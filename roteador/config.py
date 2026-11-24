"""Leitura do arquivo de configuração.

O enunciado deixa o formato a critério do grupo, desde que o arquivo traga o
endereço virtual, a porta UDP e a lista de vizinhos (IP real, porta, custo).
Uma linha por vizinho facilita a interoperabilidade: ligar o outro grupo é
acrescentar uma linha e reiniciar.

Linhas vazias e comentários (`#`) são ignorados. Qualquer outra linha inválida
interrompe a subida do roteador com o número da linha e o motivo.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

from roteador.enderecos import analisar_endereco, eh_endereco_de_roteador


class ConfigError(Exception):
    """Arquivo de configuração rejeitado. `linha` é 1-based, ou 0 se geral."""

    def __init__(self, mensagem: str, linha: int = 0) -> None:
        self.linha = linha
        if linha:
            texto = f"linha {linha}: {mensagem}"
        else:
            texto = mensagem
        super().__init__(texto)


@dataclass(frozen=True)
class VizinhoConfig:
    ip: str
    porta: int
    custo: int


@dataclass(frozen=True)
class Config:
    endereco: str
    porta: int
    vizinhos: tuple[VizinhoConfig, ...]


def ler_config(caminho: str) -> Config:
    """Lê o arquivo e devolve a configuração já com os nomes resolvidos."""
    try:
        with open(caminho, encoding="utf-8-sig") as arquivo:
            linhas = arquivo.readlines()
    except OSError as erro:
        raise ConfigError(f"nao foi possivel ler {caminho}: {erro}") from erro

    endereco: str | None = None
    porta = 6000
    porta_definida = False
    vizinhos: list[VizinhoConfig] = []
    vistos: set[tuple[str, int]] = set()

    for numero, bruta in enumerate(linhas, start=1):
        linha = bruta.strip()
        if linha == "" or linha.startswith("#"):
            continue
        partes = linha.split()
        chave = partes[0]
        if chave == "endereco" and len(partes) == 2:
            if endereco is not None:
                raise ConfigError("endereco repetido", numero)
            endereco = _endereco_do_roteador(partes[1], numero)
        elif chave == "porta" and len(partes) == 2:
            if porta_definida:
                raise ConfigError("porta repetida", numero)
            porta = _porta(partes[1], numero)
            porta_definida = True
        elif chave == "vizinho" and len(partes) == 4:
            ip = _resolver_ip(partes[1], numero)
            porta_vizinho = _porta(partes[2], numero)
            custo = _custo(partes[3], numero)
            chave_vizinho = (ip, porta_vizinho)
            if chave_vizinho in vistos:
                raise ConfigError(
                    f"vizinho repetido: {ip}:{porta_vizinho}", numero
                )
            vistos.add(chave_vizinho)
            vizinhos.append(VizinhoConfig(ip, porta_vizinho, custo))
        else:
            raise ConfigError(
                "linha invalida (esperado: endereco, porta ou vizinho)", numero
            )

    if endereco is None:
        raise ConfigError("falta a linha 'endereco 10.G.R.1'", max(len(linhas), 1))
    return Config(endereco, porta, tuple(vizinhos))


def _endereco_do_roteador(texto: str, linha: int) -> str:
    try:
        canonico = analisar_endereco(texto)
    except ValueError as erro:
        raise ConfigError(str(erro), linha) from erro
    if not eh_endereco_de_roteador(canonico):
        raise ConfigError(
            "endereco do roteador deve ser 10.G.R.1 com G e R entre 1 e 254",
            linha,
        )
    return canonico


def _porta(texto: str, linha: int) -> int:
    if not texto.isdigit():
        raise ConfigError(f"porta invalida: {texto!r}", linha)
    valor = int(texto)
    if not 1 <= valor <= 65535:
        raise ConfigError(f"porta fora de 1-65535: {valor}", linha)
    return valor


def _custo(texto: str, linha: int) -> int:
    # Zero, negativo e texto são erro: o Dijkstra do enunciado usa inteiros
    # positivos, e o desempate só é determinístico com esse contrato.
    if not texto.isdigit() or int(texto) < 1:
        raise ConfigError(f"custo deve ser inteiro positivo: {texto!r}", linha)
    return int(texto)


def _resolver_ip(texto: str, linha: int) -> str:
    """Converte nome de máquina em IPv4 uma vez, na subida.

    A comparação com o remetente do pacote usa o IP, não o nome. O endereço
    real muda com o DHCP: por isso ele fica só neste arquivo, fácil de editar.
    """
    try:
        ip = socket.gethostbyname(texto)
    except socket.gaierror as erro:
        raise ConfigError(f"nao resolveu o nome {texto!r}: {erro}", linha) from erro
    return ip
