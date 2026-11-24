"""Socket UDP, threads e o laço do terminal.

Três atividades compartilham o núcleo por um único lock: a recepção
(bloqueada em recvfrom), o temporizador (acorda a cada 0,5 s de tempo
virtual) e o terminal. Há um socket só, ligado na porta configurada, e é
por ele que tudo sai — a porta de origem é a porta do roteador, e o vizinho
reconhece quem enviou.
"""

from __future__ import annotations

import socket
import threading

from roteador.eventos import Saida
from roteador.log import Log, agora_parede
from roteador.nucleo import RoteadorNucleo
from roteador.relogio import RelogioReal

# O núcleo conta o tempo em segundos virtuais. O tick de 0,5 s virtual vira
# `0,5 * escala` segundos de parede. Com escala 0,1, tudo anda 10× mais rápido.
TICK_VIRTUAL = 0.5


class RoteadorUDP:
    def __init__(self, nucleo: RoteadorNucleo, relogio: RelogioReal, log: Log) -> None:
        self.nucleo = nucleo
        self.relogio = relogio
        self.log = log
        self._lock = threading.Lock()
        self._io = threading.Lock()
        self._parar = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", nucleo.config.porta))

    def servir(self) -> None:
        """Sobe recepção e temporizador e lê o terminal nesta thread."""
        recepcao = threading.Thread(target=self._loop_recepcao, name="recepcao", daemon=True)
        temporizador = threading.Thread(target=self._loop_tempo, name="tempo", daemon=True)
        recepcao.start()
        temporizador.start()
        self._anunciar(
            f"roteador {self.nucleo.endereco} escutando UDP {self.nucleo.config.porta}"
        )
        self._anunciar("digite ajuda para a lista de comandos")
        try:
            self._loop_terminal()
        except KeyboardInterrupt:
            self._anunciar("encerrando")
        finally:
            self.encerrar()

    def encerrar(self) -> None:
        self._parar.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self.log.fechar()

    def _loop_terminal(self) -> None:
        while not self._parar.is_set():
            try:
                linha = input("> ")
            except EOFError:
                break
            except KeyboardInterrupt:
                raise
            texto = linha.strip()
            if texto.lower() == "sair":
                self._anunciar("encerrando")
                break
            if texto.lower() == "silencio":
                self.log.silencio = not self.log.silencio
                estado = "ligado" if self.log.silencio else "desligado"
                self._anunciar(f"silencio {estado}")
                continue
            self._chamar(lambda linha=texto: self.nucleo.comando(linha, self.relogio.agora()))

    def _loop_tempo(self) -> None:
        while not self._parar.is_set():
            self._chamar(lambda: self.nucleo.tick(self.relogio.agora()))
            if self._parar.wait(TICK_VIRTUAL * self.relogio.escala):
                return

    def _loop_recepcao(self) -> None:
        while not self._parar.is_set():
            try:
                dados, endereco = self.sock.recvfrom(65535)
            except ConnectionResetError:
                # Windows entrega ICMP "porta inalcançável" como erro 10054
                # no recvfrom. O vizinho caiu; o laço tem que continuar.
                continue
            except OSError:
                if self._parar.is_set():
                    return
                continue
            try:
                self._chamar(
                    lambda dados=dados, endereco=endereco: self.nucleo.receber(
                        dados, (endereco[0], endereco[1]), self.relogio.agora()
                    )
                )
            except Exception as erro:  # noqa: BLE001 — um pacote não derruba o roteador
                self._registrar_erro(endereco, erro)

    def _chamar(self, funcao) -> None:
        with self._lock:
            saida = funcao()
        self._aplicar(saida)

    def _aplicar(self, saida: Saida) -> None:
        for dados, destino in saida.envios:
            self._enviar(dados, destino)
        for item in saida.eventos:
            linha = self.log.registrar(item, agora_parede())
            if not self.log.silencio:
                self._anunciar(linha)
        for mensagem in saida.mensagens:
            self._anunciar(mensagem)

    def _enviar(self, dados: bytes, destino: tuple[str, int]) -> None:
        try:
            self.sock.sendto(dados, destino)
        except ConnectionResetError:
            return
        except OSError:
            if not self._parar.is_set():
                self._anunciar(f"falha ao enviar para {destino[0]}:{destino[1]}")

    def _registrar_erro(self, endereco: tuple, erro: Exception) -> None:
        from roteador.eventos import evento

        item = evento(
            "DESCARTADO",
            motivo="erro-interno",
            detalhe=type(erro).__name__,
            de=f"{endereco[0]}:{endereco[1]}",
        )
        linha = self.log.registrar(item, agora_parede())
        if not self.log.silencio:
            self._anunciar(linha)

    def _anunciar(self, texto: str) -> None:
        with self._io:
            print(texto, flush=True)

