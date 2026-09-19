"""A readable, pure-Python Motorola MC68000 instruction core."""

from m68000_python._core import AUTOVECTOR, SPURIOUS, BusError
from m68000_python.cpu import M68000CPU

__all__ = ["AUTOVECTOR", "M68000CPU", "SPURIOUS", "BusError"]
