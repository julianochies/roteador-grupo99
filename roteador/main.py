"""Ponto de entrada: `python -m roteador config/r1.txt`."""

from __future__ import annotations

import argparse
import sys
import time

from roteador.config import ConfigError, ler_config
from roteador.log import Log
from roteador.nucleo import RoteadorNucleo
from roteador.relogio import RelogioReal
from roteador.udp import RoteadorUDP


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="roteador",
        description="Roteador de estado de enlace sobre UDP.",
    )
    parser.add_argument("config", help="arquivo de configuracao do roteador")
    parser.add_argument(
        "--escala-tempo",
        type=float,
        default=1.0,
        help="1.0 = tempo real; 0.1 faz os temporizadores andarem 10x mais rapido",
    )
    parser.add_argument(
        "--perda-lsp",
        type=float,
        default=0.0,
        help="probabilidade de descartar um LSP recebido (questao 5)",
    )
    parser.add_argument(
        "--semente",
        type=int,
        default=1,
        help="semente da perda aleatoria de LSP",
    )
    parser.add_argument(
        "--perder-proximo-lsp-de",
        action="append",
        default=[],
        metavar="ORIGEM",
        help="descarta so o proximo LSP desta origem (pode repetir a opcao)",
    )
    args = parser.parse_args(argv)
    if args.escala_tempo <= 0:
        print("escala de tempo deve ser positiva", file=sys.stderr)
        return 2
    if not 0.0 <= args.perda_lsp <= 1.0:
        print("perda de LSP deve estar entre 0 e 1", file=sys.stderr)
        return 2
    try:
        config = ler_config(args.config)
    except ConfigError as erro:
        print(f"erro na configuracao: {erro}", file=sys.stderr)
        return 2

    nucleo = RoteadorNucleo(
        config,
        seq_inicial=int(time.time()),
        perda_lsp=args.perda_lsp,
        semente=args.semente,
        perder_proximo_lsp_de=set(args.perder_proximo_lsp_de),
    )
    try:
        relogio = RelogioReal(args.escala_tempo)
    except ValueError as erro:
        print(str(erro), file=sys.stderr)
        return 2
    log = Log(config.endereco)
    try:
        RoteadorUDP(nucleo, relogio, log).servir()
    except OSError as erro:
        print(f"nao foi possivel abrir a porta {config.porta}: {erro}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
