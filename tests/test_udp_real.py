"""Dois processos de verdade em 127.0.0.1, com o tempo acelerado.

Cobre o socket único, as threads e o terminal. O restante do protocolo é
provado na rede simulada, que não depende do relógio da máquina.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


class TestUdpReal(unittest.TestCase):
    def test_dois_roteadores_convergem_e_respondem_ping(self):
        with tempfile.TemporaryDirectory() as pasta:
            base = Path(pasta)
            (base / "r1.txt").write_text(
                textwrap.dedent(
                    """\
                    endereco 10.9.1.1
                    porta 19111
                    vizinho 127.0.0.1 19112 1
                    """
                ),
                encoding="utf-8",
            )
            (base / "r2.txt").write_text(
                textwrap.dedent(
                    """\
                    endereco 10.9.2.1
                    porta 19112
                    vizinho 127.0.0.1 19111 1
                    """
                ),
                encoding="utf-8",
            )
            ambiente = os.environ.copy()
            ambiente["PYTHONUNBUFFERED"] = "1"
            processos = []
            saidas: list[list[str]] = []
            try:
                for nome in ("r1.txt", "r2.txt"):
                    sem_terminal = nome == "r2.txt"
                    proc = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "roteador",
                            str(base / nome),
                            "--escala-tempo",
                            "0.1",
                            *(["--sem-terminal"] if sem_terminal else []),
                        ],
                        cwd=RAIZ,
                        stdin=subprocess.DEVNULL if sem_terminal else subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        env=ambiente,
                    )
                    caixa: list[str] = []
                    threading.Thread(target=_ler, args=(proc, caixa), daemon=True).start()
                    processos.append(proc)
                    saidas.append(caixa)
                self.assertTrue(_esperar(saidas[0], "VIZINHO-ATIVO", 8), _texto(saidas))
                self.assertTrue(_esperar(saidas[1], "VIZINHO-ATIVO", 8), _texto(saidas))
                assert processos[0].stdin is not None
                processos[0].stdin.write("ping 10.9.2.1\n")
                processos[0].stdin.flush()
                self.assertTrue(_esperar(saidas[0], "eco de 10.9.2.1", 5), _texto(saidas))
                processos[0].stdin.write("msg 10.9.2.1 ola-udp\n")
                processos[0].stdin.flush()
                self.assertTrue(_esperar(saidas[1], "ola-udp", 5), _texto(saidas))
            finally:
                for proc in processos:
                    if proc.stdin is not None:
                        try:
                            proc.stdin.close()
                        except OSError:
                            pass
                    if proc.poll() is None:
                        proc.terminate()
                for proc in processos:
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    if proc.stdout is not None:
                        proc.stdout.close()


def _ler(proc: subprocess.Popen, caixa: list[str]) -> None:
    assert proc.stdout is not None
    for linha in proc.stdout:
        caixa.append(linha)


def _esperar(caixa: list[str], trecho: str, segundos: float) -> bool:
    import time

    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if any(trecho in linha for linha in caixa):
            return True
        time.sleep(0.05)
    return False


def _texto(saidas: list[list[str]]) -> str:
    return "\n".join(f"--- r{i + 1} ---\n" + "".join(linhas) for i, linhas in enumerate(saidas))


if __name__ == "__main__":
    unittest.main()
