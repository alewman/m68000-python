"""Read a MAME 0.285 ``error.log`` lockstep trace (docs/mame-oracle.md).

Two kinds of line come out of the Lua script in ``lockstep.lua``:

* an instruction line, written by the debugger's ``trace`` action *before*
  the instruction runs: ``curpc sr d0 .. d7 a0 .. a6 usp sp`` in hex, where
  ``sp`` is MAME's supervisor stack pointer slot and ``usp`` the user one;
* ``M register value``, written when System 16B's i8751 writes one of the
  315-5195 mapper's first sixteen registers.  The reader keeps a copy of
  them, because writing 1 or 2 to register 5 makes the mapper write or read
  one word of the 68000's bus on the i8751's behalf (sega/315_5195.cpp):
  that access, if it falls in a watched window, is logged next, and is
  dropped here because the CPU did not make it;
* a read line, ``R address bits value``, written by a watchpoint when the
  instruction running reads a watched (device) address; a write line,
  ``W address bits value``, likewise for a watched write.

:func:`records` yields ``(registers, accesses)`` pairs: the state before an
instruction and the watched accesses it made, in order, each tagged ``R``
or ``W``.  Lines of any other shape (the driver's own log messages) are
skipped.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

FIELDS = ("pc", "sr", "d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7",
          "a0", "a1", "a2", "a3", "a4", "a5", "a6", "usp", "ssp")  # fmt: skip


@dataclass(frozen=True, slots=True)
class Access:
    kind: str  # "R" or "W"
    address: int
    bits: int
    value: int


def _hex_fields(line: str, count: int) -> list[int] | None:
    parts = line.split()
    if len(parts) != count:
        return None
    try:
        return [int(part, 16) for part in parts]
    except ValueError:
        return None


def records(path: str | Path) -> Iterator[tuple[dict[str, int], list[Access]]]:
    """Yield (state before the instruction, watched accesses it made), in order."""
    current: dict[str, int] | None = None
    reads: list[Access] = []
    mapper = [0] * 16
    foreign: tuple[str, int] | None = None  # the mapper's own access, expected next
    with open(path, encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.startswith("M "):
                values = _hex_fields(line[2:], 2)
                if values is not None:
                    register, value = values
                    mapper[register & 15] = value & 0xFF
                    if register == 5 and value == 1:
                        foreign = ("W", (mapper[10] << 17) | (mapper[11] << 9) | (mapper[12] << 1))
                    elif register == 5 and value == 2:
                        foreign = ("R", (mapper[7] << 17) | (mapper[8] << 9) | (mapper[9] << 1))
                continue
            if line.startswith(("R ", "W ")):
                values = _hex_fields(line[2:], 3)
                if values is None:
                    continue
                if foreign is not None and (line[0], values[0]) == foreign:
                    foreign = None  # the i8751's access through the mapper
                    continue
                if current is not None:
                    reads.append(Access(line[0], *values))
                continue
            foreign = None
            values = _hex_fields(line, len(FIELDS))
            if values is None:
                continue
            if current is not None:
                yield current, reads
            current = dict(zip(FIELDS, values, strict=True))
            reads = []
    if current is not None:
        yield current, reads
