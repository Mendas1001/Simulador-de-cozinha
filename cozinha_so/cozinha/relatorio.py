"""
relatorio.py
============
Saída em texto: log em tempo real no console e relatório final
(tabela de pedidos, Gráfico de Gantt em texto, TME e comparação).

Nada aqui altera a simulação; só lê eventos e resultados.
"""

from __future__ import annotations

import threading
from typing import Dict

from .cozinheiro import Evento, TipoEvento
from .simulador import ResultadoSimulacao


# ----------------------------------------------------------------------
# Log em tempo real
# ----------------------------------------------------------------------
class ImpressoraConsole:
    """
    Ouvinte de eventos que imprime no terminal.
    O lock evita que linhas de threads diferentes se misturem no meio.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __call__(self, ev: Evento) -> None:
        prefixo = f"[t={ev.tempo:>3}] [{ev.algoritmo:<4}]"
        if ev.tipo is TipoEvento.INICIO:
            msg = (f"{ev.cozinheiro} {ev.algoritmo} pegou o Pedido {ev.pedido_id} "
                   f"(preparo: {ev.burst}u)")
        elif ev.tipo is TipoEvento.FIM:
            msg = f"{ev.cozinheiro} terminou o Pedido {ev.pedido_id}"
        else:
            msg = f"{ev.cozinheiro} ficou ocioso (sem mais pedidos)"
        with self._lock:
            print(f"{prefixo} {msg}", flush=True)


# ----------------------------------------------------------------------
# Relatório final
# ----------------------------------------------------------------------
def tabela_pedidos(res: ResultadoSimulacao) -> str:
    linhas = [f"{'Pedido':<7}{'Chegada':>8}{'Preparo':>8}{'Início':>8}"
              f"{'Fim':>6}{'Espera':>8}{'Turnaround':>12}  Cozinheiro"]
    for p in res.pedidos:
        linhas.append(f"P{p.id:<6}{p.chegada:>8}{p.burst:>8}{p.inicio:>8}"
                      f"{p.fim:>6}{p.espera:>8}{p.turnaround:>12}  {p.cozinheiro}")
    return "\n".join(linhas)


def gantt_texto(res: ResultadoSimulacao) -> str:
    """
    Gráfico de Gantt em texto: uma linha por cozinheiro, uma coluna por
    unidade de tempo. '.' = ocioso.

        Cozinheiro 1 |P1 P1 P1 P4 P4 .  |
        Cozinheiro 2 |P2 P2 P3 P3 P3 P3 |
                      0  1  2  3  4  5  6
    """
    largura = max(len(f"P{p.id}") for p in res.pedidos) + 1
    total = res.duracao
    rotulo = max(len(n) for n in res.cozinheiros)

    def celula(txt: str) -> str:
        return txt.ljust(largura)

    linhas = []
    for nome in res.cozinheiros:
        slots = [celula(".")] * total
        for p in res.pedidos:
            if p.cozinheiro == nome:
                for t in range(p.inicio, p.fim):
                    slots[t] = celula(f"P{p.id}")
        linhas.append(f"{nome:<{rotulo}} |{''.join(slots)}|")

    eixo = "".join(celula(str(t)) for t in range(total + 1))
    linhas.append(f"{'tempo':<{rotulo}}  {eixo}")
    return "\n".join(linhas)


def relatorio_algoritmo(res: ResultadoSimulacao) -> str:
    return "\n".join([
        f"=== {res.algoritmo} ===",
        tabela_pedidos(res),
        "",
        "Gráfico de Gantt:",
        gantt_texto(res),
        "",
        f"Tempo Médio de Espera (TME):       {res.tme:.2f}",
        f"Tempo Médio de Turnaround (TMT):   {res.tmt:.2f}",
        f"Duração total (makespan):          {res.duracao}",
    ])


def relatorio_comparativo(resultados: Dict[str, ResultadoSimulacao]) -> str:
    partes = ["", "=" * 70, "RELATÓRIO COMPARATIVO", "=" * 70]
    for res in resultados.values():
        partes += ["", relatorio_algoritmo(res)]

    partes += ["", "=" * 70, "RESUMO", "=" * 70,
               f"{'Algoritmo':<10}{'TME':>8}{'TMT':>8}{'Duração':>10}"]
    for res in resultados.values():
        partes.append(f"{res.algoritmo:<10}{res.tme:>8.2f}{res.tmt:>8.2f}{res.duracao:>10}")

    melhor = min(resultados.values(), key=lambda r: r.tme)
    empate = [r for r in resultados.values() if abs(r.tme - melhor.tme) < 1e-9]
    if len(empate) > 1:
        partes.append("\nResultado: empate no TME.")
    else:
        partes.append(f"\nMenor TME: {melhor.algoritmo} ({melhor.tme:.2f}).")
    return "\n".join(partes)
