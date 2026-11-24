"""Leitura e escrita dos quatro pacotes do enunciado.

Formato (seção Formato dos pacotes): texto ASCII, campos separados por `:`,
sem quebra de linha no envio. Na recepção tolera-se um único `\\r\\n` (ou
`\\n`) final, para conversar com um grupo que termine a string assim.

A mensagem de DADOS não pode conter `:` nem caractere fora do ASCII: os dois
casos caem naturalmente em pacote malformado (campo a mais, ou erro de
decodificação).
"""

from __future__ import annotations

from dataclasses import dataclass

from roteador.enderecos import EnderecoInvalido, analisar_endereco

# Número exato de campos depois do split por ":".
_CAMPOS = {"HELLO": 2, "LSP": 4, "DADOS": 6, "ICMP": 6}
_TIPOS_ICMP = {0, 3, 8, 11}


class PacoteMalformado(Exception):
    """Tipo desconhecido, campo a mais ou a menos, ou valor inválido.

    A casca captura esta exceção, registra o descarte e segue. Um pacote
    ruim não derruba o roteador (Regras gerais de comunicação).
    """

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


@dataclass(frozen=True)
class Hello:
    endereco: str


@dataclass(frozen=True)
class Lsp:
    origem: str
    seq: int
    vizinhos: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Dados:
    origem: str
    destino: str
    ttl: int
    id: int
    mensagem: str


@dataclass(frozen=True)
class Icmp:
    origem: str
    destino: str
    ttl: int
    id: int
    tipo: int


Pacote = Hello | Lsp | Dados | Icmp


def texto_vizinhos(vizinhos: tuple[tuple[str, int], ...]) -> str:
    """Lista do LSP. Vazia vira exatamente `.`, como no enunciado."""
    if not vizinhos:
        return "."
    return ";".join(f"{virtual}={custo}" for virtual, custo in vizinhos)


def serializar(pacote: Pacote) -> bytes:
    """O inverso do parse, sem `\\n` no final."""
    if isinstance(pacote, Hello):
        texto = f"HELLO:{pacote.endereco}"
    elif isinstance(pacote, Lsp):
        texto = f"LSP:{pacote.origem}:{pacote.seq}:{texto_vizinhos(pacote.vizinhos)}"
    elif isinstance(pacote, Dados):
        texto = (
            f"DADOS:{pacote.origem}:{pacote.destino}:"
            f"{pacote.ttl}:{pacote.id}:{pacote.mensagem}"
        )
    elif isinstance(pacote, Icmp):
        texto = (
            f"ICMP:{pacote.origem}:{pacote.destino}:"
            f"{pacote.ttl}:{pacote.id}:{pacote.tipo}"
        )
    else:
        raise TypeError(f"pacote desconhecido: {type(pacote)!r}")
    return texto.encode("ascii")


def nome_tipo(pacote: Pacote) -> str:
    """Rótulo curto para o log de encaminhamento (`DADOS`, `ICMP8`)."""
    if isinstance(pacote, Dados):
        return "DADOS"
    if isinstance(pacote, Icmp):
        return f"ICMP{pacote.tipo}"
    if isinstance(pacote, Hello):
        return "HELLO"
    return "LSP"


def parse(dados: bytes) -> Pacote:
    """Converte bytes recebidos em um pacote, ou levanta `PacoteMalformado`."""
    try:
        texto = dados.decode("ascii")
    except UnicodeDecodeError as erro:
        raise PacoteMalformado("nao e ASCII") from erro
    texto = _sem_quebra_final(texto)
    if texto == "":
        raise PacoteMalformado("pacote vazio")
    campos = texto.split(":")
    tipo = campos[0]
    esperado = _CAMPOS.get(tipo)
    if esperado is None:
        raise PacoteMalformado(f"tipo desconhecido: {tipo!r}")
    if len(campos) != esperado:
        raise PacoteMalformado(
            f"{tipo} precisa de {esperado} campos e veio com {len(campos)}"
        )
    if tipo == "HELLO":
        return Hello(_endereco(campos[1]))
    if tipo == "LSP":
        return Lsp(_endereco(campos[1]), _inteiro(campos[2], "seq"), _lista_lsp(campos[3]))
    if tipo == "DADOS":
        return Dados(
            _endereco(campos[1]),
            _endereco(campos[2]),
            _ttl(campos[3]),
            _inteiro(campos[4], "id"),
            _mensagem(campos[5]),
        )
    return Icmp(
        _endereco(campos[1]),
        _endereco(campos[2]),
        _ttl(campos[3]),
        _inteiro(campos[4], "id"),
        _tipo_icmp(campos[5]),
    )


def _sem_quebra_final(texto: str) -> str:
    """Remove uma única quebra de linha final (`\\r\\n`, `\\n` ou `\\r`)."""
    if texto.endswith("\r\n"):
        return texto[:-2]
    if texto.endswith("\n") or texto.endswith("\r"):
        return texto[:-1]
    return texto


def _endereco(campo: str) -> str:
    try:
        return analisar_endereco(campo)
    except EnderecoInvalido as erro:
        raise PacoteMalformado(str(erro)) from erro


def _inteiro(campo: str, nome: str) -> int:
    """Inteiro decimal não negativo, sem sinal e sem ponto."""
    if not campo.isdigit():
        raise PacoteMalformado(f"{nome} nao e inteiro: {campo!r}")
    return int(campo)


def _ttl(campo: str) -> int:
    valor = _inteiro(campo, "ttl")
    if valor > 255:
        raise PacoteMalformado(f"ttl fora de 0-255: {valor}")
    return valor


def _tipo_icmp(campo: str) -> int:
    valor = _inteiro(campo, "tipo")
    if valor not in _TIPOS_ICMP:
        raise PacoteMalformado(f"tipo ICMP desconhecido: {valor}")
    return valor


def _mensagem(campo: str) -> str:
    # O split por ":" já rejeita ":" dentro da mensagem (campo a mais).
    # Aqui só falta recusar quebra de linha que tenha sobrado no meio.
    if "\n" in campo or "\r" in campo:
        raise PacoteMalformado("mensagem contem quebra de linha")
    return campo


def _lista_lsp(campo: str) -> tuple[tuple[str, int], ...]:
    """`.` é a lista vazia. Caso contrário, `vizinho=custo` separado por `;`."""
    if campo == ".":
        return ()
    if campo == "":
        raise PacoteMalformado("lista de vizinhos vazia deve ser '.'")
    vistos: set[str] = set()
    lista: list[tuple[str, int]] = []
    for item in campo.split(";"):
        virtual, separador, custo_txt = item.partition("=")
        if separador != "=" or virtual == "" or custo_txt == "":
            raise PacoteMalformado(f"item de LSP invalido: {item!r}")
        endereco = _endereco(virtual)
        if not custo_txt.isdigit() or int(custo_txt) < 1:
            raise PacoteMalformado(f"custo de LSP invalido: {custo_txt!r}")
        if endereco in vistos:
            raise PacoteMalformado(f"vizinho repetido no LSP: {endereco}")
        vistos.add(endereco)
        lista.append((endereco, int(custo_txt)))
    return tuple(lista)
