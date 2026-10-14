"""
esteira.py
==========
"Esteira de Pedidos Globais": a fila compartilhada entre os cozinheiros.

Este é o ÚNICO ponto de contato entre as threads, então é aqui que fica toda
a sincronização. A esteira tem dois modos, para DEMONSTRAR por que o Lock existe:

  sincronizada=True  (padrão)
      Toda leitura/alteração da fila e dos pedidos acontece com o lock tomado
      (seção crítica, via `threading.Condition`). Dois cozinheiros nunca pegam
      o mesmo pedido e nenhum dado fica corrompido.

  sincronizada=False  (demonstração de condição de corrida)
      A MESMA lógica, mas sem nenhum lock. O padrão é o clássico
      "verifica-e-depois-age" (check-then-act):
          1. LÊ    -> olha a fila
          2. DECIDE-> escolhe o pedido
          3. AGE   -> remove da fila e marca como "Preparando"
      Se outro cozinheiro executar o passo 1 ou 2 antes do passo 3 do primeiro,
      os dois escolhem o MESMO pedido e o preparam em duplicidade.
      Há também um contador de entregas atualizado com "lê, soma, escreve" sem
      proteção: duas threads leem o mesmo valor e uma atualização se perde
      (lost update).

      IMPORTANTE (honestidade didática): em CPython o GIL torna a janela entre
      os passos 2 e 3 minúscula, então a corrida real seria rara e difícil de
      reproduzir numa apresentação. Por isso alargamos a janela com um
      time.sleep curto (`janela_s`). O defeito de projeto (falta de exclusão
      mútua) é real; só tornamos o azar reproduzível.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Iterable, List, Optional

from .escalonadores import Escalonador
from .modelos import Pedido, StatusPedido
from .relogio import Relogio

# (pedido, quem_pegou_primeiro, quem_pegou_depois) -> None
AoConflito = Callable[[Pedido, str, str], None]


class EsteiraPedidos:
    # Margem (em unidades) para tolerar o jitter de time.sleep/Condition.wait:
    # uma thread que acorda em t=2.97 ainda enxerga o pedido que chega em t=3.
    TOLERANCIA = 0.05

    def __init__(self, escalonador: Escalonador, relogio: Relogio,
                 sincronizada: bool = True, janela_s: float = 0.05,
                 ao_conflito: Optional[AoConflito] = None) -> None:
        self._escalonador = escalonador
        self._relogio = relogio
        self._sincronizada = sincronizada
        self._janela_s = janela_s
        self._ao_conflito = ao_conflito

        self._cond = threading.Condition()      # Condition = Lock + espera
        self._aguardando: List[Pedido] = []     # protegido por _cond (modo sincronizado)
        self._concluidos: List[Pedido] = []     # idem
        self._total_entregas = 0                # contador compartilhado (ver registrar_conclusao)

        # Instrumentação SÓ para detectar/contar duplicidades. Não faz parte da
        # lógica protegida: não influencia quem pega o quê.
        self._diag = threading.Lock()
        self._entregues: Dict[int, str] = {}    # id do pedido -> 1º cozinheiro que o pegou
        self._conflitos = 0

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
        """Entrega ao cozinheiro o próximo pedido segundo o escalonador."""
        if self._sincronizada:
            return self._retirar_sincronizado(cozinheiro)
        return self._retirar_sem_sincronizacao(cozinheiro)

    def _retirar_sincronizado(self, cozinheiro: str) -> Optional[Pedido]:
        """
        Versão correta: ler, decidir e agir acontecem DENTRO do lock,
        como uma única operação indivisível.

          * Há pedidos que já chegaram -> escolhe um, marca como PREPARANDO
            e devolve.
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
                    self._registrar_entrega(pedido, cozinheiro)
                    # Avisa os demais: a fila mudou (ex.: pode ter esvaziado).
                    self._cond.notify_all()
                    return pedido

                # Nenhum pedido chegou ainda: dorme até a próxima chegada.
                proxima = min(p.chegada for p in self._aguardando)
                espera_s = self._relogio.segundos(proxima - agora)
                self._cond.wait(timeout=max(espera_s, 0.001))

    def _retirar_sem_sincronizacao(self, cozinheiro: str) -> Optional[Pedido]:
        """
        Versão INCORRETA de propósito (demonstração): sem lock algum.
        Repare nos três passos separados: LÊ -> DECIDE -> AGE.
        """
        while True:
            agora = self._relogio.agora()

            # (1) LÊ a fila, sem proteção
            if not self._aguardando:
                return None
            chegados = [p for p in list(self._aguardando)
                        if p.chegada <= agora + self.TOLERANCIA]
            if not chegados:
                time.sleep(0.005)       # espera ocupada: não há Condition para dormir
                continue

            # (2) DECIDE qual pedido pegar
            pedido = self._escalonador.escolher(chegados)

            # >>> JANELA DA CONDIÇÃO DE CORRIDA <<<
            # Aqui o outro cozinheiro também lê a fila, ainda cheia, e decide
            # pelo MESMO pedido (ver a nota no topo do arquivo).
            time.sleep(self._janela_s)

            # (3) AGE: remove da fila e marca como "Preparando"
            try:
                self._aguardando.remove(pedido)
            except ValueError:
                pass                    # o outro já tinha removido... e mesmo assim vamos prepará-lo!
            pedido.status = StatusPedido.PREPARANDO
            pedido.cozinheiro = cozinheiro          # sobrescreve quem pegou antes
            pedido.inicio = max(round(agora), pedido.chegada)
            self._registrar_entrega(pedido, cozinheiro)
            return pedido

    def registrar_conclusao(self, pedido: Pedido) -> None:
        """Marca o pedido como concluído, guarda na lista e conta a entrega."""
        if self._sincronizada:
            with self._cond:
                pedido.fim = pedido.inicio + pedido.burst
                pedido.status = StatusPedido.CONCLUIDO
                self._concluidos.append(pedido)
                self._total_entregas += 1           # protegido pelo lock
                self._cond.notify_all()
        else:
            pedido.fim = pedido.inicio + pedido.burst
            pedido.status = StatusPedido.CONCLUIDO
            self._concluidos.append(pedido)
            # Lost update: lê, (outra thread lê o mesmo valor), escreve.
            lido = self._total_entregas
            time.sleep(self._janela_s / 2)
            self._total_entregas = lido + 1

    # ------------------------------------------------------------------
    # Instrumentação / consulta
    # ------------------------------------------------------------------
    def _registrar_entrega(self, pedido: Pedido, cozinheiro: str) -> None:
        """Detecta (sem interferir) um pedido entregue a dois cozinheiros."""
        with self._diag:
            primeiro = self._entregues.setdefault(pedido.id, cozinheiro)
            duplicado = primeiro != cozinheiro
            if duplicado:
                self._conflitos += 1
        if duplicado and self._ao_conflito:
            self._ao_conflito(pedido, primeiro, cozinheiro)

    @property
    def conflitos(self) -> int:
        """Quantas vezes um pedido foi entregue a um 2º cozinheiro."""
        with self._diag:
            return self._conflitos

    @property
    def total_entregas(self) -> int:
        """Valor do contador compartilhado (pode estar errado sem sincronização)."""
        return self._total_entregas

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
