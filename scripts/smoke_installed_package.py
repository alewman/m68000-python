"""Smoke-test the installed m68000-python package, from outside the source tree.

    python scripts/smoke_installed_package.py

CI runs this against the freshly built wheel, and the publish workflow runs it
before any upload.  It must pass with only the installed package importable.
"""

from pathlib import Path

import m68000_python
from m68000_python import M68000CPU, CPUState, DebugSession, disassemble_bytes

source_tree = Path(__file__).resolve().parents[1] / "src"
assert source_tree not in Path(m68000_python.__file__).resolve().parents, m68000_python.__file__

memory = bytearray(1 << 16)


def read_word(address: int) -> int:
    return (memory[address] << 8) | memory[address + 1]


def write_word(address: int, value: int) -> None:
    memory[address] = value >> 8
    memory[address + 1] = value & 0xFF


memory[0:8] = (0x8000).to_bytes(4, "big") + (0x1000).to_bytes(4, "big")
memory[0x1000:0x1002] = bytes((0x70, 0x05))  # moveq #5,D0
cpu = M68000CPU(memory.__getitem__, read_word, memory.__setitem__, write_word)
assert cpu.reset() == 42
assert cpu.capture_state() == CPUState(ssp=0x8000, pc=0x1000, ir=0x7005, sr=0x2700, clock=42)
assert disassemble_bytes(bytes((0x70, 0x05)), 0x1000).text == "moveq #$5, D0"
record = DebugSession(cpu, peek_word=read_word, track_accesses=True).step()
assert (record.after.d[0], record.cycles) == (5, 4)
assert record.accesses == (("r", 0x1004, 0, 2),)
print(f"m68000-python {m68000_python.__file__}: installed package OK")
