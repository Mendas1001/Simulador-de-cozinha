"""
servidor.py - ponte entre o backend (cozinha/) e o frontend (web/)

Como funciona:
  1. O navegador chama  POST /api/iniciar  com as opções da simulação.
  2. Aqui rodamos `comparar(..., simultaneo=True)` numa thread de fundo
     (FCFS e SJF ao mesmo tempo, cada um com seus cozinheiros).
     Com `sincronizada=False` a esteira roda SEM Lock (demo de condição de corrida).
  3. Cada Evento emitido pelos cozinheiros vira um dicionário guardado
     numa lista (histórico) protegida por uma Condition.
  4. O navegador abre  GET /api/stream  (Server-Sent Events) e recebe os
     eventos em tempo real, um por um. Se a página for recarregada no meio
     da simulação, o histórico inteiro é reenviado e a tela se reconstrói.

Uso:
    pip install flask
    python servidor.py            # abre http://127.0.0.1:5000
    python servidor.py --porta 8000
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
import webbrowser
from typing import List, Optional

from flask import Flask, Response, jsonify, request

from cozinha.cozinheiro import Evento
from cozinha.relatorio import ImpressoraConsole
from cozinha.simulador import carga_aleatoria, carga_padrao, comparar

app = Flask(__name__, static_folder="web", static_url_path="")


# ----------------------------------------------------------------------
# Execução: histórico de eventos compartilhado entre a simulação e o SSE
# ----------------------------------------------------------------------
class Execucao:
    """
    Guarda os eventos de UMA simulação.
    - A simulação (várias threads) chama `publicar`.
    - Cada conexão SSE lê a lista a partir do ponto onde parou.
    Tudo sob a mesma Condition, então ninguém lê a lista pela metade.
    """

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.eventos: List[dict] = []
        self.finalizada = False

    def publicar(self, evento: dict) -> None:
        with self.cond:
            self.eventos.append(evento)
            self.cond.notify_all()

    def ouvinte(self, ev: Evento) -> None:
        """Ouvinte de eventos do backend: converte e publica."""
        self.publicar(ev.to_dict())

    def finalizar(self) -> None:
        with self.cond:
            self.finalizada = True
            self.cond.notify_all()


_atual: Optional[Execucao] = None
_trava = threading.Lock()          # protege a troca de `_atual`


def _rodar(exe: Execucao, pedidos, cozinheiros: int, escala: float,
           sincronizada: bool) -> None:
    """Corpo da thread de fundo: roda FCFS x SJF e publica o resultado."""
    try:
        # O console escreve no terminal E manda cada trecho escrito para a tela:
        # o log da interface é a saída real do console (inclusive embaralhada).
        console = ImpressoraConsole(
            sincronizada,
            ao_escrever=lambda trecho, alg: exe.publicar(
                {"tipo": "console", "algoritmo": alg, "texto": trecho}))
        resultados = comparar(pedidos, num_cozinheiros=cozinheiros, escala=escala,
                              simultaneo=True, sincronizada=sincronizada,
                              ouvintes=[exe.ouvinte, console])
        exe.publicar({"tipo": "fim_geral",
                      "resultados": {n: r.to_dict() for n, r in resultados.items()}})
    except Exception as e:                       # noqa: BLE001 - vai para a tela
        exe.publicar({"tipo": "erro", "mensagem": str(e)})
    finally:
        exe.finalizar()


# ----------------------------------------------------------------------
# Rotas
# ----------------------------------------------------------------------
@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/estado")
def estado():
    """Diz se já existe uma simulação (para a página recarregada reconectar)."""
    exe = _atual
    return jsonify(existe=exe is not None,
                   finalizada=bool(exe and exe.finalizada))


@app.post("/api/iniciar")
def iniciar():
    global _atual
    dados = request.get_json(silent=True) or {}

    # --- validação das opções vindas do navegador -----------------------
    try:
        cozinheiros = int(dados.get("cozinheiros", 2))
        escala = float(dados.get("escala", 0.3))
        carga = dados.get("carga", "padrao")
        n = int(dados.get("n", 10))
        seed = dados.get("seed")
        seed = int(seed) if seed not in (None, "") else random.randrange(1_000_000)
        sincronizada = bool(dados.get("sincronizada", True))
    except (TypeError, ValueError):
        return jsonify(erro="Opções inválidas."), 400
    if not 1 <= cozinheiros <= 5:
        return jsonify(erro="Use de 1 a 5 cozinheiros."), 400
    if not 0.02 <= escala <= 2:
        return jsonify(erro="Velocidade fora do intervalo."), 400
    if carga == "aleatoria" and not 1 <= n <= 30:
        return jsonify(erro="Use de 1 a 30 pedidos."), 400

    pedidos = carga_aleatoria(n, seed) if carga == "aleatoria" else carga_padrao()

    with _trava:
        if _atual is not None and not _atual.finalizada:
            return jsonify(erro="Já existe uma simulação em andamento."), 409
        exe = Execucao()
        _atual = exe

    # Primeiro evento: configuração (a tela monta os painéis a partir dele).
    exe.publicar({
        "tipo": "config",
        "algoritmos": ["FCFS", "SJF"],
        "cozinheiros": [f"Cozinheiro {i + 1}" for i in range(cozinheiros)],
        "escala": escala,
        "sincronizada": sincronizada,
        "carga": carga,
        "seed": seed if carga == "aleatoria" else None,
        "inicio_epoch_ms": int(time.time() * 1000),   # relógio comum da tela
        "pedidos": [p.to_dict() for p in pedidos],
    })
    threading.Thread(target=_rodar, args=(exe, pedidos, cozinheiros, escala, sincronizada),
                     daemon=True).start()
    return jsonify(ok=True)


@app.get("/api/stream")
def stream():
    """Server-Sent Events: envia o histórico e depois cada novo evento."""
    exe = _atual
    if exe is None:
        return jsonify(erro="Nenhuma simulação iniciada."), 404

    def gerar():
        i = 0
        while True:
            with exe.cond:
                while i >= len(exe.eventos) and not exe.finalizada:
                    if not exe.cond.wait(timeout=15):
                        break                     # timeout: manda um "ping"
                novos = exe.eventos[i:]
                i += len(novos)
                terminou = exe.finalizada and i >= len(exe.eventos)
            for ev in novos:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if not novos:
                yield ": ping\n\n"               # mantém a conexão viva
            if terminou:
                return

    return Response(gerar(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ----------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Servidor do simulador de cozinha")
    ap.add_argument("--porta", type=int, default=5000)
    ap.add_argument("--sem-navegador", action="store_true",
                    help="não abrir o navegador automaticamente")
    args = ap.parse_args()

    url = f"http://127.0.0.1:{args.porta}"
    print(f"Simulador rodando em {url}  (Ctrl+C para sair)")
    if not args.sem_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    # debug=False: o reloader do Flask reiniciaria o processo e as threads.
    app.run(host="127.0.0.1", port=args.porta, debug=False, threaded=True)
