"""Endereços virtuais 10.G.R.x e a rede 10.G.R.0/24 de cada roteador.

O enunciado (Endereçamento virtual) fixa o roteador R do grupo G em 10.G.R.1.
Qualquer datagrama para 10.G.R.x é entregue a esse roteador: os três primeiros
octetos identificam a rede, o quarto distingue o endereço "pingado".
"""

from __future__ import annotations


class EnderecoInvalido(ValueError):
    """O texto não é um endereço virtual no formato exigido."""


def analisar_endereco(texto: str) -> str:
    """Devolve o endereço na forma canônica (sem zeros à esquerda).

    Aceita quatro octetos decimais, o primeiro igual a 10 e cada um entre
    0 e 255. `10.1.2` e `11.0.0.1` são rejeitados.
    """
    partes = texto.split(".")
    if len(partes) != 4:
        raise EnderecoInvalido(f"endereco virtual precisa de 4 octetos: {texto!r}")
    numeros: list[int] = []
    for parte in partes:
        if not parte.isascii() or not parte.isdigit():
            raise EnderecoInvalido(f"octeto invalido em {texto!r}")
        digitos = parte.lstrip("0") or "0"
        if len(digitos) > 3 or int(digitos) > 255:
            raise EnderecoInvalido(f"octeto fora de 0-255 em {texto!r}")
        numeros.append(int(digitos))
    if numeros[0] != 10:
        raise EnderecoInvalido(f"endereco virtual deve comecar com 10: {texto!r}")
    return ".".join(str(n) for n in numeros)


def eh_endereco_de_roteador(endereco: str) -> bool:
    """Verdadeiro se o endereço é 10.G.R.1 com G e R entre 1 e 254.

    É a forma exigida no arquivo de configuração. Pacotes em trânsito podem
    usar outro último octeto (por exemplo 10.7.1.50), então esta função não
    serve para validar origem e destino de DADOS ou ICMP.
    """
    try:
        canonico = analisar_endereco(endereco)
    except EnderecoInvalido:
        return False
    _dez, grupo, roteador, host = (int(p) for p in canonico.split("."))
    return 1 <= grupo <= 254 and 1 <= roteador <= 254 and host == 1


def rede_de(endereco: str) -> str:
    """Prefixo de três octetos que identifica a rede /24.

    `rede_de("10.7.1.50")` é `"10.7.1"`. A tabela de roteamento usa esse
    prefixo como chave; na tela ele aparece como `10.7.1.0/24`.
    """
    a, b, c, _host = analisar_endereco(endereco).split(".")
    return f"{a}.{b}.{c}"


def rede_cidr(prefixo: str) -> str:
    """`10.7.1` vira `10.7.1.0/24`, como o enunciado mostra a tabela."""
    return f"{prefixo}.0/24"


def mesma_rede(a: str, b: str) -> bool:
    """Os dois endereços pertencem à mesma rede 10.G.R.0/24."""
    return rede_de(a) == rede_de(b)
