"""Sobe, derruba e religa os roteadores da pasta config/.

    python ferramentas/subir_topologia.py
    python ferramentas/subir_topologia.py --fundo
    python ferramentas/subir_topologia.py derrubar 3
    python ferramentas/subir_topologia.py religar 3
    python ferramentas/subir_topologia.py encerrar

No Windows, o modo normal abre um console por roteador. Em outros sistemas,
rode `python -m roteador config/rN.txt` em terminais separados ou use
`--fundo` para gravar a saída em logs/rN.out sem ler comandos.
`derrubar` registra o horário em logs/controle.log para o analisar_logs.py.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

ESTADO = RAIZ / "logs" / "processos.json"
CONTROLE = RAIZ / "logs" / "controle.log"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sobe a topologia local.")
    parser.add_argument("acao", nargs="?", default="subir", choices=["subir", "derrubar", "religar", "encerrar"])
    parser.add_argument("roteador", nargs="?", type=int)
    parser.add_argument("--fundo", action="store_true", help="roda sem abrir console")
    parser.add_argument("--diretorio", default="config")
    parser.add_argument("--escala-tempo", type=float, default=1.0)
    args = parser.parse_args(argv)

    if args.acao in ("derrubar", "religar") and args.roteador is None:
        print("informe o numero do roteador", file=sys.stderr)
        return 2
    try:
        if args.acao == "subir":
            return _subir(Path(args.diretorio), args.fundo, args.escala_tempo)
        if args.acao == "derrubar":
            return _derrubar(args.roteador)
        if args.acao == "religar":
            return _religar(args.roteador, args.fundo, args.escala_tempo)
        return _encerrar()
    except OSError as erro:
        print(f"falha no controle da topologia: {erro}", file=sys.stderr)
        return 2


def _subir(diretorio: Path, fundo: bool, escala: float) -> int:
    if not _modo_disponivel(fundo):
        return 2
    arquivos = sorted(diretorio.glob("r*.txt"))
    if not arquivos:
        print(f"nenhum rN.txt em {diretorio}", file=sys.stderr)
        return 2
    estado = _ler_estado()
    if _estado_legado(estado.values()):
        return 2
    if any(_processo_corresponde(info) for info in estado.values()):
        print("topologia ja iniciada; use encerrar antes de subir novamente", file=sys.stderr)
        return 2
    estado.clear()
    for arquivo in arquivos:
        numero = int(arquivo.stem[1:])
        _iniciar(numero, arquivo, fundo, escala, estado)
        _salvar_estado(estado)
    print(f"{len(arquivos)} roteadores no ar")
    return 0


def _iniciar(numero: int, arquivo: Path, fundo: bool, escala: float, estado: dict) -> None:
    identificador = uuid4().hex
    cmd = [
        sys.executable, "-m", "roteador", str(arquivo),
        "--escala-tempo", str(escala), f"--id-lancamento={identificador}",
    ]
    if fundo:
        cmd.append("--sem-terminal")
        destino = RAIZ / "logs"
        destino.mkdir(parents=True, exist_ok=True)
        with (destino / f"r{numero}.out").open("a", encoding="utf-8") as saida:
            proc = subprocess.Popen(
                cmd,
                cwd=RAIZ,
                stdin=subprocess.DEVNULL,
                stdout=saida,
                stderr=subprocess.STDOUT,
                start_new_session=os.name == "posix",
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            )
    else:
        proc = subprocess.Popen(cmd, cwd=RAIZ, creationflags=subprocess.CREATE_NEW_CONSOLE)
    estado[str(numero)] = {
        "pid": proc.pid,
        "config": str(arquivo),
        "vivo": True,
        "fundo": fundo,
        "id_lancamento": identificador,
    }
    print(f"r{numero} pid={proc.pid}")


def _modo_disponivel(fundo: bool) -> bool:
    if fundo or os.name == "nt":
        return True
    print(
        "use --fundo ou rode python -m roteador <config> em terminais separados",
        file=sys.stderr,
    )
    return False


def _derrubar(numero: int) -> int:
    estado = _ler_estado()
    info = estado.get(str(numero))
    if info and _estado_legado([info]):
        return 2
    if not info or not _processo_corresponde(info):
        print(f"r{numero} nao esta no ar", file=sys.stderr)
        return 2
    _matar(info["pid"])
    info["vivo"] = False
    _salvar_estado(estado)
    _controle(f"acao=derrubar roteador={numero}")
    print(f"r{numero} derrubado")
    return 0


def _religar(numero: int, fundo: bool, escala: float) -> int:
    estado = _ler_estado()
    info = estado.get(str(numero))
    if info is None:
        print(f"r{numero} nao foi iniciado por este script", file=sys.stderr)
        return 2
    fundo = fundo or info.get("fundo", False)
    if not _modo_disponivel(fundo):
        return 2
    if _estado_legado([info]):
        return 2
    if _processo_corresponde(info):
        _matar(info["pid"])
    _iniciar(numero, Path(info["config"]), fundo, escala, estado)
    _salvar_estado(estado)
    _controle(f"acao=religar roteador={numero}")
    return 0


def _encerrar() -> int:
    estado = _ler_estado()
    if any(info.get("vivo") and not info.get("id_lancamento") for info in estado.values()):
        print("feche manualmente os roteadores iniciados por uma versao anterior", file=sys.stderr)
    for info in estado.values():
        if not info.get("vivo"):
            continue
        if _processo_corresponde(info):
            _matar(info["pid"])
        info["vivo"] = False
        _salvar_estado(estado)
    _controle("acao=encerrar")
    print("topologia encerrada")
    return 0


def _estado_legado(registros) -> bool:
    if not any(info.get("vivo") and not info.get("id_lancamento") for info in registros):
        return False
    print(
        "feche os roteadores da versao anterior manualmente e use encerrar para limpar o registro",
        file=sys.stderr,
    )
    return True


def _processo_corresponde(info: dict) -> bool:
    identificador = info.get("id_lancamento")
    if not info.get("vivo") or not identificador:
        return False
    pid = int(info["pid"])
    if pid <= 0:
        return False
    if os.name == "nt":
        consulta = (
            "try { "
            f"$processo = Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}' -ErrorAction Stop; "
            "if ($processo) { "
            "if (-not $processo.CommandLine) { exit 2 }; $processo.CommandLine "
            "} } catch { exit 2 }"
        )
        comando = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", consulta]
        flags = subprocess.CREATE_NO_WINDOW
    else:
        comando = ["ps", "-ww", "-p", str(pid), "-o", "args="]
        flags = 0
    resultado = subprocess.run(
        comando, capture_output=True, text=True, errors="replace", creationflags=flags,
    )
    if os.name == "posix" and resultado.returncode == 1 and not (resultado.stdout or resultado.stderr):
        return False
    if resultado.returncode != 0:
        raise OSError(f"nao foi possivel consultar o processo {pid}")
    return f"--id-lancamento={identificador}" in resultado.stdout.split()


def _matar(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def _controle(campos: str) -> None:
    CONTROLE.parent.mkdir(parents=True, exist_ok=True)
    hora = datetime.now().isoformat(timespec="milliseconds")
    with CONTROLE.open("a", encoding="utf-8") as arquivo:
        arquivo.write(f"{hora} CONTROLE {campos}\n")


def _ler_estado() -> dict:
    if not ESTADO.exists():
        return {}
    return json.loads(ESTADO.read_text(encoding="utf-8"))


def _salvar_estado(estado: dict) -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(estado, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
