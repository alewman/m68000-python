"""Instructions per second on a flat 16 MB RAM host, for the worklog and README.

    python benchmarks/speed.py [--seconds 5]

The program is a mixed loop in the shape of real 68000 code (moves through
address registers, arithmetic, a compare and branch, a DBF), assembled below
as words; it runs until the time is up and reports instructions/second and
emulated MHz (clocks/second / 1e6).  A Mega Drive's 68000 runs at 7.67 MHz.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m68000_python import M68000CPU

PROGRAM = [
    0x41F9, 0x0000, 0x2000,  # lea     $2000.l, A0
    0x43F9, 0x0000, 0x3000,  # lea     $3000.l, A1
    0x303C, 0x00FF,          # move.w  #$ff, D0
    0x3218,                  # move.w  (A0)+, D1          loop:
    0xD241,                  # add.w   D1, D1
    0x32C1,                  # move.w  D1, (A1)+
    0x0C41, 0x1234,          # cmpi.w  #$1234, D1
    0x6702,                  # beq.s   +2
    0x5282,                  # addq.l  #1, D2
    0x51C8, 0xFFF0,          # dbf     D0, loop
    0x60E2,                  # bra.s   start
]  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=5.0)
    args = parser.parse_args()
    memory = bytearray(1 << 24)
    for index, word in enumerate(PROGRAM):
        memory[0x1000 + 2 * index] = word >> 8
        memory[0x1001 + 2 * index] = word & 0xFF

    def read_byte(address: int) -> int:
        return memory[address]

    def read_word(address: int) -> int:
        return (memory[address] << 8) | memory[address + 1]

    def write_byte(address: int, value: int) -> None:
        memory[address] = value

    def write_word(address: int, value: int) -> None:
        memory[address] = value >> 8
        memory[address + 1] = value & 0xFF

    cpu = M68000CPU(read_byte, read_word, write_byte, write_word)
    cpu.set_pc(0x1000)
    step = cpu.step
    instructions = clocks = 0
    deadline = time.perf_counter() + args.seconds
    started = time.perf_counter()
    while True:
        for _ in range(10000):
            clocks += step()
        instructions += 10000
        if time.perf_counter() >= deadline:
            break
    elapsed = time.perf_counter() - started
    print(
        f"{sys.implementation.name} {sys.version.split()[0]}: "
        f"{instructions / elapsed:,.0f} instructions/s, {clocks / elapsed / 1e6:.2f} emulated MHz"
    )


if __name__ == "__main__":
    main()
