"""LSDB, número de sequência, inundação e envelhecimento."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roteador.config import Config, VizinhoConfig
from roteador.nucleo import RoteadorNucleo
from roteador.pacotes import Hello, Lsp, serializar
from roteador.simulacao import TOPOLOGIA_REFERENCIA, RedeSimulada


def _com_dois_vizinhos() -> RoteadorNucleo:
    config = Config(
        "10.7.1.1",
        6001,
        (
            VizinhoConfig("127.0.0.1", 6002, 1),
            VizinhoConfig("127.0.0.1", 6004, 5),
        ),
    )
    nucleo = RoteadorNucleo(config, seq_inicial=5_000)
    nucleo.tick(0)
    nucleo.receber(serializar(Hello("10.7.2.1")), ("127.0.0.1", 6002), 0)
    nucleo.receber(serializar(Hello("10.7.4.1")), ("127.0.0.1", 6004), 0)
    return nucleo


def _tipos(saida, tipo: str):
    return [e for e in saida.eventos if e.tipo == tipo]


class TestLsdb(unittest.TestCase):
    def test_l1_seq_inicial_e_renovacao(self):
        nucleo = RoteadorNucleo(Config("10.7.1.1", 6001, ()), seq_inicial=1_700_000_000)
        primeiro = nucleo.tick(0)
        gerado = _tipos(primeiro, "LSP-GERADO")[0]
        self.assertEqual(gerado.get("seq"), "1700000000")
        self.assertEqual(gerado.get("motivo"), "inicio")
        self.assertFalse(_tipos(nucleo.tick(29), "LSP-GERADO"))
        renovado = _tipos(nucleo.tick(30), "LSP-GERADO")[0]
        self.assertEqual(renovado.get("seq"), "1700000001")
        self.assertEqual(renovado.get("motivo"), "renovacao")

    def test_l2_l3_l4_seq_maior_igual_e_menor(self):
        nucleo = _com_dois_vizinhos()
        novo = serializar(Lsp("10.7.3.1", 10, (("10.7.2.1", 2),)))
        primeiro = nucleo.receber(novo, ("127.0.0.1", 6002), 1)
        self.assertTrue(_tipos(primeiro, "LSP-NOVO"))
        self.assertEqual(len(_tipos(primeiro, "ROTAS-RECALCULADAS")), 1)
        # Reenviado ao outro vizinho, não a quem mandou.
        destinos = [d for _b, d in primeiro.envios]
        self.assertIn(("127.0.0.1", 6004), destinos)
        self.assertNotIn(("127.0.0.1", 6002), destinos)

        copia = nucleo.receber(novo, ("127.0.0.1", 6004), 1)
        self.assertTrue(_tipos(copia, "LSP-DUPLICADO"))
        self.assertEqual(copia.envios, [])
        self.assertFalse(_tipos(copia, "ROTAS-RECALCULADAS"))

        velho = serializar(Lsp("10.7.3.1", 9, ()))
        menor = nucleo.receber(velho, ("127.0.0.1", 6002), 1)
        self.assertTrue(_tipos(menor, "LSP-DUPLICADO"))
        self.assertEqual(nucleo.lsdb.obter("10.7.3.1").lsp.seq, 10)

    def test_l5_lsp_proprio_e_descartado(self):
        nucleo = _com_dois_vizinhos()
        bruto = serializar(Lsp("10.7.1.1", 99999, ()))
        saida = nucleo.receber(bruto, ("127.0.0.1", 6002), 1)
        self.assertTrue(_tipos(saida, "LSP-PROPRIO"))
        self.assertNotEqual(nucleo.lsdb.obter("10.7.1.1").lsp.seq, 99999)

    def test_l6_reenvio_preserva_os_bytes(self):
        nucleo = _com_dois_vizinhos()
        bruto = b"LSP:10.7.3.1:40:10.7.2.1=2\r\n"
        saida = nucleo.receber(bruto, ("127.0.0.1", 6002), 1)
        encaminhados = [dados for dados, destino in saida.envios if destino == ("127.0.0.1", 6004)]
        self.assertEqual(encaminhados, [bruto])

    def test_l7_envelhece_aos_90_e_o_proprio_fica(self):
        nucleo = _com_dois_vizinhos()
        bruto = serializar(Lsp("10.7.3.1", 3, ()))
        nucleo.receber(bruto, ("127.0.0.1", 6002), 0)
        nucleo.tick(89)
        self.assertIsNotNone(nucleo.lsdb.obter("10.7.3.1"))
        saida = nucleo.tick(90)
        self.assertIsNone(nucleo.lsdb.obter("10.7.3.1"))
        self.assertIsNotNone(nucleo.lsdb.obter("10.7.1.1"))
        self.assertTrue(_tipos(saida, "LSP-EXPIRADO"))
        self.assertTrue(_tipos(saida, "ROTAS-RECALCULADAS"))

    def test_l8_sem_vizinhos_ativos_a_lista_e_ponto(self):
        nucleo = RoteadorNucleo(Config("10.7.1.1", 6001, ()), seq_inicial=10)
        saida = nucleo.tick(0)
        bruto = serializar(nucleo.lsdb.obter("10.7.1.1").lsp)
        self.assertEqual(bruto, b"LSP:10.7.1.1:10:.")
        self.assertEqual(_tipos(saida, "LSP-GERADO")[0].get("viz"), ".")

    def test_d6_um_recalculo_por_mudanca_e_nenhum_na_copia(self):
        nucleo = _com_dois_vizinhos()
        antes = len([e for e in []])
        saida = nucleo.receber(serializar(Lsp("10.7.9.1", 1, ())), ("127.0.0.1", 6002), 2)
        self.assertEqual(len(_tipos(saida, "ROTAS-RECALCULADAS")), 1)
        copia = nucleo.receber(serializar(Lsp("10.7.9.1", 1, ())), ("127.0.0.1", 6004), 2)
        self.assertEqual(len(_tipos(copia, "ROTAS-RECALCULADAS")), 0)
        self.assertEqual(antes, 0)

    def test_l9_uma_inundacao_na_topologia_de_referencia(self):
        # N=5, E=6 → 4 aceitos e 4 cópias. envios = 2E-N+1 = 8.
        rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        rede.rodar(1)
        rede.limpar_eventos()
        rede.forcar_lsp(1)
        self.assertEqual(rede.contar("LSP-NOVO"), 4)
        self.assertEqual(rede.contar("LSP-DUPLICADO"), 4)

    def test_l10_reinicio_com_seq_maior_e_aceito(self):
        rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        rede.rodar(1)
        antigo = rede[2].lsdb.obter("10.7.1.1").lsp.seq
        rede.derrubar(1)
        rede.religar(1)
        # O vizinho que ficou no ar manda HELLO no período de 5 s. Só então
        # o roteador reiniciado anuncia o seq novo.
        rede.rodar(5)
        novo = rede[2].lsdb.obter("10.7.1.1").lsp.seq
        self.assertGreater(novo, antigo)

    def test_reinicio_rapido_recupera_a_lsdb(self):
        rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        rede.rodar(1)
        rede.derrubar(2)
        rede.religar(2)
        rede.rodar(5)
        self.assertIsNotNone(rede[2].rota("10.7.5.1"))
        self.assertIn("10.7.4.1", rede[2].lsdb.origens())


if __name__ == "__main__":
    unittest.main()
