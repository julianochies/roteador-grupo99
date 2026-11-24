"""Gera os arquivos de configuração de uma topologia em localhost.

Exemplo:
    python ferramentas/gerar_topologia.py "1-2:1,2-3:2,1-4:5,3-4:1,3-5:3,4-5:1"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from roteador.topologia import configs_da_topologia  # noqa: E402


def escrever(spec: str, diretorio: Path, grupo: int, porta_base: int) -> list[Path]:
    diretorio.mkdir(parents=True, exist_ok=True)
    configs = configs_da_topologia(spec, grupo=grupo, porta_base=porta_base)
    escritos: list[Path] = []
    for numero, config in configs.items():
        linhas = [
            f"# Roteador {numero} do grupo {grupo}",
            f"endereco {config.endereco}",
            f"porta {config.porta}",
            "# vizinho <IP real> <porta UDP> <custo>",
        ]
        for vizinho in config.vizinhos:
            linhas.append(f"vizinho {vizinho.ip} {vizinho.porta} {vizinho.custo}")
        linhas.append("")
        caminho = diretorio / f"r{numero}.txt"
        caminho.write_text("\n".join(linhas), encoding="utf-8")
        escritos.append(caminho)
    return escritos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera config/rN.txt para uma topologia.")
    parser.add_argument("enlaces", help='ex.: "1-2:1,2-3:2,1-4:5"')
    parser.add_argument("--grupo", type=int, default=7)
    parser.add_argument("--porta-base", type=int, default=6001)
    parser.add_argument("--diretorio", default="config")
    args = parser.parse_args(argv)
    caminhos = escrever(args.enlaces, Path(args.diretorio), args.grupo, args.porta_base)
    for caminho in caminhos:
        print(caminho)
    return 0


if __name__ == "__main__":
    sys.exit(main())
