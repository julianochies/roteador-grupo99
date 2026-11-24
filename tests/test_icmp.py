"""ICMP: eco, tempo excedido, destino inalcançável e erro sobre erro."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roteador.pacotes import Icmp, serializar
from roteador.simulacao import TOPOLOGIA_REFERENCIA, RedeSimulada


def _tipos(saida, tipo: str):
    return [e for e in saida.eventos if e.tipo == tipo]


class TestIcmp(unittest.TestCase):
    def setUp(self):
        self.rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        self.rede.rodar(1)

    def test_i1_ping_com_ttl_crescente_ate_r5(self):
        esperado = [
            "tempo excedido de 10.7.2.1",
            "tempo excedido de 10.7.3.1",
            "tempo excedido de 10.7.4.1",
            "eco de 10.7.5.1",
        ]
        for ttl, trecho in enumerate(esperado, start=1):
            self.rede.limpar_eventos()
            self.rede.comando(1, f"ping 10.7.5.1 {ttl}")
            texto = "\n".join(self.rede.mensagens[1])
            self.assertIn(trecho, texto, f"ttl {ttl}: {texto}")
        self.rede.limpar_eventos()
        self.rede.comando(1, "ping 10.7.5.1 8")
        self.assertIn("eco de 10.7.5.1", "\n".join(self.rede.mensagens[1]))

    def test_i2_eco_usa_o_endereco_que_foi_pingado(self):
        self.rede.limpar_eventos()
        self.rede.comando(1, "ping 10.7.5.50")
        texto = "\n".join(self.rede.mensagens[1])
        self.assertIn("eco de 10.7.5.50", texto)
        self.assertNotIn("eco de 10.7.5.1", texto)

    def test_i3_intermediario_sem_rota_gera_tipo_3(self):
        # Linha reta: sem o enlace R2–R3 não há outro caminho. R1 perde o
        # LSP em que R2 anuncia a queda e continua mandando o ping para R2.
        rede = RedeSimulada.da_topologia("1-2:1,2-3:1", grupo=7)
        rede.rodar(1)
        rede[1].perder_proxima.add("10.7.2.1")
        rede.comando(2, "enlace off 10.7.3.1")
        self.assertEqual(rede[1].rota("10.7.3.1"), ("10.7.2.1", 2))
        self.assertIsNone(rede[2].rota("10.7.3.1"))
        rede.limpar_eventos()
        rede.comando(1, "ping 10.7.3.1")
        texto = "\n".join(rede.mensagens[1])
        self.assertIn("destino inalcancavel de 10.7.2.1", texto)

    def test_i4_erro_nao_gera_outro_erro(self):
        pacote = serializar(Icmp("10.7.4.1", "10.7.5.1", 1, 7, 11))
        saida = self.rede[1].receber(pacote, ("127.0.0.1", 6002), self.rede.agora)
        self.assertTrue(_tipos(saida, "DESCARTADO"))
        self.assertFalse(_tipos(saida, "ICMP-GERADO"))
        sem_rota = serializar(Icmp("10.7.4.1", "10.7.99.1", 16, 7, 3))
        saida = self.rede[1].receber(sem_rota, ("127.0.0.1", 6002), self.rede.agora)
        self.assertFalse(_tipos(saida, "ICMP-GERADO"))

    def test_i5_resposta_de_eco_com_ttl_esgotado_gera_11(self):
        pacote = serializar(Icmp("10.7.2.1", "10.7.5.1", 1, 9, 0))
        saida = self.rede[1].receber(pacote, ("127.0.0.1", 6002), self.rede.agora)
        gerados = _tipos(saida, "ICMP-GERADO")
        self.assertTrue(any(e.get("tipo") == "11" for e in gerados))

    def test_i6_timeout_se_o_destino_caiu_e_a_rota_ainda_existe(self):
        self.rede.derrubar(5)
        self.rede.limpar_eventos()
        self.rede.comando(1, "ping 10.7.5.1")
        self.assertIsNotNone(self.rede[1].rota("10.7.5.1"))
        self.rede.rodar(2)
        self.assertTrue(any(m.startswith("timeout ") for m in self.rede.mensagens[1]))

    def test_i7_dois_pings_casam_pelo_id(self):
        self.rede.limpar_eventos()
        self.rede.comando(1, "ping 10.7.2.1")
        self.rede.comando(1, "ping 10.7.5.1")
        texto = "\n".join(self.rede.mensagens[1])
        self.assertIn("eco de 10.7.2.1 id=1", texto)
        self.assertIn("eco de 10.7.5.1 id=2", texto)

    def test_ping_local_responde_sem_enviar(self):
        saida = self.rede.comando(1, "ping 10.7.1.77 4")
        self.assertEqual(saida.envios, [])
        self.assertTrue(any("eco de 10.7.1.77" in m for m in saida.mensagens))

    def test_terminal_recusa_acento_e_dois_pontos(self):
        saida = self.rede.comando(1, "msg 10.7.2.1 olá")
        self.assertEqual(saida.envios, [])
        self.assertTrue(saida.mensagens)
        saida = self.rede.comando(1, "msg 10.7.2.1 a:b")
        self.assertEqual(saida.envios, [])


if __name__ == "__main__":
    unittest.main()
