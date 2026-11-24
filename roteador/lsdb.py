"""Base de estados de enlace (LSDB).

Cada origem guarda só o LSP mais novo. O número de sequência decide o que é
cópia ou LSP antigo (seção Recebimento). O LSP do próprio roteador não
envelhece: a fonte somos nós, e a renovação sai a cada 30 s.
"""

from __future__ import annotations

from dataclasses import dataclass

from roteador.pacotes import Lsp


@dataclass
class Entrada:
    lsp: Lsp
    bruto: bytes
    recebido_em: float
    proprio: bool


class LSDB:
    def __init__(self) -> None:
        self._entradas: dict[str, Entrada] = {}

    def obter(self, origem: str) -> Entrada | None:
        return self._entradas.get(origem)

    def definir(self, lsp: Lsp, bruto: bytes, now: float, proprio: bool) -> None:
        self._entradas[lsp.origem] = Entrada(lsp, bruto, now, proprio)

    def todas(self) -> list[Entrada]:
        return list(self._entradas.values())

    def origens(self) -> list[str]:
        return sorted(self._entradas)

    def arestas(self) -> dict[str, list[tuple[str, int]]]:
        """Grafo dirigido: cada LSP de O vira as arestas O → vizinho."""
        return {
            entrada.lsp.origem: list(entrada.lsp.vizinhos)
            for entrada in self._entradas.values()
        }

    def expirar(self, now: float, limite: float, eu: str) -> list[Entrada]:
        """Remove LSPs alheios sem renovação há `limite` segundos (90 s).

        O LSP próprio nunca sai por aqui. O roteador que abandonou a rede
        some da LSDB dos outros quando o LSP dele deixa de ser renovado.
        """
        removidas: list[Entrada] = []
        for origem, entrada in list(self._entradas.items()):
            if entrada.proprio or origem == eu:
                continue
            idade = now - entrada.recebido_em
            if idade >= limite:
                removidas.append(entrada)
                del self._entradas[origem]
        return removidas
