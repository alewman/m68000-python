"""Run one corpus case on the core and list every difference.

The host here is the corpus's: a sparse RAM of 16-bit words, every bus access
logged in the corpus's transaction shape (kind, address, size, the 16-bit
bus value, the two strobes, the function code).  An address error's aborted
access is logged through the core's ``address_error`` hook, as the corpus
logs it: kind ``re``/``we``, the address with A0 cleared.

What is compared, per case: D0-D7, A0-A6, USP, SSP, SR, the prefetch address
(``pc``), the prefetch pair, every RAM word the final state names, the clock
total, and the ordered list of bus accesses with kind, address, size, value,
strobes and function code.  The value of an aborted access is not compared:
no data moves when AS is not asserted, and the corpus's value there is
whatever MAME's data latch held.  Idle entries (``n``) are not compared one
by one; their sum is part of the clock total.
"""

from __future__ import annotations

from corpus import Case, State, Transaction

from m68000_python import M68000CPU
from m68000_python._core import S


class CorpusHost:
    """A sparse word memory that logs every access the way the corpus does."""

    def __init__(self, ram: dict[int, int]) -> None:
        self.memory = dict(ram)
        self.log: list[tuple] = []

    def read_word(self, address: int, fc: int = 0) -> int:
        value = self.memory.get(address, 0)
        self.log.append(("r", address, ".w", value, 1, 1, fc))
        return value

    def write_word(self, address: int, value: int, fc: int = 0) -> None:
        self.memory[address] = value
        self.log.append(("w", address, ".w", value, 1, 1, fc))

    def read_byte(self, address: int, fc: int = 0) -> int:
        word = self.memory.get(address & ~1, 0)
        if address & 1:
            self.log.append(("r", address & ~1, ".b", word & 0xFF, 0, 1, fc))
            return word & 0xFF
        self.log.append(("r", address, ".b", word & 0xFF00, 1, 0, fc))
        return word >> 8

    def write_byte(self, address: int, value: int, fc: int = 0) -> None:
        even = address & ~1
        word = self.memory.get(even, 0)
        if address & 1:
            self.memory[even] = (word & 0xFF00) | value
            self.log.append(("w", even, ".b", value, 0, 1, fc))
        else:
            self.memory[even] = (word & 0x00FF) | (value << 8)
            self.log.append(("w", even, ".b", value << 8, 1, 0, fc))

    def tas_write(self, address: int, value: int, fc: int = 0) -> None:
        self.write_byte(address, value, fc)
        _kind, *rest = self.log.pop()
        self.log.append(("t", *rest))

    def address_error(self, address: int, write: bool, fc: int) -> None:
        self.log.append(("we" if write else "re", address & ~1, ".w", None, 1, 1, fc))


def load(cpu: M68000CPU, state: State) -> None:
    registers = state.registers
    for index in range(8):
        cpu.R[index] = registers[f"d{index}"]
    for index in range(7):
        cpu.R[8 + index] = registers[f"a{index}"]
    cpu.SR = registers["sr"]
    if cpu.SR & S:
        cpu.R[15], cpu._other_sp = registers["ssp"], registers["usp"]
    else:
        cpu.R[15], cpu._other_sp = registers["usp"], registers["ssp"]
    cpu.ir, cpu.irc = state.prefetch
    cpu._pc = registers["pc"]


def registers_of(cpu: M68000CPU) -> dict[str, int]:
    values = {f"d{index}": cpu.R[index] for index in range(8)}
    values.update({f"a{index}": cpu.R[8 + index] for index in range(7)})
    values["usp"] = cpu.usp
    values["ssp"] = cpu.ssp
    values["sr"] = cpu.SR
    values["pc"] = cpu._pc
    return values


def expected_log(transactions: tuple[Transaction, ...]) -> list[tuple]:
    log = []
    for t in transactions:
        data = None if t.kind in ("re", "we") else t.data
        log.append((t.kind, t.address, t.size, data, t.uds, t.lds, t.fc))
    return log


def run_case(case: Case, *, compare_transactions: bool = True) -> tuple[list[str], int]:
    """Run ``case``; return (differences, clocks)."""
    host = CorpusHost(case.initial.ram)
    cpu = M68000CPU(
        host.read_byte,
        host.read_word,
        host.write_byte,
        host.write_word,
        function_codes=True,
        tas_write=host.tas_write,
        address_error=host.address_error,
    )
    load(cpu, case.initial)
    host.log.clear()
    cycles = cpu.step()
    differences = []
    actual = registers_of(cpu)
    for name, value in case.final.registers.items():
        if actual[name] != value:
            differences.append(f"{name}: {actual[name]:#x} != {value:#x}")
    if (cpu.ir, cpu.irc) != tuple(case.final.prefetch):
        differences.append(
            f"prefetch: [{cpu.ir:#06x}, {cpu.irc:#06x}] != "
            f"[{case.final.prefetch[0]:#06x}, {case.final.prefetch[1]:#06x}]"
        )
    for address, value in case.final.ram.items():
        got = host.memory.get(address, 0)
        if got != value:
            differences.append(f"ram[{address:#08x}]: {got:#06x} != {value:#06x}")
    if cycles != case.cycles:
        differences.append(f"cycles: {cycles} != {case.cycles}")
    if compare_transactions:
        expected = expected_log(case.transactions)
        if host.log != expected:
            differences.append("transactions differ")
            differences.append("  got:      " + format_log(host.log))
            differences.append("  expected: " + format_log(expected))
    return differences, cycles


def format_log(log: list[tuple]) -> str:
    items = []
    for kind, address, size, data, _uds, _lds, fc in log:
        shown = "?" if data is None else f"{data:04x}"
        items.append(f"{kind}{size[1]}@{address:06x}={shown}/{fc}")
    return " ".join(items)
