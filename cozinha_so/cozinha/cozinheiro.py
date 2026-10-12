"""
cozinheiro.py
=============
Eventos da simulação e a thread do cozinheiro.

Os cozinheiros não imprimem nada diretamente: eles emitem `Evento`s para
uma função `emitir`. Quem decide o que fazer com o evento (imprimir no
terminal, enviar por WebSocket, guardar em fila para a interface...) é
quem monta a simulação. É esse desacoplamento que permite plugar um
frontend depois sem mexer na lógica.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Callable

from .esteira import EsteiraPedidos
from .relogio import Relogio


class TipoEvento(Enum):
    INICIO = "inicio"   # cozinheiro pegou um pedido
    FIM = "fim"         # cozinheiro terminou um pedido
    OCIOSO = "ocioso"   # cozinheiro encerrou (fila vazia)


@dataclass
class Evento:
    tipo: TipoEvento
    algoritmo: str
    tempo: int              # tempo da simulação (unidades)
    cozinheiro: str
    pedido_id: int | None = None
    burst: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tipo"] = self.tipo.value
        return d


class Cozinheiro(threading.Thread):
    """Uma estação de trabalho: pega pedidos da esteira até ela esvaziar."""

    def __init__(self, nome: str, algoritmo: str, esteira: EsteiraPedidos,
                 relogio: Relogio, emitir: Callable[[Evento], None]) -> None:
        super().__init__(name=nome, daemon=True)
        self.nome = nome
        self.algoritmo = algoritmo
        self._esteira = esteira
        self._relogio = relogio
        self._emitir = emitir

    def run(self) -> None:
        while True:
            # Seção crítica fica dentro da esteira; aqui só chamamos a API.
            pedido = self._esteira.retirar_proximo(self.nome)
            if pedido is None:
                self._emitir(Evento(TipoEvento.OCIOSO, self.algoritmo,
                                    round(self._relogio.agora()), self.nome))
                return

            self._emitir(Evento(TipoEvento.INICIO, self.algoritmo, pedido.inicio,
                                self.nome, pedido.id, pedido.burst))

            # Simula o preparo: sleep proporcional ao burst (fora do lock,
            # para que o outro cozinheiro trabalhe em paralelo).
            self._relogio.dormir(pedido.burst)

            self._esteira.registrar_conclusao(pedido)
            self._emitir(Evento(TipoEvento.FIM, self.algoritmo, pedido.fim,
                                self.nome, pedido.id, pedido.burst))
