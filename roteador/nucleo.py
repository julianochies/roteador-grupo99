"""Regras do protocolo, sem socket e sem relógio.

`receber`, `tick` e `comando` recebem o horário e devolvem uma `Saida`.
Quem envia, imprime e escreve o log é a casca (`udp.py`). Por isso um teste
percorre 90 s de envelhecimento sem esperar 90 s.

Ordem ao receber DADOS ou ICMP, igual à do enunciado (Encaminhamento):
1. destino na própria rede → entrega local, sem mexer no TTL;
2. senão decrementa o TTL e, se chegou a 0, ICMP 11;
3. senão, sem rota, ICMP 3;
4. senão encaminha com o TTL novo.

Nunca se gera 11 ou 3 em resposta a um 11 ou 3. Eco (8 e 0) gera erro
normalmente.
"""

from __future__ import annotations

import random
import time
from dataclasses import replace

from roteador.cli import (
    AJUDA,
    PedidoAjuda,
    PedidoDijkstra,
    PedidoEnlace,
    PedidoInvalido,
    PedidoLsdb,
    PedidoMsg,
    PedidoPerder,
    PedidoPing,
    PedidoTabela,
    PedidoVizinhos,
    formatar_lsdb,
    formatar_passos,
    formatar_tabela,
    formatar_vizinhos,
    interpretar,
    texto_resultado_icmp,
)
from roteador.config import Config
from roteador.dijkstra import dijkstra, dijkstra_passos
from roteador.enderecos import mesma_rede, rede_de
from roteador.eventos import Saida, evento
from roteador.lsdb import LSDB
from roteador.pacotes import (
    Dados,
    Hello,
    Icmp,
    Lsp,
    PacoteMalformado,
    nome_tipo,
    parse,
    serializar,
    texto_vizinhos,
)
from roteador.vizinhos import TabelaVizinhos, Vizinho

HELLO_INTERVALO = 5.0
VIZINHO_TIMEOUT = 20.0
LSP_INTERVALO = 30.0
LSP_VALIDADE = 90.0
PING_TIMEOUT = 2.0
TTL_PADRAO = 16


class RoteadorNucleo:
    def __init__(
        self,
        config: Config,
        seq_inicial: int,
        perda_lsp: float = 0.0,
        semente: int = 0,
        perder_proximo_lsp_de: set[str] | None = None,
    ) -> None:
        self.config = config
        self.endereco = config.endereco
        self.vizinhos = TabelaVizinhos(config)
        self.lsdb = LSDB()
        self.tabela: dict[str, tuple[str, int]] = {}
        # O primeiro LSP usa `seq_inicial` (Unix time na casca). Cada LSP
        # seguinte soma 1. Reenviar o LSP de outro roteador não mexe nisto.
        self._seq = seq_inicial
        self.proximo_hello = 0.0
        self.proxima_renovacao = 0.0
        self._ja_gerou = False
        self.pendentes: dict[int, tuple[str, float]] = {}
        self._proximo_id_ping = 1
        self._proximo_id_dados = 1
        self.perda_lsp = perda_lsp
        self._rng = random.Random(semente)
        self.perder_proxima = set(perder_proximo_lsp_de or ())

    def rota(self, destino: str) -> tuple[str, int] | None:
        """`(próximo salto, custo)` para o endereço, ou None."""
        return self.tabela.get(rede_de(destino))

    def receber(self, dados: bytes, remetente: tuple[str, int], now: float) -> Saida:
        """Processa um datagrama UDP. Remetente fora da configuração é descartado
        antes do parse, como pedem as regras gerais de comunicação.
        """
        saida = Saida()
        ip, porta = remetente[0], int(remetente[1])
        de = f"{ip}:{porta}"
        if not self.vizinhos.configurado(ip, porta):
            saida.eventos.append(evento("DESCARTADO", motivo="remetente-desconhecido", de=de))
            return saida
        vizinho = self.vizinhos.obter(ip, porta)
        if vizinho is not None and not vizinho.enlace_ligado:
            saida.eventos.append(evento("DESCARTADO", motivo="enlace-off", de=de))
            return saida
        try:
            pacote = parse(dados)
        except PacoteMalformado as erro:
            saida.eventos.append(
                evento("DESCARTADO", motivo="malformado", detalhe=erro.motivo, de=de)
            )
            return saida
        if isinstance(pacote, Hello):
            self._processar_hello(pacote, ip, porta, now, saida)
        elif isinstance(pacote, Lsp):
            self._processar_lsp(pacote, dados, ip, porta, now, saida)
        else:
            self._processar_transito(pacote, now, saida)
        return saida

    def tick(self, now: float) -> Saida:
        """Um passo do temporizador. A casca chama isto a cada 0,5 s."""
        saida = Saida()
        if now >= self.proximo_hello:
            self._enviar_hellos(saida)
            self.proximo_hello = now + HELLO_INTERVALO
        cairam = self.vizinhos.expirar(now, VIZINHO_TIMEOUT)
        for vizinho in cairam:
            self._log_inativo(vizinho, saida, "timeout")
        if cairam:
            # Vários vizinhos podem cair no mesmo tick. Um LSP já descreve
            # a lista nova; gerar um por vizinho só multiplicaria a inundação.
            self.gerar_lsp_proprio(now, "vizinho-saiu", saida)
        if now >= self.proxima_renovacao:
            motivo = "inicio" if not self._ja_gerou else "renovacao"
            self.gerar_lsp_proprio(now, motivo, saida)
        self._envelhecer(now, saida)
        self._expirar_pings(now, saida)
        return saida

    def comando(self, linha: str, now: float) -> Saida:
        saida = Saida()
        pedido = interpretar(linha)
        if isinstance(pedido, PedidoInvalido):
            if pedido.mensagem:
                saida.mensagens.append(pedido.mensagem)
            return saida
        if isinstance(pedido, PedidoTabela):
            saida.mensagens.append(formatar_tabela(self.tabela))
        elif isinstance(pedido, PedidoLsdb):
            saida.mensagens.append(formatar_lsdb(self.lsdb))
        elif isinstance(pedido, PedidoVizinhos):
            saida.mensagens.append(formatar_vizinhos(self.vizinhos))
        elif isinstance(pedido, PedidoDijkstra):
            passos = dijkstra_passos(self.lsdb.arestas(), self.endereco)
            saida.mensagens.append(formatar_passos(passos))
        elif isinstance(pedido, PedidoAjuda):
            saida.mensagens.append(AJUDA.rstrip("\n"))
        elif isinstance(pedido, PedidoMsg):
            self._enviar_msg(pedido.destino, pedido.texto, saida)
        elif isinstance(pedido, PedidoPing):
            self._enviar_ping(pedido.destino, pedido.ttl, now, saida)
        elif isinstance(pedido, PedidoEnlace):
            self._comando_enlace(pedido.ligado, pedido.virtual, now, saida)
        elif isinstance(pedido, PedidoPerder):
            self.perder_proxima.add(pedido.origem)
            saida.mensagens.append(
                f"proximo LSP de {pedido.origem} sera descartado"
            )
        return saida

    def gerar_lsp_proprio(self, now: float, motivo: str, saida: Saida | None = None) -> Saida:
        """Cria o próximo LSP deste roteador, guarda na LSDB e inunda.

        O número de sequência só anda aqui. A lista leva os vizinhos ativos
        com o custo do arquivo; sem nenhum, a lista é `.`.
        """
        if saida is None:
            saida = Saida()
        seq = self._seq
        self._seq += 1
        pares = tuple(
            sorted(
                (v.virtual, v.custo)
                for v in self.vizinhos.ativos()
                if v.virtual is not None
            )
        )
        lsp = Lsp(self.endereco, seq, pares)
        bruto = serializar(lsp)
        self.lsdb.definir(lsp, bruto, now, proprio=True)
        self._inundar(bruto, exceto=None, saida=saida)
        self._ja_gerou = True
        self.proxima_renovacao = now + LSP_INTERVALO
        saida.eventos.append(
            evento("LSP-GERADO", seq=seq, viz=texto_vizinhos(pares), motivo=motivo)
        )
        self._recalcular(saida)
        return saida

    def _processar_hello(self, hello: Hello, ip: str, porta: int, now: float, saida: Saida) -> None:
        def ao_mudar(tipo: str, virtual: str, vizinho: Vizinho) -> None:
            if tipo == "SAIU":
                self._log_inativo(vizinho, saida, "virtual-mudou", virtual=virtual)
                self.gerar_lsp_proprio(now, "vizinho-saiu", saida)
                return
            saida.eventos.append(
                evento("VIZINHO-ATIVO", viz=virtual, end=f"{vizinho.ip}:{vizinho.porta}")
            )
            self.gerar_lsp_proprio(now, "vizinho-entrou", saida)
            # Além do LSP novo, o vizinho que acabou de subir recebe a LSDB
            # inteira. Sem isso ele só conheceria o resto na renovação de 30 s.
            self._sincronizar(vizinho, saida, motivo="vizinho-entrou")

        self.vizinhos.registrar_hello(ip, porta, hello.endereco, now, ao_mudar)

    def _processar_lsp(
        self,
        lsp: Lsp,
        dados: bytes,
        ip: str,
        porta: int,
        now: float,
        saida: Saida,
    ) -> None:
        vizinho = self.vizinhos.obter(ip, porta)
        de = vizinho.virtual if vizinho and vizinho.virtual else f"{ip}:{porta}"
        if lsp.origem == self.endereco:
            saida.eventos.append(evento("LSP-PROPRIO", origem=lsp.origem, seq=lsp.seq, de=de))
            return
        if self._perdido(lsp, de, saida):
            return
        atual = self.lsdb.obter(lsp.origem)
        if atual is not None and atual.lsp.seq >= lsp.seq:
            saida.eventos.append(
                evento("LSP-DUPLICADO", origem=lsp.origem, seq=lsp.seq, de=de)
            )
            return
        # Salto maior que +1: ou perdemos uma renovação, ou o vizinho
        # reiniciou (o seq novo é o Unix time, bem à frente do antigo).
        # No caso direto, devolvemos a LSDB para ele não esperar 30 s.
        # Renovação normal é seq+1 e não dispara isso, então a contagem da
        # inundação (questão 2) continua batendo com a fórmula.
        salto = atual is not None and lsp.seq > atual.lsp.seq + 1
        self.lsdb.definir(lsp, bytes(dados), now, proprio=False)
        reenviado = self._inundar(bytes(dados), exceto=(ip, porta), saida=saida)
        self._recalcular(saida)
        saida.eventos.append(
            evento(
                "LSP-NOVO",
                origem=lsp.origem,
                seq=lsp.seq,
                de=de,
                reenviado=reenviado,
            )
        )
        direto = vizinho is not None and vizinho.virtual == lsp.origem
        if salto and direto:
            self._sincronizar(vizinho, saida, pular_origem=lsp.origem, motivo="salto-seq")

    def _processar_transito(self, pacote: Dados | Icmp, now: float, saida: Saida) -> None:
        if mesma_rede(pacote.destino, self.endereco):
            self._entregar_local(pacote, now, saida)
            return
        if pacote.ttl - 1 <= 0:
            self._ttl_esgotado(pacote, now, saida)
            return
        self._encaminhar(replace(pacote, ttl=pacote.ttl - 1), now, saida)

    def _entregar_local(self, pacote: Dados | Icmp, now: float, saida: Saida) -> None:
        if isinstance(pacote, Dados):
            saida.mensagens.append(
                f"mensagem de {pacote.origem} para {pacote.destino}: {pacote.mensagem}"
            )
            return
        if pacote.tipo == 8:
            # A origem da resposta é o endereço que foi pingado, não
            # necessariamente o .1 do roteador (10.7.1.50 responde como tal).
            resposta = Icmp(
                origem=pacote.destino,
                destino=pacote.origem,
                ttl=TTL_PADRAO,
                id=pacote.id,
                tipo=0,
            )
            self._emitir_icmp(resposta, now, saida)
            return
        if pacote.tipo in (0, 3, 11):
            self._mostrar_resposta(pacote, now, saida)

    def _ttl_esgotado(self, pacote: Dados | Icmp, now: float, saida: Saida) -> None:
        if _pode_gerar_erro(pacote):
            self._gerar_erro(11, pacote.origem, pacote.id, now, saida)
            return
        saida.eventos.append(
            evento("DESCARTADO", motivo="erro-sobre-erro", tipo=nome_tipo(pacote))
        )

    def _encaminhar(self, pacote: Dados | Icmp, now: float, saida: Saida) -> None:
        resolved = self._proximo_salto(pacote.destino)
        if resolved is None:
            if _pode_gerar_erro(pacote):
                self._gerar_erro(3, pacote.origem, pacote.id, now, saida)
            else:
                saida.eventos.append(
                    evento("DESCARTADO", motivo="erro-sobre-erro", tipo=nome_tipo(pacote))
                )
            return
        virtual, endpoint = resolved
        saida.envios.append((serializar(pacote), endpoint))
        saida.eventos.append(
            evento(
                "ENCAMINHADO",
                tipo=nome_tipo(pacote),
                origem=pacote.origem,
                destino=pacote.destino,
                prox=virtual,
                ttl=pacote.ttl,
            )
        )

    def _gerar_erro(self, tipo: int, destino: str, id_pacote: int, now: float, saida: Saida) -> None:
        aviso = Icmp(self.endereco, destino, TTL_PADRAO, id_pacote, tipo)
        self._emitir_icmp(aviso, now, saida)

    def _emitir_icmp(self, pacote: Icmp, now: float, saida: Saida) -> None:
        """Origina um ICMP (resposta de eco ou erro). Sem rota, só registra."""
        if self._enviar_originado(pacote, saida, now):
            saida.eventos.append(
                evento("ICMP-GERADO", tipo=pacote.tipo, para=pacote.destino, id=pacote.id)
            )
            return
        saida.eventos.append(
            evento(
                "DESCARTADO",
                motivo="erro-sem-rota",
                tipo=pacote.tipo,
                para=pacote.destino,
                id=pacote.id,
            )
        )

    def _enviar_msg(self, destino: str, texto: str, saida: Saida) -> None:
        if not self._tem_rota(destino):
            saida.mensagens.append(f"destino inalcancavel: {destino}")
            return
        pacote = Dados(self.endereco, destino, TTL_PADRAO, self._proximo_id_dados, texto)
        self._proximo_id_dados += 1
        if self._enviar_originado(pacote, saida=saida):
            if not mesma_rede(destino, self.endereco):
                saida.mensagens.append(f"msg enviada para {destino}")
            return
        saida.mensagens.append(f"destino inalcancavel: {destino}")

    def _enviar_ping(self, destino: str, ttl: int, now: float, saida: Saida) -> None:
        if not self._tem_rota(destino):
            saida.mensagens.append(f"destino inalcancavel: {destino}")
            return
        id_pacote = self._proximo_id_ping
        self._proximo_id_ping += 1
        self.pendentes[id_pacote] = (destino, now)
        saida.mensagens.append(f"ping {destino} id={id_pacote} ttl={ttl}")
        pedido = Icmp(self.endereco, destino, ttl, id_pacote, 8)
        if self._enviar_originado(pedido, saida, now):
            saida.eventos.append(
                evento("ICMP-GERADO", tipo=8, para=destino, id=id_pacote)
            )
            return
        self.pendentes.pop(id_pacote, None)
        saida.mensagens.append(f"destino inalcancavel: {destino}")

    def _enviar_originado(
        self, pacote: Dados | Icmp, saida: Saida, now: float | None = None
    ) -> bool:
        """Envia um pacote criado aqui. Entrega local se o destino é a nossa rede.

        `now` só entra na conta do RTT quando a entrega é local (ping para
        a própria rede).
        """
        if mesma_rede(pacote.destino, self.endereco):
            self._entregar_local(pacote, 0.0 if now is None else now, saida)
            return True
        resolved = self._proximo_salto(pacote.destino)
        if resolved is None:
            return False
        _virtual, endpoint = resolved
        saida.envios.append((serializar(pacote), endpoint))
        return True

    def _mostrar_resposta(self, pacote: Icmp, now: float, saida: Saida) -> None:
        pendente = self.pendentes.pop(pacote.id, None)
        rtt = None if pendente is None else (now - pendente[1]) * 1000
        saida.mensagens.append(
            texto_resultado_icmp(pacote.tipo, pacote.origem, pacote.id, rtt)
        )

    def _tem_rota(self, destino: str) -> bool:
        if mesma_rede(destino, self.endereco):
            return True
        return self._proximo_salto(destino) is not None

    def _proximo_salto(self, destino: str) -> tuple[str, tuple[str, int]] | None:
        rota = self.tabela.get(rede_de(destino))
        if rota is None:
            return None
        virtual, _custo = rota
        vizinho = self.vizinhos.por_virtual(virtual)
        if vizinho is None or not vizinho.ativo or not vizinho.enlace_ligado:
            return None
        return virtual, vizinho.endpoint

    def _enviar_hellos(self, saida: Saida) -> None:
        bruto = serializar(Hello(self.endereco))
        for vizinho in self.vizinhos.destinos_hello():
            saida.envios.append((bruto, vizinho.endpoint))

    def _inundar(
        self, bruto: bytes, exceto: tuple[str, int] | None, saida: Saida
    ) -> int:
        """Cópia idêntica para cada vizinho ativo, menos quem nos mandou."""
        enviados = 0
        for vizinho in self.vizinhos.ativos():
            if exceto is not None and vizinho.endpoint == exceto:
                continue
            saida.envios.append((bruto, vizinho.endpoint))
            enviados += 1
        return enviados

    def _sincronizar(
        self,
        vizinho: Vizinho,
        saida: Saida,
        pular_origem: str | None = None,
        motivo: str = "vizinho-entrou",
    ) -> None:
        entradas = 0
        for entrada in self.lsdb.todas():
            if pular_origem is not None and entrada.lsp.origem == pular_origem:
                continue
            saida.envios.append((entrada.bruto, vizinho.endpoint))
            entradas += 1
        para = vizinho.virtual or f"{vizinho.ip}:{vizinho.porta}"
        saida.eventos.append(
            evento("LSP-SYNC", para=para, entradas=entradas, motivo=motivo)
        )

    def _envelhecer(self, now: float, saida: Saida) -> None:
        removidas = self.lsdb.expirar(now, LSP_VALIDADE, self.endereco)
        for entrada in removidas:
            idade = now - entrada.recebido_em
            saida.eventos.append(
                evento("LSP-EXPIRADO", origem=entrada.lsp.origem, idade=f"{idade:.1f}s")
            )
        # Um recálculo para o lote inteiro de expirações deste tick.
        if removidas:
            self._recalcular(saida)

    def _expirar_pings(self, now: float, saida: Saida) -> None:
        vencidos = [
            id_pacote
            for id_pacote, (_destino, enviado) in self.pendentes.items()
            if now - enviado >= PING_TIMEOUT
        ]
        for id_pacote in vencidos:
            destino, _enviado = self.pendentes.pop(id_pacote)
            saida.mensagens.append(f"timeout id={id_pacote} destino={destino}")

    def _recalcular(self, saida: Saida) -> None:
        inicio = time.perf_counter()
        nova = dijkstra(self.lsdb.arestas(), self.endereco)
        gasto_ms = (time.perf_counter() - inicio) * 1000
        mudou = _diff_rotas(self.tabela, nova)
        self.tabela = nova
        saida.eventos.append(
            evento("ROTAS-RECALCULADAS", mudou=mudou, tempo=f"{gasto_ms:.1f}ms")
        )

    def _comando_enlace(self, ligado: bool, virtual: str, now: float, saida: Saida) -> None:
        if ligado:
            vizinho = self.vizinhos.ligar_enlace(virtual)
            if vizinho is None:
                saida.mensagens.append(f"vizinho desconhecido: {virtual}")
                return
            saida.mensagens.append(
                f"enlace com {virtual} ligado; aguardando HELLO"
            )
            return
        resultado = self.vizinhos.desligar_enlace(virtual)
        if resultado is None:
            saida.mensagens.append(f"vizinho desconhecido: {virtual}")
            return
        vizinho, estava_ativo = resultado
        saida.mensagens.append(f"enlace com {virtual} cortado")
        if estava_ativo:
            self._log_inativo(vizinho, saida, "enlace-off", virtual=virtual)
            self.gerar_lsp_proprio(now, "enlace-off", saida)

    def _log_inativo(
        self, vizinho: Vizinho, saida: Saida, motivo: str, virtual: str | None = None
    ) -> None:
        nome = virtual or vizinho.virtual or f"{vizinho.ip}:{vizinho.porta}"
        saida.eventos.append(
            evento(
                "VIZINHO-INATIVO",
                viz=nome,
                end=f"{vizinho.ip}:{vizinho.porta}",
                motivo=motivo,
            )
        )

    def _perdido(self, lsp: Lsp, de: str, saida: Saida) -> bool:
        if lsp.origem in self.perder_proxima:
            self.perder_proxima.discard(lsp.origem)
            saida.eventos.append(
                evento(
                    "DESCARTADO",
                    motivo="perda-simulada",
                    origem=lsp.origem,
                    seq=lsp.seq,
                    de=de,
                )
            )
            return True
        if self.perda_lsp > 0 and self._rng.random() < self.perda_lsp:
            saida.eventos.append(
                evento(
                    "DESCARTADO",
                    motivo="perda-simulada",
                    origem=lsp.origem,
                    seq=lsp.seq,
                    de=de,
                )
            )
            return True
        return False


def _pode_gerar_erro(pacote: Dados | Icmp) -> bool:
    """11 e 3 não geram outro erro. DADOS, eco e resposta de eco geram."""
    if isinstance(pacote, Dados):
        return True
    return pacote.tipo in (0, 8)


def _diff_rotas(
    antiga: dict[str, tuple[str, int]], nova: dict[str, tuple[str, int]]
) -> str:
    partes: list[str] = []
    for rede in sorted(set(antiga) | set(nova)):
        antes = antiga.get(rede)
        depois = nova.get(rede)
        if antes == depois:
            continue
        texto_antes = "*" if antes is None else f"{antes[0]}/{antes[1]}"
        texto_depois = "*" if depois is None else f"{depois[0]}/{depois[1]}"
        partes.append(f"{rede}:{texto_antes}->{texto_depois}")
    return ",".join(partes) if partes else "-"
