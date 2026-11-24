"""O que o núcleo devolve para a casca enviar, registrar ou mostrar.

O núcleo não imprime nem chama sendto. Cada operação devolve uma `Saida`:
pacotes prontos para o socket, eventos de log já estruturados e textos para
o terminal. Os testes conferem esses objetos, não a formatação da tela.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _texto(valor: object) -> str:
    return str(valor)


@dataclass(frozen=True)
class Evento:
    """Uma linha de log antes de ganhar horário.

    `campos` guarda a ordem em que as chaves foram criadas, para o arquivo
    sair estável (`origem=... seq=... de=...`).
    """

    tipo: str
    campos: tuple[tuple[str, str], ...] = ()

    def get(self, chave: str, padrao: str | None = None) -> str | None:
        for nome, valor in self.campos:
            if nome == chave:
                return valor
        return padrao

    def tem(self, **campos: object) -> bool:
        for chave, valor in campos.items():
            if self.get(chave) != _texto(valor):
                return False
        return True


def evento(nome: str, **campos: object) -> Evento:
    """Monta um evento. Valores viram texto aqui, para o log e os testes.

    O primeiro argumento é o nome (`LSP-NOVO`, `ICMP-GERADO`). Um campo também
    pode se chamar `tipo` — é o tipo ICMP ou do pacote encaminhado, outra coisa.
    """
    pares = tuple((chave, _texto(valor)) for chave, valor in campos.items())
    return Evento(nome, pares)


@dataclass
class Saida:
    """Resultado de `receber`, `tick` ou `comando`."""

    envios: list[tuple[bytes, tuple[str, int]]] = field(default_factory=list)
    eventos: list[Evento] = field(default_factory=list)
    mensagens: list[str] = field(default_factory=list)

    def acrescentar(self, outra: Saida) -> None:
        self.envios.extend(outra.envios)
        self.eventos.extend(outra.eventos)
        self.mensagens.extend(outra.mensagens)
