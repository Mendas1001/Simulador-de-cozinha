"""
simulador.py
============
Orquestra uma simulação completa (esteira + cozinheiros + relógio) e
oferece `comparar()` para rodar FCFS e SJF com a MESMA carga de pedidos.

Ponto de entrada para o frontend:
    resultados = comparar(pedidos, ouvintes=[minha_funcao])
`minha_funcao(evento)` é chamada (de várias threads!) a cada evento.
Se ela mexer em estado compartilhado, deve usar o próprio lock
ou, melhor, apenas colocar o evento numa `queue.Queue`.
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from .cozinheiro import Cozinheiro, Evento
from .escalonadores import ESCALONADORES, Escalonador
from .esteira import EsteiraPedidos
from .modelos import Pedido
from .relogio import Relogio

Ouvinte = Callable[[Evento], None]


# ----------------------------------------------------------------------
# Resultado
# ----------------------------------------------------------------------
@dataclass
class ResultadoSimulacao:
    algoritmo: str
    pedidos: List[Pedido]          # concluídos, ordenados por ID
    cozinheiros: List[str]

    @property
    def tme(self) -> float:
        """Tempo Médio de Espera."""
        return sum(p.espera for p in self.pedidos) / len(self.pedidos)

    @property
    def tmt(self) -> float:
        """Tempo Médio de Turnaround."""
        return sum(p.turnaround for p in self.pedidos) / len(self.pedidos)

    @property
    def duracao(self) -> int:
        """Makespan: instante em que o último pedido terminou."""
        return max(p.fim for p in self.pedidos)

    def to_dict(self) -> dict:
        return {
            "algoritmo": self.algoritmo,
            "tme": self.tme,
            "tmt": self.tmt,
            "duracao": self.duracao,
            "pedidos": [p.to_dict() for p in self.pedidos],
        }


# ----------------------------------------------------------------------
# Uma simulação
# ----------------------------------------------------------------------
class Simulacao:
    def __init__(self, escalonador: Escalonador, pedidos: Sequence[Pedido],
                 num_cozinheiros: int = 2, escala: float = 0.25,
                 ouvintes: Optional[Sequence[Ouvinte]] = None) -> None:
        self.escalonador = escalonador
        self.num_cozinheiros = num_cozinheiros
        self.relogio = Relogio(escala)
        self.esteira = EsteiraPedidos(escalonador, self.relogio)
        self._ouvintes = list(ouvintes or [])
        # Cópias limpas: nenhuma simulação altera os pedidos originais.
        self._pedidos = [p.copia_inicial() for p in pedidos]

    def _emitir(self, evento: Evento) -> None:
        for ouvinte in self._ouvintes:
            ouvinte(evento)

    def executar(self) -> ResultadoSimulacao:
        """Roda a simulação até todos os pedidos serem concluídos (bloqueante)."""
        self.esteira.adicionar_varios(self._pedidos)

        nomes = [f"Cozinheiro {i + 1}" for i in range(self.num_cozinheiros)]
        threads = [Cozinheiro(n, self.escalonador.nome, self.esteira,
                              self.relogio, self._emitir) for n in nomes]

        self.relogio.iniciar()          # t = 0 para todo mundo
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        return ResultadoSimulacao(self.escalonador.nome,
                                  self.esteira.concluidos(), nomes)


# ----------------------------------------------------------------------
# Comparação FCFS x SJF
# ----------------------------------------------------------------------
def comparar(pedidos: Sequence[Pedido], num_cozinheiros: int = 2,
             escala: float = 0.25, simultaneo: bool = False,
             ouvintes: Optional[Sequence[Ouvinte]] = None
             ) -> Dict[str, ResultadoSimulacao]:
    """
    Executa todos os algoritmos registrados com a mesma carga inicial.

    simultaneo=False -> um após o outro (saída do terminal mais legível)
    simultaneo=True  -> os dois ao mesmo tempo, cada um com sua própria
                        esteira e seus próprios cozinheiros
    """
    simulacoes = {nome: Simulacao(cls(), pedidos, num_cozinheiros, escala, ouvintes)
                  for nome, cls in ESCALONADORES.items()}
    resultados: Dict[str, ResultadoSimulacao] = {}

    if not simultaneo:
        for nome, sim in simulacoes.items():
            resultados[nome] = sim.executar()
        return resultados

    def rodar(nome: str, sim: Simulacao) -> None:
        resultados[nome] = sim.executar()   # dict: cada thread grava sua chave

    threads = [threading.Thread(target=rodar, args=(n, s))
               for n, s in simulacoes.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {n: resultados[n] for n in simulacoes}   # mantém a ordem


# ----------------------------------------------------------------------
# Cargas de pedidos
# ----------------------------------------------------------------------
def carga_padrao() -> List[Pedido]:
    """Carga fixa (determinística) em que FCFS e SJF se comportam diferente."""
    #            id chegada burst
    dados = [(1, 0, 8), (2, 1, 4), (3, 2, 9), (4, 3, 5),
             (5, 4, 2), (6, 5, 6), (7, 6, 3), (8, 7, 1)]
    return [Pedido(i, c, b) for i, c, b in dados]


def carga_aleatoria(n: int, seed: Optional[int] = None) -> List[Pedido]:
    """Gera n pedidos aleatórios (use seed para repetir a mesma carga)."""
    rng = random.Random(seed)
    pedidos, chegada = [], 0
    for i in range(1, n + 1):
        pedidos.append(Pedido(i, chegada, rng.randint(1, 9)))
        chegada += rng.randint(0, 3)
    return pedidos
