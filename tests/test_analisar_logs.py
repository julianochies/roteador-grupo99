"""Medição de uma mudança de rotas nos logs da topologia."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from ferramentas.analisar_logs import main


class TestAnalisarLogs(TestCase):
    def test_mede_primeira_mudanca_apos_queda_atravessando_meia_noite(self):
        cenarios = (
            ("2026-11-24T", "2026-11-25T"),
            ("", ""),
        )
        for antes, depois in cenarios:
            with self.subTest(antes=antes, depois=depois), TemporaryDirectory() as pasta:
                logs = Path(pasta)
                (logs / "controle.log").write_text(
                    f"{antes}23:59:55.000 CONTROLE acao=derrubar roteador=3\n",
                    encoding="utf-8",
                )
                (logs / "10.99.1.1.log").write_text(
                    f"{antes}23:59:53.000 ROTAS-RECALCULADAS mudou=rota-antiga\n"
                    f"{antes}23:59:59.000 ROTAS-RECALCULADAS mudou=-\n"
                    f"{depois}00:00:15.250 ROTAS-RECALCULADAS mudou=rota-nova\n"
                    f"{depois}00:00:16.000 ROTAS-RECALCULADAS mudou=outra-rota\n",
                    encoding="utf-8",
                )
                texto = StringIO()
                with redirect_stdout(texto):
                    self.assertEqual(main([pasta]), 0)
                self.assertIn("recálculo com mudança 20.250s depois", texto.getvalue())

    def test_queda_datada_ignora_evento_legado_em_log_reaproveitado(self):
        with TemporaryDirectory() as pasta:
            logs = Path(pasta)
            (logs / "controle.log").write_text(
                "2026-11-24T23:59:55.000 CONTROLE acao=derrubar roteador=3\n",
                encoding="utf-8",
            )
            (logs / "10.99.1.1.log").write_text(
                "23:59:56.000 ROTAS-RECALCULADAS mudou=rota-legada\n"
                "2026-11-25T00:00:15.250 ROTAS-RECALCULADAS mudou=rota-nova\n",
                encoding="utf-8",
            )
            texto = StringIO()
            with redirect_stdout(texto):
                self.assertEqual(main([pasta]), 0)
            self.assertIn("recálculo com mudança 20.250s depois", texto.getvalue())
