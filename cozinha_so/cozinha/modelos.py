"""
modelos.py
==========
Estruturas de dados puras do simulador (sem threads, sem I/O).

Tudo aqui pode ser serializado com `to_dict()`, o que facilita enviar o
estado para um frontend (JSON via Flask/FastAPI/WebSocket, por exemplo).

Convenção de tempo: todos os tempos são em "unidades de tempo" (inteiros).
A conversão para segundos reais é feita pelo `Relogio` (ver relogio.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class StatusPedido(Enum):
    """Ciclo de vida de um pedido."""
    AGUARDANDO = "Aguardando"
    PREPARANDO = "Preparando"
    CONCLUIDO = "Concluído"


@dataclass
class Pedido:
    """
    Um pedido do restaurante (equivale a um "processo" no escalonador de CPU).

    Atributos de entrada:
        id        -> identificador único do pedido
        chegada   -> Arrival Time: instante em que o pedido entra na esteira
        burst     -> Burst Time: tempo necessário para preparar o pedido

    Atributos preenchidos durante a simulação:
        status     -> Aguardando / Preparando / Concluído
        inicio     -> instante em que um cozinheiro começou a preparar
        fim        -> instante em que o preparo terminou
        cozinheiro -> nome de quem preparou
    """
    id: int
    chegada: int
    burst: int
    status: StatusPedido = StatusPedido.AGUARDANDO
    inicio: Optional[int] = None
    fim: Optional[int] = None
    cozinheiro: Optional[str] = None

    def __post_init__(self) -> None:
        if self.burst <= 0:
            raise ValueError(f"Pedido {self.id}: burst deve ser > 0")
        if self.chegada < 0:
            raise ValueError(f"Pedido {self.id}: chegada deve ser >= 0")

    # ------------------------------------------------------------------
    # Métricas calculadas
    # ------------------------------------------------------------------
    @property
    def espera(self) -> Optional[int]:
        """Tempo de Espera = início do preparo - chegada."""
        if self.inicio is None:
            return None
        return self.inicio - self.chegada

    @property
    def turnaround(self) -> Optional[int]:
        """Turnaround = fim do preparo - chegada (espera + burst)."""
        if self.fim is None:
            return None
        return self.fim - self.chegada

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------
    def copia_inicial(self) -> "Pedido":
        """
        Devolve uma cópia "limpa" (sem dados de execução).
        Garante que FCFS e SJF recebam exatamente a mesma carga inicial.
        """
        return Pedido(id=self.id, chegada=self.chegada, burst=self.burst)

    def to_dict(self) -> dict:
        """Representação em dicionário (pronta para JSON)."""
        return {
            "id": self.id,
            "chegada": self.chegada,
            "burst": self.burst,
            "status": self.status.value,
            "inicio": self.inicio,
            "fim": self.fim,
            "cozinheiro": self.cozinheiro,
            "espera": self.espera,
            "turnaround": self.turnaround,
        }
