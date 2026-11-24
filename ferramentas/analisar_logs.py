"""Conta LSPs nos logs e mede o tempo até o recálculo depois de um derrubar.

    python ferramentas/analisar_logs.py logs

Cada arquivo `10.G.R.1.log` entra na contagem. Se existir `controle.log`
com `acao=derrubar`, o intervalo até o próximo `ROTAS-RECALCULADAS` de cada
roteador é o tempo de convergência visto por aquele roteador.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resume os logs do roteador.")
    parser.add_argument("diretorio", nargs="?", default="logs")
    args = parser.parse_args(argv)
    diretorio = Path(args.diretorio)
    if not diretorio.is_dir():
        print(f"diretorio inexistente: {diretorio}", file=sys.stderr)
        return 2

    arquivos = sorted(p for p in diretorio.glob("*.log") if p.name != "controle.log")
    if not arquivos:
        print("nenhum log de roteador")
        return 0

    for arquivo in arquivos:
        eventos = [_parse(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]
        eventos = [e for e in eventos if e is not None]
        print(arquivo)
        for tipo in (
            "LSP-GERADO",
            "LSP-NOVO",
            "LSP-DUPLICADO",
            "LSP-PROPRIO",
            "LSP-EXPIRADO",
            "VIZINHO-ATIVO",
            "VIZINHO-INATIVO",
            "ROTAS-RECALCULADAS",
            "ENCAMINHADO",
            "ICMP-GERADO",
            "DESCARTADO",
        ):
            total = sum(1 for e in eventos if e["tipo"] == tipo)
            if total:
                print(f"  {tipo}: {total}")

    controle = diretorio / "controle.log"
    if controle.exists():
        print()
        _convergencia(controle, arquivos)
    return 0


def _convergencia(controle: Path, arquivos: list[Path]) -> None:
    marcas = []
    for linha in controle.read_text(encoding="utf-8").splitlines():
        evento = _parse(linha)
        if evento and evento["tipo"] == "CONTROLE" and "derrubar" in evento["resto"]:
            marcas.append(evento)
    if not marcas:
        print("controle.log sem acao=derrubar")
        return
    marca = marcas[-1]
    print(f"ultimo derrubar as {marca['hora']}")
    for arquivo in arquivos:
        eventos = [
            e
            for linha in arquivo.read_text(encoding="utf-8").splitlines()
            if (e := _parse(linha)) is not None
        ]
        seguinte = next(
            (
                e
                for e in eventos
                if e["tipo"] == "ROTAS-RECALCULADAS" and _segundos(e["hora"]) >= _segundos(marca["hora"])
            ),
            None,
        )
        if seguinte is None:
            print(f"  {arquivo.name}: sem ROTAS-RECALCULADAS depois do derrubar")
            continue
        delta = _segundos(seguinte["hora"]) - _segundos(marca["hora"])
        if delta < 0:
            delta += 24 * 3600
        print(f"  {arquivo.name}: recálculo {delta:.3f}s depois ({seguinte['hora']})")


def _parse(linha: str) -> dict | None:
    partes = linha.split(" ", 2)
    if len(partes) < 2:
        return None
    return {"hora": partes[0], "tipo": partes[1], "resto": partes[2] if len(partes) > 2 else ""}


def _segundos(hora: str) -> float:
    hms, ponto, frac = hora.partition(".")
    horas, minutos, segundos = (int(p) for p in hms.split(":"))
    mili = int((frac + "000")[:3]) if ponto else 0
    return horas * 3600 + minutos * 60 + segundos + mili / 1000


if __name__ == "__main__":
    sys.exit(main())
