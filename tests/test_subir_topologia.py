"""Preserva o controle de uma topologia já iniciada."""

import json
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from subprocess import CompletedProcess
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
            original = '{"1": {"pid": 123, "vivo": true, "fundo": true, "id_lancamento": "abc"}}'
            estado.write_text(original, encoding="utf-8")
            erro = StringIO()
            with (
                patch.object(subir_topologia, "ESTADO", estado),
                patch.object(subir_topologia.subprocess, "Popen") as iniciar,
                patch.object(
                    subir_topologia.subprocess,
                    "run",
                    return_value=CompletedProcess([], 0, "python -m roteador --id-lancamento=abc", ""),
                ),
                redirect_stderr(erro),
            ):
                self.assertEqual(
                    subir_topologia.main(["--fundo", "--diretorio", pasta]), 2
                )
            iniciar.assert_not_called()
            self.assertEqual(estado.read_text(encoding="utf-8"), original)
            self.assertIn("encerrar", erro.getvalue())

    def test_subir_substitui_registro_de_processo_ja_encerrado(self):
        with TemporaryDirectory() as pasta:
            diretorio = Path(pasta)
            (diretorio / "r1.txt").touch()
            registro = {"1": {"pid": 123, "vivo": True, "id_lancamento": "abc"}}
            # O ps usa status 1 quando o PID já saiu.
            with (
                patch.object(subir_topologia, "_ler_estado", return_value=registro),
                patch.object(subir_topologia, "_salvar_estado"),
                patch.object(subir_topologia, "_iniciar") as iniciar,
                patch.object(subir_topologia.os, "name", "posix"),
                patch.object(
                    subir_topologia.subprocess, "run", return_value=CompletedProcess([], 1, "", "")
                ),
            ):
                self.assertEqual(subir_topologia._subir(diretorio, True, 1), 0)
            iniciar.assert_called_once_with(1, diretorio / "r1.txt", True, 1, {})

    def test_encerrar_nao_sinaliza_pid_reutilizado_ou_registro_legado(self):
        registro = {
            "1": {"pid": 123, "vivo": True, "id_lancamento": "abc"},
            "2": {"pid": 234, "vivo": True},
        }
        with (
            patch.object(subir_topologia, "_ler_estado", return_value=registro),
            patch.object(subir_topologia, "_salvar_estado") as salvar,
            patch.object(subir_topologia, "_controle"),
            patch.object(subir_topologia, "_matar") as matar,
            patch.object(
                subir_topologia.subprocess,
                "run",
                return_value=CompletedProcess([], 0, "python -m outro --id-lancamento=abcd", ""),
            ),
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(subir_topologia._encerrar(), 0)
        matar.assert_not_called()
        self.assertEqual(salvar.call_count, 2)
        self.assertFalse(any(info["vivo"] for info in registro.values()))

    def test_encerrar_persiste_primeiro_progresso_antes_de_falha_no_probe_seguinte(self):
        registro = {
            "1": {"pid": 123, "vivo": True, "id_lancamento": "abc"},
            "2": {"pid": 234, "vivo": True, "id_lancamento": "def"},
        }
        passos = []

        def consultar(info):
            passos.append(("consultar", info["pid"]))
            if info["pid"] == 234:
                raise OSError("processo indisponível")
            return True

        def salvar(estado):
            passos.append(("salvar", json.loads(json.dumps(estado))))

        with (
            patch.object(subir_topologia, "_ler_estado", return_value=registro),
            patch.object(subir_topologia, "_processo_corresponde", side_effect=consultar),
            patch.object(subir_topologia, "_matar", side_effect=lambda pid: passos.append(("matar", pid))),
            patch.object(subir_topologia, "_salvar_estado", side_effect=salvar),
            patch.object(subir_topologia, "_controle") as controle,
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(subir_topologia.main(["encerrar"]), 2)
        controle.assert_not_called()
        self.assertEqual(
            passos,
            [("consultar", 123), ("matar", 123), ("salvar", registro), ("consultar", 234)],
        )
        self.assertFalse(registro["1"]["vivo"])
        self.assertTrue(registro["2"]["vivo"])

    def test_falha_no_probe_impede_trocar_estado(self):
        with TemporaryDirectory() as pasta:
            diretorio = Path(pasta)
            (diretorio / "r1.txt").touch()
            registro = {"1": {"pid": 123, "vivo": True, "id_lancamento": "abc"}}
            with (
                patch.object(subir_topologia, "_ler_estado", return_value=registro),
                patch.object(subir_topologia, "_salvar_estado") as salvar,
                patch.object(subir_topologia, "_iniciar") as iniciar,
                patch.object(
                    subir_topologia.subprocess,
                    "run",
                    return_value=CompletedProcess([], 1, "", "permissão negada"),
                ),
                redirect_stderr(StringIO()) as erro,
            ):
                self.assertEqual(subir_topologia.main(["--fundo", "--diretorio", pasta]), 2)
            iniciar.assert_not_called()
            salvar.assert_not_called()
            self.assertTrue(registro["1"]["vivo"])
            self.assertIn("nao foi possivel consultar o processo 123", erro.getvalue())
