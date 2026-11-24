"""Testes de pacotes, endereços e arquivo de configuração."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roteador.config import ConfigError, ler_config
from roteador.enderecos import mesma_rede, rede_cidr, rede_de
from roteador.pacotes import PacoteMalformado, parse, serializar


EXEMPLOS = [
    b"HELLO:10.3.1.1",
    b"LSP:10.3.1.1:1767712000:10.3.2.1=1;10.3.4.1=3",
    b"LSP:10.3.1.1:1767712001:.",
    b"DADOS:10.3.1.1:10.3.4.1:16:0:Oi pessoal!",
    b"ICMP:10.3.1.1:10.3.4.1:16:42:8",
]


class TestPacotes(unittest.TestCase):
    def test_x1_exemplos_do_enunciado_byte_a_byte(self):
        for bruto in EXEMPLOS:
            self.assertEqual(serializar(parse(bruto)), bruto)
            self.assertFalse(bruto.endswith(b"\n"))

    def test_ida_e_volta_de_todos_os_tipos(self):
        for bruto in EXEMPLOS:
            self.assertEqual(parse(serializar(parse(bruto))), parse(bruto))

    def test_aceita_quebra_final(self):
        self.assertEqual(parse(b"HELLO:10.3.1.1\r\n"), parse(b"HELLO:10.3.1.1"))
        self.assertEqual(parse(b"HELLO:10.3.1.1\n"), parse(b"HELLO:10.3.1.1"))

    def test_p1_malformados(self):
        ruins = [
            b"",
            b"\xff\xfe",
            b"HELLO:10.3.1.1\n\n",
            b"PING:10.3.1.1",
            b"HELLO:10.3.1.1:extra",
            b"HELLO:10.1.2",
            b"HELLO:11.1.1.1",
            b"DADOS:10.3.1.1:10.3.4.1:abc:0:oi",
            b"DADOS:10.3.1.1:10.3.4.1:16:0:oi:pessoal",
            "DADOS:10.3.1.1:10.3.4.1:16:0:ol\u00e1".encode("utf-8"),
            b"LSP:10.3.1.1:1:10.3.2.1=0",
            b"LSP:10.3.1.1:1:",
            b"ICMP:10.3.1.1:10.3.4.1:16:1:1",
            b"ICMP:10.3.1.1:10.3.4.1:256:1:8",
        ]
        for bruto in ruins:
            with self.subTest(bruto=bruto):
                with self.assertRaises(PacoteMalformado):
                    parse(bruto)

    def test_rede_de_um_host_qualquer(self):
        self.assertEqual(rede_de("10.7.1.50"), "10.7.1")
        self.assertEqual(rede_cidr("10.7.1"), "10.7.1.0/24")
        self.assertTrue(mesma_rede("10.7.1.1", "10.7.1.50"))
        self.assertFalse(mesma_rede("10.7.1.1", "10.7.2.1"))


class TestConfig(unittest.TestCase):
    def test_leitura_e_comentario(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "r.txt"
            caminho.write_text(
                "\n".join(
                    [
                        "# comentario",
                        "endereco 10.7.1.1",
                        "porta 6001",
                        "vizinho localhost 6002 4",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            config = ler_config(str(caminho))
        self.assertEqual(config.endereco, "10.7.1.1")
        self.assertEqual(config.porta, 6001)
        self.assertEqual(config.vizinhos[0].ip, "127.0.0.1")
        self.assertEqual(config.vizinhos[0].custo, 4)

    def test_erros_apontam_a_linha(self):
        casos = [
            "porta 6000\n",
            "endereco 10.7.1.2\n",
            "endereco 10.7.1.1\nvizinho 127.0.0.1 6000 0\n",
            "endereco 10.7.1.1\nvizinho 127.0.0.1 6000 1\nvizinho 127.0.0.1 6000 2\n",
            "endereco 10.7.1.1\nlinha esquisita\n",
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                with tempfile.TemporaryDirectory() as pasta:
                    caminho = Path(pasta) / "r.txt"
                    caminho.write_text(texto, encoding="utf-8")
                    with self.assertRaises(ConfigError) as ctx:
                        ler_config(str(caminho))
                    self.assertGreater(ctx.exception.linha, 0)


if __name__ == "__main__":
    unittest.main()
