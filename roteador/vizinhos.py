"""Tabela de vizinhos configurados e o estado ativo/inativo.

O arquivo diz onde o vizinho pode estar (IP real e porta). Quem ele é
(endereço virtual) só se descobre no HELLO, que também é a única prova de
que ele está de pé: o UDP não tem conexão (seção Vizinhança).
"""

from __future__ import annotations

from dataclasses import dataclass

from roteador.config import Config, VizinhoConfig


@dataclass
class Vizinho:
    ip: str
    porta: int
    custo: int
    virtual: str | None = None
    ultimo_hello: float | None = None
    ativo: bool = False
    # `enlace_ligado` é o comando de teste `enlace off`: para de mandar HELLO
    # e ignora o que vier desse par, sem matar o processo.
    enlace_ligado: bool = True

    @property
    def endpoint(self) -> tuple[str, int]:
        return (self.ip, self.porta)


class TabelaVizinhos:
    def __init__(self, config: Config) -> None:
        self._por_endpoint: dict[tuple[str, int], Vizinho] = {}
        self._por_virtual: dict[str, Vizinho] = {}
        for item in config.vizinhos:
            self._inserir(item)

    def _inserir(self, item: VizinhoConfig) -> None:
        self._por_endpoint[(item.ip, item.porta)] = Vizinho(
            ip=item.ip, porta=item.porta, custo=item.custo
        )

    def configurado(self, ip: str, porta: int) -> bool:
        return (ip, porta) in self._por_endpoint

    def obter(self, ip: str, porta: int) -> Vizinho | None:
        return self._por_endpoint.get((ip, porta))

    def por_virtual(self, virtual: str) -> Vizinho | None:
        return self._por_virtual.get(virtual)

    def todos(self) -> list[Vizinho]:
        return list(self._por_endpoint.values())

    def ativos(self) -> list[Vizinho]:
        """Vizinhos que entram no LSP: ativos, com virtual e enlace ligado."""
        return [v for v in self._por_endpoint.values() if v.ativo and v.virtual]

    def destinos_hello(self) -> list[Vizinho]:
        """HELLO sai para todo vizinho configurado, ativo ou não.

        O enlace desligado pelo comando de teste fica de fora: é o que simula
        o fio cortado sem derrubar o processo.
        """
        return [v for v in self._por_endpoint.values() if v.enlace_ligado]

    def registrar_hello(self, ip: str, porta: int, virtual: str, now: float, ao_mudar) -> None:
        """Aplica um HELLO e chama `ao_mudar(tipo, virtual_antigo_ou_novo, vizinho)`.

        O callback roda no meio da transição. Assim, uma troca de endereço
        virtual vira saída (LSP sem ele) e depois entrada (LSP com ele), com
        a tabela já no estado correspondente a cada passo.
        """
        vizinho = self._por_endpoint[(ip, porta)]
        if vizinho.ativo and vizinho.virtual != virtual:
            antigo = vizinho.virtual or ""
            self._desativar(vizinho)
            ao_mudar("SAIU", antigo, vizinho)
        if not vizinho.ativo:
            self._ativar(vizinho, virtual, now)
            ao_mudar("ENTROU", virtual, vizinho)
        else:
            vizinho.ultimo_hello = now

    def expirar(self, now: float, limite: float) -> list[Vizinho]:
        """Vizinhos ativos sem HELLO há `limite` segundos passam a inativos.

        O enunciado usa 20 s (quatro períodos de 5 s): tolera três HELLOs
        perdidos antes de declarar queda.
        """
        cairam: list[Vizinho] = []
        for vizinho in self._por_endpoint.values():
            if not vizinho.ativo or vizinho.ultimo_hello is None:
                continue
            if now - vizinho.ultimo_hello >= limite:
                self._desativar(vizinho)
                cairam.append(vizinho)
        return cairam

    def desligar_enlace(self, virtual: str) -> tuple[Vizinho, bool] | None:
        """Corta o enlace. Devolve o vizinho e se ele estava ativo."""
        vizinho = self._por_virtual.get(virtual)
        if vizinho is None:
            return None
        estava_ativo = vizinho.ativo
        vizinho.enlace_ligado = False
        if estava_ativo:
            self._desativar(vizinho)
        return vizinho, estava_ativo

    def ligar_enlace(self, virtual: str) -> Vizinho | None:
        vizinho = self._por_virtual.get(virtual)
        if vizinho is None:
            return None
        vizinho.enlace_ligado = True
        return vizinho

    def _ativar(self, vizinho: Vizinho, virtual: str, now: float) -> None:
        if (
            vizinho.virtual
            and vizinho.virtual != virtual
            and self._por_virtual.get(vizinho.virtual) is vizinho
        ):
            del self._por_virtual[vizinho.virtual]
        vizinho.virtual = virtual
        vizinho.ativo = True
        vizinho.ultimo_hello = now
        self._por_virtual[virtual] = vizinho

    def _desativar(self, vizinho: Vizinho) -> None:
        # O virtual fica guardado para o log e para o comando `enlace`.
        vizinho.ativo = False
