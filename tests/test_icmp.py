"""ICMP: eco, tempo excedido, destino inalcançável e erro sobre erro."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roteador.pacotes import Icmp, parse, serializar
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
        self.assertIn("eco de 10.7.5.1 id=3", texto)

    def test_erro_de_msg_nao_consumira_ping_com_rtt(self):
        roteador = self.rede[1]
        ping = roteador.comando("ping 10.7.2.1", 1.0)
        msg = roteador.comando("msg 10.7.5.1 teste", 1.0)
        id_ping = parse(ping.envios[0][0]).id
        id_msg = parse(msg.envios[0][0]).id
        self.assertNotEqual(id_ping, id_msg)

        endpoint = ("127.0.0.1", 6002)
        erro = serializar(Icmp("10.7.2.1", "10.7.1.1", 16, id_msg, 3))
        self.assertEqual(
            roteador.receber(erro, endpoint, 1.25).mensagens,
            [f"destino inalcancavel de 10.7.2.1 id={id_msg}"],
        )
        eco = serializar(Icmp("10.7.2.1", "10.7.1.1", 16, id_ping, 0))
        self.assertEqual(
            roteador.receber(eco, endpoint, 1.5).mensagens,
            [f"eco de 10.7.2.1 id={id_ping} rtt=500.0ms"],
        )

    def test_eco_de_outra_origem_nao_consumira_ping(self):
        roteador = self.rede[1]
        ping = roteador.comando("ping 10.7.2.50", 1.0)
        identificador = parse(ping.envios[0][0]).id
        endpoint = ("127.0.0.1", 6002)
        errado = serializar(Icmp("10.7.2.1", "10.7.1.1", 16, identificador, 0))
        self.assertEqual(roteador.receber(errado, endpoint, 1.25).mensagens, [])
        certo = serializar(Icmp("10.7.2.50", "10.7.1.1", 16, identificador, 0))
        self.assertEqual(
            roteador.receber(certo, endpoint, 1.5).mensagens,
            [f"eco de 10.7.2.50 id={identificador} rtt=500.0ms"],
        )

    def test_eco_no_prazo_limite_expira_sem_esperar_tick(self):
        roteador = self.rede[1]
        ping = roteador.comando("ping 10.7.2.1", 1.0)
        identificador = parse(ping.envios[0][0]).id
        endpoint = ("127.0.0.1", 6002)
        eco = serializar(Icmp("10.7.2.1", "10.7.1.1", 16, identificador, 0))
        self.assertEqual(
            roteador.receber(eco, endpoint, 3.0).mensagens,
            [f"timeout id={identificador} destino=10.7.2.1"],
        )
        self.assertEqual(roteador.tick(3.5).mensagens, [])
        self.assertEqual(roteador.receber(eco, endpoint, 3.5).mensagens, [])

    def test_erro_icmp_atrasado_resulta_apenas_em_timeout(self):
        endpoint = ("127.0.0.1", 6002)
        enviado = 1.0
        for tipo in (3, 11):
            for tick_primeiro in (True, False):
                with self.subTest(tipo=tipo, tick_primeiro=tick_primeiro):
                    roteador = self.rede[1]
                    ping = roteador.comando("ping 10.7.2.1", enviado)
                    identificador = parse(ping.envios[0][0]).id
                    erro = serializar(Icmp("10.7.2.1", "10.7.1.1", 16, identificador, tipo))
                    if tick_primeiro:
                        mensagens = roteador.tick(enviado + 2).mensagens
                        mensagens += roteador.receber(erro, endpoint, enviado + 2.25).mensagens
                    else:
                        mensagens = roteador.receber(erro, endpoint, enviado + 2.25).mensagens
                        mensagens += roteador.tick(enviado + 2.5).mensagens
                    self.assertEqual(mensagens, [f"timeout id={identificador} destino=10.7.2.1"])
                    enviado += 3

    def test_terminal_recusa_digitos_invalidos_sem_encerrar(self):
        longo = "9" * 5000
        for comando in (
            "ping 10.7.2.1 ²",
            "ping 10.7.².1",
            f"ping 10.7.2.1 {longo}",
            f"ping 10.7.{longo}.1",
        ):
            with self.subTest(comando=comando[:30]):
                saida = self.rede.comando(1, comando)
                self.assertEqual(saida.envios, [])
                self.assertTrue(saida.mensagens)
        self.assertTrue(self.rede.comando(1, "ping 10.7.2.1").envios)

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
