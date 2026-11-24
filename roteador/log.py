"""Logs em arquivo e no terminal, no formato `chave=valor`.

Um arquivo por roteador (`logs/10.7.1.1.log`). O horário vem do relógio de
parede (`time.time`), só para o ser humano ler; os temporizadores do
protocolo usam o relógio monotônico que a casca passa ao núcleo.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from roteador.eventos import Evento


def formatar_linha(evento: Evento, quando: datetime | None = None) -> str:
    momento = quando or datetime.now()
    hora = momento.isoformat(timespec="milliseconds")
    campos = " ".join(f"{chave}={valor}" for chave, valor in evento.campos)
    if campos:
        return f"{hora} {evento.tipo} {campos}"
    return f"{hora} {evento.tipo}"


class Log:
    def __init__(self, endereco: str, diretorio: str | Path = "logs") -> None:
        self.diretorio = Path(diretorio)
        self.diretorio.mkdir(parents=True, exist_ok=True)
        self.caminho = self.diretorio / f"{endereco}.log"
        self._arquivo = open(self.caminho, "a", encoding="utf-8", buffering=1)
        self.silencio = False
        self.linhas: list[str] = []

    def registrar(self, evento: Evento, quando: float | None = None) -> str:
        if quando is None:
            momento = datetime.now()
        else:
            momento = datetime.fromtimestamp(quando)
        linha = formatar_linha(evento, momento)
        self.linhas.append(linha)
        self._arquivo.write(linha + "\n")
        return linha

    def fechar(self) -> None:
        try:
            self._arquivo.close()
        except OSError:
            pass


def agora_parede() -> float:
    return time.time()
