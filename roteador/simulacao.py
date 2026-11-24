"""Rede de núcleos no mesmo processo, sem socket e sem espera real.

Os testes avançam o relógio, entregam o que cada núcleo mandaria e podem
derrubar um roteador ou cortar um enlace. O protocolo é o mesmo que roda
sobre UDP; só o transporte é trocado.
"""

from __future__ import annotations

import random

from roteador.eventos import Evento, Saida
from roteador.nucleo import RoteadorNucleo
from roteador.topologia import configs_da_topologia

TOPOLOGIA_REFERENCIA = "1-2:1,2-3:2,1-4:5,3-4:1,3-5:3,4-5:1"


class RedeSimulada:
    def __init__(self, nucleos: dict[int, RoteadorNucleo], seq_base: int = 1_000_000) -> None:
        self.nucleos = nucleos
        self.seq_base = seq_base
        self.agora = 0.0
        self.ativos = {numero: True for numero in nucleos}
        self.historico: dict[int, list[Evento]] = {numero: [] for numero in nucleos}
        self.mensagens: dict[int, list[str]] = {numero: [] for numero in nucleos}
        self.cortados: set[frozenset[int]] = set()
        self._fila: list[tuple[int, bytes, tuple[str, int]]] = []
        self._perda = 0.0
        self._rng = random.Random(1)
        self._geracao = {numero: 0 for numero in nucleos}
        self._iniciado = False

    @classmethod
    def da_topologia(
        cls,
        spec: str = TOPOLOGIA_REFERENCIA,
        grupo: int = 7,
        porta_base: int = 6001,
        seq_base: int = 1_000_000,
    ) -> RedeSimulada:
        configs = configs_da_topologia(spec, grupo=grupo, porta_base=porta_base)
        nucleos = {
            numero: RoteadorNucleo(config, seq_inicial=seq_base + numero)
            for numero, config in configs.items()
        }
        rede = cls(nucleos, seq_base=seq_base)
        rede._configs = configs
        rede._grupo = grupo
        rede._porta_base = porta_base
        return rede

    def __getitem__(self, numero: int) -> RoteadorNucleo:
        return self.nucleos[numero]

    def rodar(self, segundos: float, passo: float = 0.5) -> None:
        """Avança o tempo virtual e processa ticks e entregas.

        O primeiro `rodar` também executa o instante atual, para os HELLOs
        iniciais saírem sem precisar avançar 5 s.
        """
        if not self._iniciado:
            self._ciclo()
            self._iniciado = True
        alvo = self.agora + segundos
        while self.agora + 1e-9 < alvo:
            self.agora = round(self.agora + passo, 10)
            if self.agora > alvo + 1e-9:
                break
            self._ciclo()

    def comando(self, numero: int, linha: str) -> Saida:
        saida = self.nucleos[numero].comando(linha, self.agora)
        self._registrar(numero, saida)
        self._entregar()
        return saida

    def derrubar(self, numero: int) -> None:
        """O roteador para de enviar e de receber. Os outros percebem em 20 s."""
        self.ativos[numero] = False

    def religar(self, numero: int) -> None:
        """Sobe de novo, com número de sequência à frente do anterior.

        É o reinício do processo: estado zerado, mesmo arquivo de configuração.
        """
        self._geracao[numero] += 1
        seq = self.seq_base + self._geracao[numero] * 100_000 + numero
        config = self.nucleos[numero].config
        self.nucleos[numero] = RoteadorNucleo(config, seq_inicial=seq)
        self.ativos[numero] = True

    def cortar_enlace(self, a: int, b: int) -> None:
        self.cortados.add(frozenset({a, b}))

    def religar_enlace(self, a: int, b: int) -> None:
        self.cortados.discard(frozenset({a, b}))

    def perda(self, probabilidade: float, semente: int = 1) -> None:
        self._perda = probabilidade
        self._rng = random.Random(semente)

    def forcar_lsp(self, numero: int, motivo: str = "teste") -> None:
        """Gera um LSP novo neste roteador e deixa a inundação terminar."""
        saida = self.nucleos[numero].gerar_lsp_proprio(self.agora, motivo)
        self._registrar(numero, saida)
        self._entregar()

    def eventos(self, numero: int, nome: str, **campos: object) -> bool:
        return any(e.tipo == nome and e.tem(**campos) for e in self.historico[numero])

    def contar(self, tipo: str, numero: int | None = None) -> int:
        if numero is None:
            return sum(self.contar(tipo, n) for n in self.nucleos)
        return sum(1 for e in self.historico[numero] if e.tipo == tipo)

    def limpar_eventos(self) -> None:
        for numero in self.historico:
            self.historico[numero].clear()
            self.mensagens[numero].clear()

    def _ciclo(self) -> None:
        for numero in sorted(self.nucleos):
            if not self.ativos[numero]:
                continue
            saida = self.nucleos[numero].tick(self.agora)
            self._registrar(numero, saida)
        self._entregar()

    def _registrar(self, numero: int, saida: Saida) -> None:
        self.historico[numero].extend(saida.eventos)
        self.mensagens[numero].extend(saida.mensagens)
        if not self.ativos[numero]:
            return
        for dados, destino in saida.envios:
            self._fila.append((numero, dados, destino))

    def _entregar(self) -> None:
        voltas = 0
        while self._fila:
            voltas += 1
            if voltas > 100_000:
                raise RuntimeError("inundacao nao terminou (fila estourou)")
            origem, dados, destino = self._fila.pop(0)
            destino_n = self._numero_em(destino)
            if destino_n is None or not self.ativos[destino_n] or not self.ativos[origem]:
                continue
            if frozenset({origem, destino_n}) in self.cortados:
                continue
            if self._perda > 0 and self._rng.random() < self._perda:
                continue
            remetente = self._endpoint(origem)
            saida = self.nucleos[destino_n].receber(dados, remetente, self.agora)
            self._registrar(destino_n, saida)

    def _endpoint(self, numero: int) -> tuple[str, int]:
        config = self.nucleos[numero].config
        vizinho = config.vizinhos[0]
        return (vizinho.ip, config.porta)

    def _numero_em(self, destino: tuple[str, int]) -> int | None:
        ip, porta = destino
        for numero, nucleo in self.nucleos.items():
            if nucleo.config.porta == porta and _ip_do(nucleo) == ip:
                return numero
        return None


def _ip_do(nucleo: RoteadorNucleo) -> str:
    if nucleo.config.vizinhos:
        return nucleo.config.vizinhos[0].ip
    return "127.0.0.1"
