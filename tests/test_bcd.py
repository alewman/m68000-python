"""Rung 2: ABCD, SBCD and NBCD over every input, against the T1 BCD tables.

flamewing/68k-bcd-verifier (GPL-3.0, commit 39a01be528b0744302bf1dc9b3463fc22a3fc45f,
2018-08-31) is a Sega Genesis ROM that runs ABCD and SBCD on every pair of
bytes and NBCD on every byte, each with X and Z clear and set, and checks the
result and all five flags against a table its ``bcd-gen.cc`` generates; its
README: "Real hardware naturally passes all tests; this has been verified on:
Model 1 Sega Genesis, Model 3 VA2 Sega Genesis."  The table is therefore
hardware-verified (T1).  Neither the table nor the generator is copied here
(GPL-3.0); the gate compares the SHA-256 of the table this core produces, in
the generator's exact layout, with the SHA-256 of the generator's output:

    g++ -O2 -o bcd-gen bcd-gen.cc bcd-emul.cc && ./bcd-gen   # at 39a01be
    sha256sum data/bcd-table.bin
    8432868c9aa93c92574bae48bebd4efb2834e298340eb09530625365b80147e5

Layout (bcd-gen.cc): for ABCD then SBCD, for source 0-255, destination 0-255,
X 0-1, Z 0-1: one byte of flags (X N Z V C in bits 4-0) and one byte of
result; then NBCD for operand 0-255, X 0-1, Z 0-1.  Initial N, V clear and
C equal to X, as the verifier's Context sets them.  1,050,624 bytes:
262,144 + 262,144 + 1,024 cases.

Set M68000_BCD_TABLE to a local copy of bcd-table.bin to have a mismatch
reported case by case instead of as a hash.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from m68000_python import M68000CPU

TABLE_SHA256 = "8432868c9aa93c92574bae48bebd4efb2834e298340eb09530625365b80147e5"
ABCD_D1_D0 = 0xC101  # ABCD D1,D0: destination D0, source D1
SBCD_D1_D0 = 0x8101
NBCD_D0 = 0x4800


def _cpu() -> M68000CPU:
    def read_word(address: int) -> int:
        return 0x4E71  # NOP, for the prefetch

    return M68000CPU(lambda a: 0x4E, read_word, lambda a, v: None, lambda a, v: None)


def _run(cpu: M68000CPU, opcode: int, destination: int, source: int, x: int, z: int) -> bytes:
    cpu.R[0] = destination
    cpu.R[1] = source
    cpu.SR = 0x2700 | (0x11 if x else 0) | (0x04 if z else 0)
    cpu.ir = opcode
    cpu.irc = 0x4E71
    cpu._pc = 0x1004
    cpu.step()
    return bytes((cpu.SR & 0x1F, cpu.R[0] & 0xFF))


def core_table() -> bytes:
    cpu = _cpu()
    out = bytearray()
    for opcode in (ABCD_D1_D0, SBCD_D1_D0):
        for source in range(256):
            for destination in range(256):
                for x in (0, 1):
                    for z in (0, 1):
                        out += _run(cpu, opcode, destination, source, x, z)
    for operand in range(256):
        for x in (0, 1):
            for z in (0, 1):
                out += _run(cpu, NBCD_D0, operand, 0, x, z)
    return bytes(out)


def _describe(index: int) -> str:
    case = index // 2
    if case < 2 * 262144:
        name = "ABCD" if case < 262144 else "SBCD"
        case %= 262144
        source, rest = divmod(case, 1024)
        destination, rest = divmod(rest, 4)
        return (
            f"{name} source={source:#04x} destination={destination:#04x} X={rest >> 1} Z={rest & 1}"
        )
    case -= 2 * 262144
    operand, rest = divmod(case, 4)
    return f"NBCD operand={operand:#04x} X={rest >> 1} Z={rest & 1}"


def test_every_bcd_input_matches_the_hardware_verified_table() -> None:
    table = core_table()
    assert len(table) == 1050624
    local = os.environ.get("M68000_BCD_TABLE")
    if local:
        expected = Path(local).read_bytes()
        for index, (got, want) in enumerate(zip(table, expected, strict=True)):
            assert got == want, f"{_describe(index)}: {got:#04x} != {want:#04x}"
    assert hashlib.sha256(table).hexdigest() == TABLE_SHA256
