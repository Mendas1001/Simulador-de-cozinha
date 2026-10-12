"""
relogio.py
==========
Relógio da simulação: converte tempo real (segundos) em unidades de tempo
da simulação e vice-versa.

    1 unidade de tempo  =  `escala` segundos reais

Com escala=0.25, um pedido de burst=8 leva 2 segundos reais para ser preparado.
Todos os cozinheiros e a esteira compartilham o MESMO relógio, então a
noção de "agora" é consistente entre as threads.
"""

from __future__ import annotations

import time


class Relogio:
    def __init__(self, escala: float = 0.25) -> None:
        if escala <= 0:
            raise ValueError("escala deve ser > 0")
        self.escala = escala
        self._t0: float | None = None

    def iniciar(self) -> None:
        """Marca o instante zero da simulação."""
        self._t0 = time.monotonic()

    def agora(self) -> float:
        """Tempo atual da simulação, em unidades (float)."""
        if self._t0 is None:
            raise RuntimeError("Relogio nao iniciado: chame iniciar() antes")
        return (time.monotonic() - self._t0) / self.escala

    def segundos(self, unidades: float) -> float:
        """Converte unidades de simulação em segundos reais."""
        return unidades * self.escala

    def dormir(self, unidades: float) -> None:
        """Simula trabalho: bloqueia a thread pelo tempo proporcional."""
        time.sleep(self.segundos(unidades))
