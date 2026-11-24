"""Dijkstra sobre a LSDB, escrito com `heapq` (permitido pelo enunciado).

O grafo é dirigido: o LSP de O anuncia as arestas que saem de O. Um roteador
que só aparece como vizinho de alguém é alcançável, mas não é expandido,
porque não há LSP dele.

Em empate de custo fica o caminho cujo primeiro salto tem o menor endereço
virtual. O resultado da demonstração e dos testes não muda de uma execução
para outra. O enunciado aceita qualquer caminho de custo mínimo; o desempate
só escolhe um deles de forma fixa.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from roteador.enderecos import rede_de


@dataclass(frozen=True)
class Passo:
    """Uma linha da tabela de iterações, no estilo da aula.

    `adicionou` é o nó que entrou em N' neste passo. Distâncias ausentes são
    infinitas (o nó ainda não foi descoberto).
    """

    adicionou: str
    confirmados: tuple[str, ...]
    distancias: tuple[tuple[str, int], ...]
    predecessores: tuple[tuple[str, str], ...]
    primeiros_saltos: tuple[tuple[str, str], ...]


def dijkstra(
    arestas: dict[str, list[tuple[str, int]]],
    origem: str,
) -> dict[str, tuple[str, int]]:
    """Tabela `{rede: (próximo salto, custo)}`, sem a própria rede."""
    tabela, _passos = calcular(arestas, origem, registrar=False)
    return tabela


def dijkstra_passos(
    arestas: dict[str, list[tuple[str, int]]],
    origem: str,
) -> list[Passo]:
    """A mesma execução, com a tabela de iterações para o relatório."""
    _tabela, passos = calcular(arestas, origem, registrar=True)
    return passos


def calcular(
    arestas: dict[str, list[tuple[str, int]]],
    origem: str,
    registrar: bool,
) -> tuple[dict[str, tuple[str, int]], list[Passo]]:
    # melhor[no] = (custo, primeiro salto ou None na origem)
    melhor: dict[str, tuple[int, str | None]] = {origem: (0, None)}
    predecessor: dict[str, str] = {}
    # heapq não diminui chave: empurramos outra entrada e ignoramos a velha
    # quando ela sai, se o nó já foi fechado ou se o par (custo, salto) mudou.
    # A terceira chave é o endereço com octetos alinhados, só para o
    # desempate da fila ser numérico ("10.7.2.1" antes de "10.7.10.1").
    fila: list[tuple[int, str, str, str]] = [(0, "", _chave(origem), origem)]
    fechados: set[str] = set()
    passos: list[Passo] = []

    while fila:
        custo, salto_chave, _ordem, no = heapq.heappop(fila)
        if no in fechados:
            continue
        custo_melhor, salto_melhor = melhor[no]
        if custo != custo_melhor or salto_chave != _chave(salto_melhor):
            continue
        fechados.add(no)
        for vizinho, peso in _vizinhos_ordenados(arestas, no):
            novo_custo = custo + peso
            if no == origem:
                novo_salto: str | None = vizinho
            else:
                novo_salto = salto_melhor
            atual = melhor.get(vizinho)
            if atual is not None and (novo_custo, _chave(novo_salto)) >= (
                atual[0],
                _chave(atual[1]),
            ):
                continue
            melhor[vizinho] = (novo_custo, novo_salto)
            predecessor[vizinho] = no
            heapq.heappush(
                fila, (novo_custo, _chave(novo_salto), _chave(vizinho), vizinho)
            )
        # O passo mostra N' e as distâncias já relaxadas por este nó.
        if registrar:
            passos.append(_passo(no, fechados, melhor, predecessor))

    tabela: dict[str, tuple[str, int]] = {}
    for no, (custo_no, salto) in melhor.items():
        if no == origem or salto is None:
            continue
        # Dois roteadores na mesma /24 não ocorrem com o endereçamento do
        # trabalho. Se ocorrer, fica o de menor custo e, no empate, o menor salto.
        rede = rede_de(no)
        anterior = tabela.get(rede)
        if anterior is None or (custo_no, salto) < (anterior[1], anterior[0]):
            tabela[rede] = (salto, custo_no)
    return tabela, passos


def _vizinhos_ordenados(
    arestas: dict[str, list[tuple[str, int]]], no: str
) -> list[tuple[str, int]]:
    return sorted(arestas.get(no, ()), key=lambda item: item[0])


def _chave(endereco: str | None) -> str:
    """Octetos com 3 dígitos, para a ordem numérica coincidir com a alfabética."""
    if not endereco:
        return ""
    return ".".join(f"{int(parte):03d}" for parte in endereco.split("."))


def _passo(
    adicionou: str,
    fechados: set[str],
    melhor: dict[str, tuple[int, str | None]],
    predecessor: dict[str, str],
) -> Passo:
    nos = sorted(melhor)
    return Passo(
        adicionou=adicionou,
        confirmados=tuple(sorted(fechados)),
        distancias=tuple((no, melhor[no][0]) for no in nos),
        predecessores=tuple(
            (no, predecessor[no]) for no in nos if no in predecessor
        ),
        primeiros_saltos=tuple(
            (no, melhor[no][1]) for no in nos if melhor[no][1] is not None
        ),
    )
