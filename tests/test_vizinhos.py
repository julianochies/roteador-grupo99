"""Vizinhança: HELLO, ativo/inativo e remetente desconhecido."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roteador.config import Config, VizinhoConfig
from roteador.nucleo import RoteadorNucleo
from roteador.pacotes import Hello, serializar
from roteador.simulacao import TOPOLOGIA_REFERENCIA, RedeSimulada


def _nucleo() -> RoteadorNucleo:
    config = Config(
        "10.7.1.1",
        6001,
        (
            VizinhoConfig("127.0.0.1", 6002, 1),
            VizinhoConfig("127.0.0.1", 6004, 5),
        ),
    )
    return RoteadorNucleo(config, seq_inicial=1_000)


def _tipos(saida, tipo: str):
    return [e for e in saida.eventos if e.tipo == tipo]


class TestVizinhos(unittest.TestCase):
    def test_v1_hello_a_cada_5s_para_todos_os_configurados(self):
        nucleo = _nucleo()
        primeiro = nucleo.tick(0)
        hellos = [destino for dados, destino in primeiro.envios if dados.startswith(b"HELLO:")]
        self.assertEqual(sorted(hellos), [("127.0.0.1", 6002), ("127.0.0.1", 6004)])
        self.assertEqual(
            [d for dados, d in nucleo.tick(4.9).envios if dados.startswith(b"HELLO:")],
            [],
        )
        de_novo = [d for dados, d in nucleo.tick(5).envios if dados.startswith(b"HELLO:")]
        self.assertEqual(len(de_novo), 2)

    def test_v2_primeiro_hello_ativa_e_gera_lsp(self):
        nucleo = _nucleo()
        saida = nucleo.receber(serializar(Hello("10.7.2.1")), ("127.0.0.1", 6002), 1)
        self.assertTrue(_tipos(saida, "VIZINHO-ATIVO"))
        self.assertEqual(_tipos(saida, "VIZINHO-ATIVO")[0].get("viz"), "10.7.2.1")
        gerados = _tipos(saida, "LSP-GERADO")
        self.assertTrue(gerados)
        self.assertIn(b"10.7.2.1=1", saida.envios[-1][0])
        vizinho = nucleo.vizinhos.obter("127.0.0.1", 6002)
        assert vizinho is not None
        self.assertTrue(vizinho.ativo)
        self.assertEqual(vizinho.virtual, "10.7.2.1")

    def test_v3_cai_aos_20s_e_nao_aos_19_5(self):
        nucleo = _nucleo()
        nucleo.tick(0)
        nucleo.receber(serializar(Hello("10.7.2.1")), ("127.0.0.1", 6002), 0)
        nucleo.tick(19.5)
        vizinho = nucleo.vizinhos.obter("127.0.0.1", 6002)
        assert vizinho is not None
        self.assertTrue(vizinho.ativo)
        saida = nucleo.tick(20)
        self.assertFalse(vizinho.ativo)
        self.assertTrue(_tipos(saida, "VIZINHO-INATIVO"))
        self.assertTrue(_tipos(saida, "LSP-GERADO"))

    def test_v4_hello_de_fora_nao_muda_nada(self):
        nucleo = _nucleo()
        saida = nucleo.receber(serializar(Hello("10.7.9.1")), ("10.9.9.9", 1), 0)
        self.assertEqual(_tipos(saida, "DESCARTADO")[0].get("motivo"), "remetente-desconhecido")
        self.assertEqual(nucleo.vizinhos.ativos(), [])
        self.assertEqual(saida.envios, [])

    def test_v5_vizinho_que_volta_recebe_a_lsdb(self):
        rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        rede.rodar(1)
        rede.derrubar(2)
        rede.rodar(21)
        self.assertFalse(rede[1].vizinhos.obter("127.0.0.1", 6002).ativo)
        rede.religar(2)
        rede.rodar(1)
        origens = set(rede[2].lsdb.origens())
        self.assertIn("10.7.1.1", origens)
        self.assertIn("10.7.5.1", origens)
        self.assertTrue(rede[1].vizinhos.obter("127.0.0.1", 6002).ativo)

    def test_hello_tambem_para_vizinho_inativo(self):
        # Já coberto por V1 no instante 0, quando ninguém é ativo.
        nucleo = _nucleo()
        destinos = {d for _dados, d in nucleo.tick(0).envios if _dados.startswith(b"HELLO:") }
        self.assertEqual(len(destinos), 2)
        self.assertEqual(nucleo.vizinhos.ativos(), [])


if __name__ == "__main__":
    unittest.main()
