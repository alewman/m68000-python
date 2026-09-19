"""Readers for the two SingleStepTests 68000 corpora.

``read_m68000(path)`` parses a SingleStepTests/m68000 ``*.json.bin`` file
directly (the container is described in docs/validation.md, "Record shape");
``read_680x0(path)`` adapts a SingleStepTests/680x0 ``*.json.gz`` file to the
same :class:`Case` shape.  Both corpora are fetched by
scripts/fetch_test_vectors.py and are never committed.

The m68000 corpus's conventions, kept here rather than converted away:

* ``pc`` is MAME's ``m_au``, the address the next prefetch will come from:
  the executing instruction's address + 4.  :attr:`State.pc` keeps that value
  and :attr:`State.instruction_address` gives the instruction's own address.
* ``ram`` is a list of 16-bit words at even addresses.
* A transaction's ``data`` for a byte access is the whole 16-bit bus, with the
  byte in the half its strobe selects (``0xAB00`` for an upper-byte access).
"""

from __future__ import annotations

import gzip
import json
import struct
from dataclasses import dataclass
from pathlib import Path

FILE_MAGIC = 0x1A3F5D71
TEST_MAGIC = 0xABC12367
NAME_MAGIC = 0x89ABCDEF
STATE_MAGIC = 0x01234567
TRANSACTIONS_MAGIC = 0x456789AB

REGISTERS = ("d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7",
             "a0", "a1", "a2", "a3", "a4", "a5", "a6", "usp", "ssp", "sr", "pc")  # fmt: skip

#: Transaction kinds in the binary container (docs/validation.md).
KIND_IDLE, KIND_WRITE, KIND_READ, KIND_TAS, KIND_READ_ERROR, KIND_WRITE_ERROR = range(6)
KIND_NAMES = {1: "w", 2: "r", 3: "t", 4: "re", 5: "we"}


@dataclass(frozen=True, slots=True)
class State:
    """One side of a case: registers, SR, the prefetch pair, and RAM words."""

    registers: dict[str, int]
    prefetch: tuple[int, int]
    ram: dict[int, int]  # even address -> 16-bit word (m68000) or byte address -> byte (680x0)

    @property
    def pc(self) -> int:
        return self.registers["pc"]


@dataclass(frozen=True, slots=True)
class Transaction:
    """One bus access: kind ("r", "w", "t", "re", "we"), address, size, data."""

    kind: str
    cycles: int
    fc: int
    address: int
    size: str  # ".b" or ".w"
    data: int
    uds: int
    lds: int


@dataclass(frozen=True, slots=True)
class Case:
    name: str
    initial: State
    final: State
    cycles: int
    transactions: tuple[Transaction, ...]
    #: Idle entries ("n", cycles) interleaved with the accesses, for reading only.
    idle: tuple[tuple[int, int], ...] = ()


def _state(buffer: bytes, offset: int) -> tuple[State, int]:
    size, magic = struct.unpack_from("<II", buffer, offset)
    if magic != STATE_MAGIC:
        raise ValueError(f"bad state magic at {offset:#x}")
    values = struct.unpack_from("<19I", buffer, offset + 8)
    prefetch = struct.unpack_from("<2I", buffer, offset + 8 + 76)
    (count,) = struct.unpack_from("<I", buffer, offset + 8 + 84)
    ram: dict[int, int] = {}
    position = offset + 8 + 88
    for _ in range(count):
        address, word = struct.unpack_from("<IH", buffer, position)
        ram[address] = word
        position += 6
    if position != offset + size:
        raise ValueError(f"state length mismatch at {offset:#x}")
    return State(dict(zip(REGISTERS, values, strict=True)), prefetch, ram), position


def _transactions(buffer: bytes, offset: int) -> tuple[int, tuple, tuple, int]:
    size, magic, cycles, count = struct.unpack_from("<IIII", buffer, offset)
    if magic != TRANSACTIONS_MAGIC:
        raise ValueError(f"bad transactions magic at {offset:#x}")
    position = offset + 16
    accesses = []
    idle = []
    for index in range(count):
        kind, length = struct.unpack_from("<BI", buffer, position)
        position += 5
        if kind == KIND_IDLE:
            idle.append((index, length))
            continue
        fc, address, data, uds, lds = struct.unpack_from("<5I", buffer, position)
        position += 20
        width = ".w" if uds and lds else ".b"
        accesses.append(Transaction(KIND_NAMES[kind], length, fc, address, width, data, uds, lds))
    if position != offset + size:
        raise ValueError(f"transaction length mismatch at {offset:#x}")
    return cycles, tuple(accesses), tuple(idle), position


def read_m68000(path: str | Path) -> list[Case]:
    """Parse one SingleStepTests/m68000 ``*.json.bin`` file."""
    buffer = Path(path).read_bytes()
    magic, count = struct.unpack_from("<II", buffer, 0)
    if magic != FILE_MAGIC:
        raise ValueError(f"{path}: not a SingleStepTests/m68000 file")
    offset = 8
    cases = []
    for _ in range(count):
        size, magic = struct.unpack_from("<II", buffer, offset)
        if magic != TEST_MAGIC:
            raise ValueError(f"{path}: bad test magic at {offset:#x}")
        end = offset + size
        _, magic, length = struct.unpack_from("<III", buffer, offset + 8)
        if magic != NAME_MAGIC:
            raise ValueError(f"{path}: bad name magic at {offset:#x}")
        name = buffer[offset + 20 : offset + 20 + length].decode("utf-8")
        position = offset + 20 + length
        initial, position = _state(buffer, position)
        final, position = _state(buffer, position)
        cycles, accesses, idle, position = _transactions(buffer, position)
        if position != end:
            raise ValueError(f"{path}: test length mismatch at {offset:#x}")
        cases.append(Case(name, initial, final, cycles, accesses, idle))
        offset = end
    return cases


# -- SingleStepTests/680x0 (Tom Harte): detector only, no license file -------


def _harte_state(record: dict) -> State:
    registers = {name: record[name] for name in REGISTERS}
    ram = dict(record["ram"])
    return State(registers, tuple(record["prefetch"]), ram)


def read_680x0(path: str | Path) -> list[Case]:
    """Adapt one SingleStepTests/680x0 ``*.json.gz`` file to :class:`Case`.

    Differences from the m68000 corpus, normalised here: ``pc`` is the
    instruction's own address (converted to +4 so both corpora mean the same
    thing), ``ram`` is byte-addressed (kept byte-addressed; see
    :attr:`Case.name`), and transactions carry no strobes and a byte-sized
    ``data`` (the strobes are rebuilt from the address).
    """
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        records = json.load(handle)
    cases = []
    for record in records:
        initial = _harte_state(record["initial"])
        final = _harte_state(record["final"])
        initial.registers["pc"] += 4
        final.registers["pc"] += 4
        accesses = []
        idle = []
        for index, entry in enumerate(record.get("transactions", ())):
            if entry[0] == "n":
                idle.append((index, entry[1]))
                continue
            kind, length, fc, address, size, data = entry[:6]
            if size == ".b":
                uds, lds = (0, 1) if address & 1 else (1, 0)
                data = (data & 0xFF) if address & 1 else (data & 0xFF) << 8
            else:
                uds = lds = 1
            accesses.append(Transaction(kind, length, fc, address, size, data, uds, lds))
        cases.append(
            Case(record["name"], initial, final, record["length"], tuple(accesses), tuple(idle))
        )
    return cases
