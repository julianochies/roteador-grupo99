"""Monta a configuração de uma topologia descrita por enlaces.

`"1-2:1,2-3:2"` liga o roteador 1 ao 2 com custo 1, e o 2 ao 3 com custo 2.
O endereço virtual do roteador n no grupo G é `10.G.n.1`. Em uma máquina só,
todos usam 127.0.0.1 e portas consecutivas a partir da base.
"""

from __future__ import annotations

from roteador.config import Config, VizinhoConfig


def ler_enlaces(spec: str) -> list[tuple[int, int, int]]:
    """`1-2:1,2-3:2` → [(1, 2, 1), (2, 3, 2)]."""
    texto = spec.strip()
    if texto == "":
        return []
    enlaces: list[tuple[int, int, int]] = []
    for parte in texto.split(","):
        try:
            pontas, custo_txt = parte.split(":")
            esquerda, direita = pontas.split("-")
            a, b, custo = int(esquerda), int(direita), int(custo_txt)
        except ValueError as erro:
            raise ValueError(f"enlace invalido: {parte!r}") from erro
        if a == b or a < 1 or b < 1 or custo < 1:
            raise ValueError(f"enlace invalido: {parte!r}")
        enlaces.append((a, b, custo))
    return enlaces


def configs_da_topologia(
    spec: str,
    grupo: int = 7,
    porta_base: int = 6001,
    ip: str = "127.0.0.1",
) -> dict[int, Config]:
    """Um `Config` por roteador citado nos enlaces."""
    if not 1 <= grupo <= 254:
        raise ValueError("grupo deve estar entre 1 e 254")
    enlaces = ler_enlaces(spec)
    numeros = sorted({n for a, b, _c in enlaces for n in (a, b)})
    vizinhos: dict[int, list[VizinhoConfig]] = {n: [] for n in numeros}
    for a, b, custo in enlaces:
        vizinhos[a].append(VizinhoConfig(ip, _porta(b, porta_base), custo))
        vizinhos[b].append(VizinhoConfig(ip, _porta(a, porta_base), custo))
    configs: dict[int, Config] = {}
    for numero in numeros:
        # A ordem estável deixa o arquivo e os testes reproduzíveis.
        lista = tuple(sorted(vizinhos[numero], key=lambda v: (v.ip, v.porta, v.custo)))
        configs[numero] = Config(
            endereco=f"10.{grupo}.{numero}.1",
            porta=_porta(numero, porta_base),
            vizinhos=lista,
        )
    return configs


def _porta(numero: int, porta_base: int) -> int:
    return porta_base + numero - 1
