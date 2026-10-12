"""
escalonadores.py
================
Algoritmos de escalonamento, isolados do resto do sistema.

Um escalonador aqui tem UMA responsabilidade: dado o conjunto de pedidos
que JÁ CHEGARAM e estão aguardando, escolher qual será preparado a seguir.
Ele não conhece threads, locks nem relógio, o que o torna fácil de testar
e de estender (basta criar uma nova subclasse, ex.: Prioridade, Round Robin).

Ambos os algoritmos são NÃO-PREEMPTIVOS: depois que um cozinheiro começa
um pedido, ele só o largará quando terminar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from .modelos import Pedido


class Escalonador(ABC):
    """Interface comum a todos os algoritmos."""

    nome: str = "BASE"

    @abstractmethod
    def escolher(self, candidatos: Sequence[Pedido]) -> Pedido:
        """Escolhe, entre os candidatos (lista não vazia), o próximo pedido."""


class FCFS(Escalonador):
    """First-Come, First-Served: atende por ordem de chegada."""

    nome = "FCFS"

    def escolher(self, candidatos: Sequence[Pedido]) -> Pedido:
        # Desempate por ID para o resultado ser determinístico.
        return min(candidatos, key=lambda p: (p.chegada, p.id))


class SJFNaoPreemptivo(Escalonador):
    """Shortest Job First (não-preemptivo): menor tempo de preparo primeiro."""

    nome = "SJF"

    def escolher(self, candidatos: Sequence[Pedido]) -> Pedido:
        # Critério principal: menor burst. Desempates: chegada e ID.
        return min(candidatos, key=lambda p: (p.burst, p.chegada, p.id))


# Registro simples: facilita montar a comparação e expor a lista ao frontend.
ESCALONADORES = {
    "FCFS": FCFS,
    "SJF": SJFNaoPreemptivo,
}
