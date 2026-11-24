"""Dijkstra: gabarito da topologia de referência e os casos de borda."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roteador.dijkstra import dijkstra, dijkstra_passos
from roteador.simulacao import TOPOLOGIA_REFERENCIA, RedeSimulada


def _arestas_referencia() -> dict[str, list[tuple[str, int]]]:
    """LSDB da topologia de referência, com custo igual nos dois sentidos."""
    enlaces = {
        ("10.7.1.1", "10.7.2.1"): 1,
        ("10.7.2.1", "10.7.3.1"): 2,
        ("10.7.1.1", "10.7.4.1"): 5,
        ("10.7.3.1", "10.7.4.1"): 1,
        ("10.7.3.1", "10.7.5.1"): 3,
        ("10.7.4.1", "10.7.5.1"): 1,
    }
    grafo: dict[str, list[tuple[str, int]]] = {}
    for (a, b), custo in enlaces.items():
        grafo.setdefault(a, []).append((b, custo))
        grafo.setdefault(b, []).append((a, custo))
    return grafo


class TestDijkstra(unittest.TestCase):
    def test_d1_gabarito_de_r1_e_r5(self):
        grafo = _arestas_referencia()
        r1 = dijkstra(grafo, "10.7.1.1")
        self.assertEqual(r1["10.7.2"], ("10.7.2.1", 1))
        self.assertEqual(r1["10.7.3"], ("10.7.2.1", 3))
        # O enlace direto custa 5; R1-R2-R3-R4 soma 4.
        self.assertEqual(r1["10.7.4"], ("10.7.2.1", 4))
        self.assertEqual(r1["10.7.5"], ("10.7.2.1", 5))
        self.assertNotIn("10.7.1", r1)

        r5 = dijkstra(grafo, "10.7.5.1")
        self.assertEqual(r5["10.7.1"], ("10.7.4.1", 5))
        self.assertEqual(r5["10.7.2"], ("10.7.4.1", 4))
        self.assertEqual(r5["10.7.3"], ("10.7.4.1", 2))
        self.assertEqual(r5["10.7.4"], ("10.7.4.1", 1))

    def test_d3_vizinho_sem_lsp_proprio_nao_e_expandido(self):
        grafo = {"10.7.1.1": [("10.7.2.1", 4)]}
        tabela = dijkstra(grafo, "10.7.1.1")
        self.assertEqual(tabela, {"10.7.2": ("10.7.2.1", 4)})
        passos = dijkstra_passos(grafo, "10.7.1.1")
        self.assertEqual([p.adicionou for p in passos], ["10.7.1.1", "10.7.2.1"])

    def test_d4_empate_fica_com_o_menor_proximo_salto(self):
        grafo = {
            "10.7.1.1": [("10.7.2.1", 1), ("10.7.3.1", 1)],
            "10.7.2.1": [("10.7.4.1", 1)],
            "10.7.3.1": [("10.7.4.1", 1)],
            "10.7.4.1": [],
        }
        tabela = dijkstra(grafo, "10.7.1.1")
        self.assertEqual(tabela["10.7.4"], ("10.7.2.1", 2))
        # A ordem dos vizinhos no dict não pode mudar o desempate.
        invertido = {
            "10.7.1.1": [("10.7.3.1", 1), ("10.7.2.1", 1)],
            "10.7.3.1": [("10.7.4.1", 1)],
            "10.7.2.1": [("10.7.4.1", 1)],
        }
        self.assertEqual(dijkstra(invertido, "10.7.1.1")["10.7.4"], ("10.7.2.1", 2))

    def test_d4_desempate_numerico_e_nao_alfabetico(self):
        # "10.7.10.1" vem antes de "10.7.2.1" no alfabeto, e depois no número.
        grafo = {
            "10.7.1.1": [("10.7.10.1", 1), ("10.7.2.1", 1)],
            "10.7.10.1": [("10.7.4.1", 1)],
            "10.7.2.1": [("10.7.4.1", 1)],
        }
        self.assertEqual(dijkstra(grafo, "10.7.1.1")["10.7.4"], ("10.7.2.1", 2))

    def test_d5_particao_nao_cria_rota(self):
        grafo = {
            "10.7.1.1": [("10.7.2.1", 1)],
            "10.7.2.1": [("10.7.1.1", 1)],
            "10.7.4.1": [("10.7.5.1", 1)],
            "10.7.5.1": [("10.7.4.1", 1)],
        }
        tabela = dijkstra(grafo, "10.7.1.1")
        self.assertNotIn("10.7.5", tabela)
        self.assertEqual(tabela["10.7.2"], ("10.7.2.1", 1))


class TestGabaritoNaSimulacao(unittest.TestCase):
    def test_d1_tabela_da_rede_simulada(self):
        rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
        rede.rodar(1)
        self.assertEqual(rede[1].rota("10.7.4.1"), ("10.7.2.1", 4))
        self.assertEqual(rede[5].rota("10.7.1.1"), ("10.7.4.1", 5))

    def test_d2_sem_r2_r3_ou_r4(self):
        esperado = {
            2: {"10.7.3.1": ("10.7.4.1", 6), "10.7.4.1": ("10.7.4.1", 5), "10.7.5.1": ("10.7.4.1", 6)},
            3: {"10.7.2.1": ("10.7.2.1", 1), "10.7.4.1": ("10.7.4.1", 5), "10.7.5.1": ("10.7.4.1", 6)},
            4: {"10.7.2.1": ("10.7.2.1", 1), "10.7.3.1": ("10.7.2.1", 3), "10.7.5.1": ("10.7.2.1", 6)},
        }
        for caido, rotas in esperado.items():
            with self.subTest(caido=caido):
                rede = RedeSimulada.da_topologia(TOPOLOGIA_REFERENCIA, grupo=7)
                rede.rodar(1)
                rede.derrubar(caido)
                rede.rodar(21)
                for destino, rota in rotas.items():
                    self.assertEqual(rede[1].rota(destino), rota, destino)
                self.assertIsNone(rede[1].rota(f"10.7.{caido}.1"))


if __name__ == "__main__":
    unittest.main()
