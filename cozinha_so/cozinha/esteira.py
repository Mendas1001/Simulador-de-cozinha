"""
esteira.py
==========
"Esteira de Pedidos Globais": a fila compartilhada entre os cozinheiros.

Este é o ÚNICO ponto de contato entre as threads, então é aqui que fica toda
a sincronização. Usamos `threading.Condition`, que embute um Lock:

  * Toda leitura/alteração da fila e dos pedidos acontece com o lock tomado
    (seção crítica). Assim, dois cozinheiros nunca pegam o mesmo pedido
    (sem race condition) e nenhum dado fica corrompido.
  * A Condition permite que um cozinheiro "durma" até o próximo pedido
    chegar, sem fazer espera ocupada (busy waiting).
"""

from __future__ import annotations

import threading
from typing import Iterable, List, Optional

from .escalonadores import Escalonador
from .modelos import Pedido, StatusPedido
from .relogio import Relogio


class EsteiraPedidos:
    # Margem (em unidades) para tolerar o jitter de time.sleep/Condition.wait:
    # uma thread que acorda em t=2.97 ainda enxerga o pedido que chega em t=3.
    TOLERANCIA = 0.05

    def __init__(self, escalonador: Escalonador, relogio: Relogio) -> None:
        self._escalonador = escalonador
        self._relogio = relogio
        self._cond = threading.Condition()      # Condition = Lock + espera
        self._aguardando: List[Pedido] = []     # protegido por _cond
        self._concluidos: List[Pedido] = []     # protegido por _cond

    # ------------------------------------------------------------------
    # Carga de pedidos
    # ------------------------------------------------------------------
    def adicionar_varios(self, pedidos: Iterable[Pedido]) -> None:
        with self._cond:
            self._aguardando.extend(pedidos)
            self._cond.notify_all()

    # ------------------------------------------------------------------
    # Operações usadas pelos cozinheiros
    # ------------------------------------------------------------------
    def retirar_proximo(self, cozinheiro: str) -> Optional[Pedido]:
        """
        Entrega ao cozinheiro o próximo pedido segundo o escalonador.

        Comportamento:
          * Há pedidos que já chegaram -> escolhe um, marca como PREPARANDO
            e devolve (tudo dentro do lock).
          * Fila vazia -> devolve None (o cozinheiro pode encerrar).
          * Há pedidos, mas nenhum chegou ainda -> espera (sem gastar CPU)
            até a próxima chegada e tenta de novo.
        """
        with self._cond:
            while True:
                agora = self._relogio.agora()

                if not self._aguardando:
                    return None

                chegados = [p for p in self._aguardando
                            if p.chegada <= agora + self.TOLERANCIA]

                if chegados:
                    pedido = self._escalonador.escolher(chegados)
                    self._aguardando.remove(pedido)
                    # Estado do pedido alterado ainda dentro da seção crítica.
                    pedido.status = StatusPedido.PREPARANDO
                    pedido.cozinheiro = cozinheiro
                    # Tempos são inteiros: arredondamos ao "tick" mais próximo.
                    pedido.inicio = max(round(agora), pedido.chegada)
                    # Avisa os demais: a fila mudou (ex.: pode ter esvaziado).
                    self._cond.notify_all()
                    return pedido

                # Nenhum pedido chegou ainda: dorme até a próxima chegada.
                proxima = min(p.chegada for p in self._aguardando)
                espera_s = self._relogio.segundos(proxima - agora)
                self._cond.wait(timeout=max(espera_s, 0.001))

    def registrar_conclusao(self, pedido: Pedido) -> None:
        """Marca o pedido como concluído e o move para a lista de prontos."""
        with self._cond:
            pedido.fim = pedido.inicio + pedido.burst
            pedido.status = StatusPedido.CONCLUIDO
            self._concluidos.append(pedido)
            self._cond.notify_all()

    # ------------------------------------------------------------------
    # Consulta (útil para o frontend ler o estado em tempo real)
    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        """Cópia consistente do estado atual (tirada com o lock tomado)."""
        with self._cond:
            return {
                "aguardando": [p.to_dict() for p in self._aguardando],
                "concluidos": [p.to_dict() for p in self._concluidos],
            }

    def concluidos(self) -> List[Pedido]:
        with self._cond:
            return sorted(self._concluidos, key=lambda p: p.id)
