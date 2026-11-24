"""Cenários de ponta a ponta: queda, dois grupos, comandos."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roteador.config import Config, VizinhoConfig
from roteador.nucleo import RoteadorNucleo
from roteador.simulacao import TOPOLOGIA_REFERENCIA, RedeSimulada


class TestCenarios(unittest.TestCase):
    def test_reconvergencia_apos_queda_de_r2(self):
        rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        rede.rodar(segundos=10)
        self.assertEqual(rede[1].rota("10.7.3.1"), ("10.7.2.1", 3))
        rede.derrubar(2)
        rede.rodar(segundos=21)
        self.assertEqual(rede[1].rota("10.7.3.1"), ("10.7.4.1", 6))
        self.assertTrue(rede.eventos(1, "VIZINHO-INATIVO", viz="10.7.2.1"))

    def test_x2_dois_grupos_ligados_por_um_enlace(self):
        # Grupo 7 (roteadores 1 e 2) e grupo 8 (roteadores 1 e 2).
        # O enlace entre grupos é 10.7.1.1 — 10.8.1.1, custo 2.
        nucleos = {
            1: RoteadorNucleo(
                Config(
                    "10.7.1.1",
                    7101,
                    (
                        VizinhoConfig("127.0.0.1", 7102, 1),
                        VizinhoConfig("127.0.0.1", 8101, 2),
                    ),
                ),
                seq_inicial=100,
            ),
            2: RoteadorNucleo(
                Config(
                    "10.7.2.1",
                    7102,
                    (VizinhoConfig("127.0.0.1", 7101, 1),),
                ),
                seq_inicial=200,
            ),
            3: RoteadorNucleo(
                Config(
                    "10.8.1.1",
                    8101,
                    (
                        VizinhoConfig("127.0.0.1", 7101, 2),
                        VizinhoConfig("127.0.0.1", 8102, 1),
                    ),
                ),
                seq_inicial=300,
            ),
            4: RoteadorNucleo(
                Config(
                    "10.8.2.1",
                    8102,
                    (VizinhoConfig("127.0.0.1", 8101, 1),),
                ),
                seq_inicial=400,
            ),
        }
        rede = RedeSimulada(nucleos)
        rede.rodar(1)
        self.assertIn("10.8.1.1", rede[1].lsdb.origens())
        self.assertIsNotNone(rede[2].rota("10.8.2.1"))
        rede.limpar_eventos()
        rede.comando(2, "ping 10.8.2.1")
        self.assertIn("eco de 10.8.2.1", "\n".join(rede.mensagens[2]))
        rede.comando(2, "msg 10.8.2.1 atravessou")
        self.assertIn("atravessou", "\n".join(rede.mensagens[4]))

        rede.cortar_enlace(1, 3)
        rede.rodar(21)
        self.assertIsNone(rede[2].rota("10.8.2.1"))

    def test_comandos_de_exibicao(self):
        rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        rede.rodar(1)
        tabela = rede.comando(1, "tabela").mensagens[0]
        self.assertIn("10.7.4.0/24", tabela)
        self.assertIn("10.7.2.1", tabela)
        lsdb = rede.comando(1, "lsdb").mensagens[0]
        self.assertIn("10.7.5.1", lsdb)
        vizinhos = rede.comando(1, "vizinhos").mensagens[0]
        self.assertIn("ativo", vizinhos)
        passos = rede.comando(1, "dijkstra").mensagens[0]
        self.assertIn("Passo 1", passos)
        self.assertIn("10.7.1.1", passos)

    def test_enlace_off_reconverge_sem_matar_o_processo(self):
        rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        rede.rodar(1)
        rede.comando(1, "enlace off 10.7.2.1")
        rede.comando(2, "enlace off 10.7.1.1")
        rede.rodar(1)
        # Os dois lados tiraram o enlace na hora, sem esperar os 20 s.
        self.assertEqual(rede[1].rota("10.7.3.1"), ("10.7.4.1", 6))
        self.assertIn("cortado", rede.comando(1, "vizinhos").mensagens[0])

    def test_perder_um_lsp_deixa_r1_com_a_rota_velha(self):
        rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        rede.rodar(1)
        self.assertEqual(rede[1].rota("10.7.3.1"), ("10.7.2.1", 3))
        aviso = rede.comando(1, "perder 10.7.2.1").mensagens[0]
        self.assertIn("10.7.2.1", aviso)
        rede.comando(2, "enlace off 10.7.3.1")
        self.assertTrue(
            rede.eventos(1, "DESCARTADO", motivo="perda-simulada", origem="10.7.2.1")
        )
        self.assertEqual(rede[1].rota("10.7.3.1"), ("10.7.2.1", 3))
        self.assertEqual(rede[2].rota("10.7.3.1"), ("10.7.1.1", 7))
        rede.limpar_eventos()
        rede.comando(1, "ping 10.7.3.1")
        texto = "\n".join(rede.mensagens[1])
        self.assertIn("tempo excedido de 10.7.1.1", texto)
        rede.rodar(30)
        self.assertEqual(rede[1].rota("10.7.3.1"), ("10.7.4.1", 6))


if __name__ == "__main__":
    unittest.main()
