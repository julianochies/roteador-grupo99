"""Comandos do terminal e a formatação da tabela, da LSDB e dos vizinhos.

A interpretação é pura: devolve um objeto descrevendo o pedido, ou o erro
para mostrar ao usuário. Quem aplica o efeito é o núcleo.
"""

from __future__ import annotations

from dataclasses import dataclass

from roteador.dijkstra import Passo
from roteador.enderecos import EnderecoInvalido, analisar_endereco, rede_cidr
from roteador.lsdb import LSDB
from roteador.pacotes import texto_vizinhos
from roteador.vizinhos import TabelaVizinhos


@dataclass(frozen=True)
class PedidoTabela:
    pass


@dataclass(frozen=True)
class PedidoLsdb:
    pass


@dataclass(frozen=True)
class PedidoVizinhos:
    pass


@dataclass(frozen=True)
class PedidoDijkstra:
    pass


@dataclass(frozen=True)
class PedidoAjuda:
    pass


@dataclass(frozen=True)
class PedidoMsg:
    destino: str
    texto: str


@dataclass(frozen=True)
class PedidoPing:
    destino: str
    ttl: int


@dataclass(frozen=True)
class PedidoEnlace:
    ligado: bool
    virtual: str


@dataclass(frozen=True)
class PedidoPerder:
    origem: str


@dataclass(frozen=True)
class PedidoInvalido:
    mensagem: str


Pedido = (
    PedidoTabela
    | PedidoLsdb
    | PedidoVizinhos
    | PedidoDijkstra
    | PedidoAjuda
    | PedidoMsg
    | PedidoPing
    | PedidoEnlace
    | PedidoPerder
    | PedidoInvalido
)


AJUDA = """\
comandos:
  tabela                         rede, proximo salto e custo
  lsdb                           LSP mais recente de cada roteador
  vizinhos                       vizinhos configurados e o estado
  dijkstra                       tabela de iteracoes a partir da LSDB atual
  msg <destino> <texto>          envia um datagrama de texto
  ping <destino> [ttl]           pedido de eco (ttl padrao 16)
  enlace off|on <virtual>       corta ou religa um enlace (teste)
  perder <origem>               descarta o proximo LSP dessa origem (teste)
  silencio                       logs so no arquivo
  sair                           encerra o roteador
"""


def interpretar(linha: str) -> Pedido:
    """Traduz uma linha do terminal. Não mexe em estado."""
    texto = linha.strip()
    if texto == "":
        return PedidoInvalido("")
    partes = texto.split()
    comando = partes[0].lower()
    if comando == "tabela" and len(partes) == 1:
        return PedidoTabela()
    if comando == "lsdb" and len(partes) == 1:
        return PedidoLsdb()
    if comando == "vizinhos" and len(partes) == 1:
        return PedidoVizinhos()
    if comando == "dijkstra" and len(partes) == 1:
        return PedidoDijkstra()
    if comando == "ajuda" and len(partes) == 1:
        return PedidoAjuda()
    if comando == "msg":
        return _msg(partes, texto)
    if comando == "ping":
        return _ping(partes)
    if comando == "enlace":
        return _enlace(partes)
    if comando == "perder":
        return _perder(partes)
    return PedidoInvalido(f"comando desconhecido: {comando}. Digite ajuda.")


def formatar_tabela(tabela: dict[str, tuple[str, int]]) -> str:
    linhas = [f"{'Rede':<18}{'Proximo salto':<18}Custo"]
    if not tabela:
        linhas.append("(vazia)")
        return "\n".join(linhas)
    for rede in sorted(tabela):
        salto, custo = tabela[rede]
        linhas.append(f"{rede_cidr(rede):<18}{salto:<18}{custo}")
    return "\n".join(linhas)


def formatar_lsdb(lsdb: LSDB) -> str:
    linhas = [f"{'Origem':<16}{'Seq':<16}Vizinhos"]
    origens = lsdb.origens()
    if not origens:
        linhas.append("(vazia)")
        return "\n".join(linhas)
    for origem in origens:
        entrada = lsdb.obter(origem)
        assert entrada is not None
        linhas.append(
            f"{origem:<16}{entrada.lsp.seq:<16}{texto_vizinhos(entrada.lsp.vizinhos)}"
        )
    return "\n".join(linhas)


def formatar_vizinhos(tabela: TabelaVizinhos) -> str:
    """Lista todos os configurados. O enunciado pede os ativos; a coluna
    Estado separa os que já caíram, para a demonstração da queda.
    """
    linhas = [f"{'Virtual':<16}{'IP':<16}{'Porta':<8}{'Custo':<8}Estado"]
    vizinhos = sorted(tabela.todos(), key=lambda v: (v.virtual or "", v.ip, v.porta))
    if not vizinhos:
        linhas.append("(nenhum vizinho configurado)")
        return "\n".join(linhas)
    for vizinho in vizinhos:
        virtual = vizinho.virtual or "-"
        if not vizinho.enlace_ligado:
            estado = "cortado"
        elif vizinho.ativo:
            estado = "ativo"
        else:
            estado = "inativo"
        linhas.append(
            f"{virtual:<16}{vizinho.ip:<16}{vizinho.porta:<8}{vizinho.custo:<8}{estado}"
        )
    return "\n".join(linhas)


def formatar_passos(passos: list[Passo]) -> str:
    if not passos:
        return "(LSDB sem o proprio roteador)"
    blocos: list[str] = []
    for indice, passo in enumerate(passos, start=1):
        linhas = [
            f"Passo {indice}: fecha {passo.adicionou}",
            "  N' = {" + ", ".join(passo.confirmados) + "}",
        ]
        dist = dict(passo.distancias)
        pred = dict(passo.predecessores)
        salto = dict(passo.primeiros_saltos)
        for no in sorted(dist):
            if dist[no] == 0 and no not in pred:
                linhas.append(f"  D({no})=0")
                continue
            texto_pred = pred.get(no, "-")
            texto_salto = salto.get(no, "-")
            linhas.append(
                f"  D({no})={dist[no]}  p={texto_pred}  salto={texto_salto}"
            )
        blocos.append("\n".join(linhas))
    return "\n".join(blocos)


def texto_resultado_icmp(tipo: int, origem: str, id_pacote: int, rtt_ms: float | None) -> str:
    nome = {0: "eco", 3: "destino inalcancavel", 11: "tempo excedido"}.get(
        tipo, f"icmp {tipo}"
    )
    if rtt_ms is None:
        return f"{nome} de {origem} id={id_pacote}"
    return f"{nome} de {origem} id={id_pacote} rtt={rtt_ms:.1f}ms"


def _msg(partes: list[str], linha: str) -> Pedido:
    if len(partes) < 3:
        return PedidoInvalido("uso: msg <destino> <texto>")
    destino, erro = _destino(partes[1])
    if erro:
        return PedidoInvalido(erro)
    # O texto é o resto da linha, para preservar os espaços internos.
    depois_do_destino = linha.split(None, 2)[2]
    if not depois_do_destino.isascii():
        return PedidoInvalido("mensagem deve ser ASCII, sem acentos")
    if ":" in depois_do_destino:
        return PedidoInvalido("mensagem nao pode conter ':'")
    if "\n" in depois_do_destino or "\r" in depois_do_destino:
        return PedidoInvalido("mensagem nao pode conter quebra de linha")
    return PedidoMsg(destino, depois_do_destino)


def _ping(partes: list[str]) -> Pedido:
    if len(partes) not in (2, 3):
        return PedidoInvalido("uso: ping <destino> [ttl]")
    destino, erro = _destino(partes[1])
    if erro:
        return PedidoInvalido(erro)
    ttl = 16
    if len(partes) == 3:
        valor = partes[2].lstrip("0")
        if not valor.isascii() or not valor.isdigit() or len(valor) > 3:
            return PedidoInvalido("ttl deve ser inteiro entre 1 e 255")
        ttl = int(valor)
        if not 1 <= ttl <= 255:
            return PedidoInvalido("ttl deve ser inteiro entre 1 e 255")
    return PedidoPing(destino, ttl)


def _enlace(partes: list[str]) -> Pedido:
    if len(partes) != 3 or partes[1].lower() not in ("on", "off"):
        return PedidoInvalido("uso: enlace off|on <endereco virtual>")
    destino, erro = _destino(partes[2])
    if erro:
        return PedidoInvalido(erro)
    return PedidoEnlace(ligado=partes[1].lower() == "on", virtual=destino)


def _perder(partes: list[str]) -> Pedido:
    if len(partes) != 2:
        return PedidoInvalido("uso: perder <origem>")
    origem, erro = _destino(partes[1])
    if erro:
        return PedidoInvalido(erro)
    return PedidoPerder(origem)


def _destino(texto: str) -> tuple[str, str]:
    try:
        return analisar_endereco(texto), ""
    except EnderecoInvalido as erro:
        return "", f"destino invalido: {erro}"
