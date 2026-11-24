"""Relógio que a casca consulta. O núcleo só recebe o número `now`.

`RelogioReal` usa `time.monotonic`, que não anda para trás se o sistema
ajustar a hora. `--escala-tempo 0.1` faz o tempo virtual passar dez vezes
mais rápido, para o teste com UDP de verdade não esperar 20 s.

`RelogioFalso` deixa o teste avançar 90 s de envelhecimento num instante.
"""

from __future__ import annotations

import time


class RelogioReal:
    def __init__(self, escala: float = 1.0) -> None:
        if escala <= 0:
            raise ValueError("escala de tempo deve ser positiva")
        self.escala = escala
        self._inicio = time.monotonic()

    def agora(self) -> float:
        return (time.monotonic() - self._inicio) / self.escala


class RelogioFalso:
    def __init__(self, inicio: float = 0.0) -> None:
        self.t = inicio

    def agora(self) -> float:
        return self.t

    def avancar(self, segundos: float) -> None:
        self.t += segundos
