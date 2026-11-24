"""Preserva o controle de uma topologia já iniciada."""

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from ferramentas import subir_topologia


class TestSubirTopologia(TestCase):
    def test_segunda_subida_preserva_estado_e_nao_inicia_processos(self):
        with TemporaryDirectory() as pasta:
            diretorio = Path(pasta)
            (diretorio / "r1.txt").touch()
            estado = diretorio / "processos.json"
            original = '{"1": {"pid": 123, "vivo": true, "fundo": true}}'
            estado.write_text(original, encoding="utf-8")
            erro = StringIO()
            with (
                patch.object(subir_topologia, "ESTADO", estado),
                patch.object(subir_topologia.subprocess, "Popen") as iniciar,
                redirect_stderr(erro),
            ):
                self.assertEqual(
                    subir_topologia.main(["--fundo", "--diretorio", pasta]), 2
                )
            iniciar.assert_not_called()
            self.assertEqual(estado.read_text(encoding="utf-8"), original)
            self.assertIn("encerrar", erro.getvalue())
