"""
relatorio.py
============
Saída em texto: log em tempo real no console e relatório final
(tabela de pedidos, Gráfico de Gantt em texto, TME e comparação).

Nada aqui altera a simulação; só lê eventos e resultados.
"""

from __future__ import annotations

import sys
import threading
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict

from .cozinheiro import Evento, TipoEvento
from .simulador import ResultadoSimulacao


def fmt2(x: float) -> str:
    """
    Formata com 2 casas arredondando 'meio para cima' (3.125 -> 3.13).
    O f"{x:.2f}" do Python arredonda para o par mais próximo (3.125 -> 3.12),
    o que divergia do que a interface web mostra e do cálculo feito à mão.
    """
    return str(Decimal(repr(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------
# Log em tempo real
# ----------------------------------------------------------------------
class ImpressoraConsole:
    """
    Ouvinte de eventos que imprime no terminal (e, opcionalmente, repassa
    cada trecho escrito para a interface web via `ao_escrever`).

    sincronizada=True  -> um lock garante que cada linha sai INTEIRA.
    sincronizada=False -> SEM lock e escrevendo cada linha em pedaços
                          pequenos: quando duas threads escrevem ao mesmo
                          tempo, os pedaços se intercalam e a saída sai
                          embaralhada (o mesmo problema de uma impressora
                          compartilhada sem exclusão mútua).
    """

    PEDACO = 14          # caracteres por escrita no modo sem sincronização
    PAUSA = 0.004        # s entre pedaços: dá chance de outra thread escrever no meio

    def __init__(self, sincronizada: bool = True, ao_escrever=None) -> None:
        self._sincronizada = sincronizada
        self._ao_escrever = ao_escrever          # callback(trecho, algoritmo)
        self._lock = threading.Lock()

    @staticmethod
    def formatar(ev: Evento) -> str:
        """Texto da linha (só caracteres que o terminal do Windows aceita)."""
        prefixo = f"[t={ev.tempo:>3}] [{ev.algoritmo:<4}]"
        if ev.tipo is TipoEvento.CHEGADA:
            msg = f"Pedido {ev.pedido_id} chegou na esteira (preparo: {ev.burst}u)"
        elif ev.tipo is TipoEvento.INICIO:
            msg = (f"{ev.cozinheiro} {ev.algoritmo} pegou o Pedido {ev.pedido_id} "
                   f"(preparo: {ev.burst}u)")
        elif ev.tipo is TipoEvento.FIM:
            msg = f"{ev.cozinheiro} terminou o Pedido {ev.pedido_id}"
        elif ev.tipo is TipoEvento.CONFLITO:
            msg = (f"[!] CONFLITO: {ev.outro} e {ev.cozinheiro} pegaram o "
                   f"Pedido {ev.pedido_id} ao mesmo tempo")
        else:
            msg = f"{ev.cozinheiro} ficou ocioso (sem mais pedidos)"
        return f"{prefixo} {msg}\n"

    def __call__(self, ev: Evento) -> None:
        linha = self.formatar(ev)
        if self._sincronizada:
            with self._lock:                       # linha inteira, sem intercalar
                self._escrever(linha, ev.algoritmo)
        else:
            # SEM lock e em pedaços: outra thread pode escrever no meio.
            for k in range(0, len(linha), self.PEDACO):
                self._escrever(linha[k:k + self.PEDACO], ev.algoritmo)
                time.sleep(self.PAUSA)

    def _escrever(self, trecho: str, algoritmo: str) -> None:
        sys.stdout.write(trecho)
        sys.stdout.flush()
        if self._ao_escrever:
            self._ao_escrever(trecho, algoritmo)


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
    linhas = [
        f"=== {res.algoritmo} ===",
        tabela_pedidos(res),
        "",
        "Gráfico de Gantt:",
        gantt_texto(res),
        "",
        f"Tempo Médio de Espera (TME):       {fmt2(res.tme)}",
        f"Tempo Médio de Turnaround (TMT):   {fmt2(res.tmt)}",
        f"Duração total (makespan):          {res.duracao}",
    ]
    if not res.sincronizada:
        total = len({p.id for p in res.pedidos})
        linhas += [
            "",
            "[!] EXECUÇÃO SEM SINCRONIZAÇÃO - resultados NÃO são confiáveis:",
            f"    pedidos diferentes: {total} | preparos realizados: {len(res.pedidos)}",
            f"    pedidos pegos por 2 cozinheiros (conflitos): {res.conflitos}",
            f"    contador de entregas: {res.contador_entregas} (esperado {len(res.pedidos)})",
        ]
    return "\n".join(linhas)


def relatorio_comparativo(resultados: Dict[str, ResultadoSimulacao]) -> str:
    partes = ["", "=" * 70, "RELATÓRIO COMPARATIVO", "=" * 70]
    if any(not r.sincronizada for r in resultados.values()):
        partes.append("[!] MODO SEM SINCRONIZAÇÃO (condição de corrida): números contaminados.")
    for res in resultados.values():
        partes += ["", relatorio_algoritmo(res)]

    partes += ["", "=" * 70, "RESUMO", "=" * 70,
               f"{'Algoritmo':<10}{'TME':>8}{'TMT':>8}{'Duração':>10}"]
    for res in resultados.values():
        partes.append(f"{res.algoritmo:<10}{fmt2(res.tme):>8}{fmt2(res.tmt):>8}{res.duracao:>10}")

    melhor = min(resultados.values(), key=lambda r: r.tme)
    empate = [r for r in resultados.values() if abs(r.tme - melhor.tme) < 1e-9]
    if len(empate) > 1:
        partes.append("\nResultado: empate no TME.")
    else:
        partes.append(f"\nMenor TME: {melhor.algoritmo} ({fmt2(melhor.tme)}).")
    return "\n".join(partes)
