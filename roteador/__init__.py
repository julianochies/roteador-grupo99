"""Roteador de estado de enlace sobre UDP.

O programa se divide em um núcleo sem entrada/saída (`nucleo.py`), que aplica
as regras do enunciado, e uma casca fina (`udp.py`, `cli.py`, `log.py`) que
fala com o socket, o teclado e o relógio.
"""

__version__ = "1.0.0"
