"""Envia um pacote UDP cru, para malformados e para simular outro grupo.

O pacote sai da porta `--de-porta`, que precisa ser a porta de um vizinho
configurado no roteador alvo — de outro par ele é descartado antes do parse.

    python ferramentas/injetor.py 127.0.0.1 6001 --de-porta 6002 "LSP:10.7.9.1:1:."
"""

from __future__ import annotations

import argparse
import socket
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Envia um datagrama UDP cru.")
    parser.add_argument("ip")
    parser.add_argument("porta", type=int)
    parser.add_argument("pacote", help="texto do pacote; latin-1, para poder ir acento")
    parser.add_argument("--de-porta", type=int, required=True)
    args = parser.parse_args(argv)
    dados = args.pacote.encode("latin-1")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", args.de_porta))
        sock.sendto(dados, (args.ip, args.porta))
    print(f"enviados {len(dados)} bytes de :{args.de_porta} para {args.ip}:{args.porta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
