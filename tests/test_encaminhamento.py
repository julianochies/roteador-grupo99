"""Encaminhamento de DADOS: entrega local, TTL e falta de rota."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roteador.config import Config, VizinhoConfig
from roteador.nucleo import RoteadorNucleo
from roteador.pacotes import Dados, parse, serializar
from roteador.simulacao import TOPOLOGIA_REFERENCIA, RedeSimulada


def _tipos(saida, tipo: str):
    return [e for e in saida.eventos if e.tipo == tipo]


class TestEncaminhamento(unittest.TestCase):
    def setUp(self):
        self.rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        self.rede.rodar(1)

    def test_e1_entrega_na_rede_do_roteador(self):
        self.rede.comando(1, "msg 10.7.5.1 primeiro")
        self.rede.comando(1, "msg 10.7.5.50 segundo")
        texto = "\n".join(self.rede.mensagens[5])
        self.assertIn("mensagem de 10.7.1.1 para 10.7.5.1: primeiro", texto)
        self.assertIn("mensagem de 10.7.1.1 para 10.7.5.50: segundo", texto)

    def test_e2_ttl_cai_um_a_cada_salto(self):
        self.rede.limpar_eventos()
        self.rede.comando(1, "msg 10.7.5.1 oi")
        self.assertTrue(self.rede.eventos(2, "ENCAMINHADO", tipo="DADOS", ttl="15", prox="10.7.3.1"))
        self.assertTrue(self.rede.eventos(3, "ENCAMINHADO", tipo="DADOS", ttl="14"))

    def test_e3_sem_rota_nao_envia(self):
        saida = self.rede.comando(1, "msg 10.7.99.1 oi")
        self.assertTrue(any("destino inalcancavel: 10.7.99.1" in m for m in saida.mensagens))
        self.assertEqual(saida.envios, [])

    def test_mensagem_local_nao_sai_no_fio(self):
        saida = self.rede.comando(1, "msg 10.7.1.50 aqui")
        self.assertEqual(saida.envios, [])
        self.assertTrue(any("para 10.7.1.50: aqui" in m for m in saida.mensagens))

    def test_p1_lixo_nao_derruba_e_o_ping_local_responde(self):
        nucleo = RoteadorNucleo(
            Config("10.7.1.1", 6001, (VizinhoConfig("127.0.0.1", 6002, 1),)),
            seq_inicial=1,
        )
        nucleo.tick(0)
        ruins = [
            b"",
            b"\x00\xff",
            b"QUEBRA:1",
            b"DADOS:10.7.1.1:10.7.2.1:xx:0:oi",
            b"LSP:10.7.2.1:1:10.7.1.1=0",
            "DADOS:10.7.1.1:10.7.2.1:16:0:não".encode("utf-8"),
            b"DADOS:10.7.1.1:10.7.2.1:16:0:a:b",
            b"HELLO:10.1.2",
        ]
        for bruto in ruins:
            saida = nucleo.receber(bruto, ("127.0.0.1", 6002), 1)
            self.assertTrue(_tipos(saida, "DESCARTADO"), bruto)
        resposta = nucleo.comando("ping 10.7.1.50", 1)
        self.assertTrue(any("eco de 10.7.1.50" in m for m in resposta.mensagens))

    def test_remetente_de_dados_desconhecido_nao_e_parseado_como_entrega(self):
        nucleo = self.rede[1]
        bruto = serializar(Dados("10.7.2.1", "10.7.1.1", 16, 0, "invasor"))
        saida = nucleo.receber(bruto, ("8.8.8.8", 9), self.rede.agora)
        self.assertEqual(_tipos(saida, "DESCARTADO")[0].get("motivo"), "remetente-desconhecido")
        self.assertTrue(all("invasor" not in m for m in saida.mensagens))
        # O parse do mesmo pacote, vindo do vizinho, entrega.
        ok = nucleo.receber(bruto, ("127.0.0.1", 6002), self.rede.agora)
        self.assertTrue(any("invasor" in m for m in ok.mensagens))
        parse(bruto)


if __name__ == "__main__":
    unittest.main()
