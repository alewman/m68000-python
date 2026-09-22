"""``M68000CPU.step_clocks``: where in a step each bus access falls.

A board host needs the clock at which each access happens inside an
instruction, to stall the CPU at the right point (a Mega Drive's VDP FIFO,
its bus arbiter).  The corpus records every transaction's length and the idle
clocks between them, so the end of each access is known; ``step_clocks`` read
inside the callback must equal it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from corpus import read_m68000
from harness import CorpusHost, load

from m68000_python import M68000CPU

VECTORS = Path(__file__).resolve().parent / "68000_test_vectors" / "m68000" / "v1"
REVISION = "64b253116a3de04aaac4346c43680960dc9b67e5"
#: Every file of the pinned corpus, as in tests/test_corpus.py.
GATED = sorted(path.name.removesuffix(".json.bin") for path in VECTORS.glob("*.json.bin"))


def _available() -> bool:
    revision = VECTORS.parent / "REVISION"
    return revision.exists() and revision.read_text().strip() == REVISION


class ClockedHost(CorpusHost):
    """The corpus host, noting ``step_clocks`` at every read and write."""

    cpu: M68000CPU

    def __init__(self, ram: dict[int, int]) -> None:
        super().__init__(ram)
        self.clocks: list[int] = []

    def read_word(self, address: int, fc: int = 0) -> int:
        self.clocks.append(self.cpu.step_clocks)
        return super().read_word(address, fc)

    def read_byte(self, address: int, fc: int = 0) -> int:
        self.clocks.append(self.cpu.step_clocks)
        return super().read_byte(address, fc)

    def write_word(self, address: int, value: int, fc: int = 0) -> None:
        self.clocks.append(self.cpu.step_clocks)
        super().write_word(address, value, fc)

    def write_byte(self, address: int, value: int, fc: int = 0) -> None:
        self.clocks.append(self.cpu.step_clocks)
        super().write_byte(address, value, fc)


def _cpu(host: ClockedHost) -> M68000CPU:
    cpu = M68000CPU(
        host.read_byte,
        host.read_word,
        host.write_byte,
        host.write_word,
        function_codes=True,
        tas_write=host.tas_write,
        address_error=host.address_error,
    )
    host.cpu = cpu
    return cpu


def test_nop_prefetches_at_the_end_of_its_four_clocks() -> None:
    host = ClockedHost({0x1000: 0x4E71, 0x1002: 0x4E71, 0x1004: 0x4E71})
    cpu = _cpu(host)
    cpu.ir, cpu.irc, cpu._pc = 0x4E71, 0x4E71, 0x1004
    assert cpu.step() == 4
    assert host.clocks == [4]
    assert cpu.step_clocks == 4


def test_a_halted_step_reports_its_four_clocks() -> None:
    cpu = _cpu(ClockedHost({}))
    cpu.halted = True
    assert cpu.step() == 4
    assert cpu.step_clocks == 4


def _access_ends(case) -> list[int]:
    """The clock at which each non-faulting access ends, from the corpus."""
    idle = dict(case.idle)
    accesses = iter(case.transactions)
    ends, now = [], 0
    for position in range(len(case.transactions) + len(case.idle)):
        if position in idle:
            now += idle[position]
            continue
        access = next(accesses)
        now += access.cycles
        if access.kind not in ("re", "we"):
            ends.append(now)
    return ends


@pytest.mark.corpus
@pytest.mark.skipif(not _available(), reason="corpus not fetched (scripts/fetch_test_vectors.py)")
@pytest.mark.parametrize("stem", GATED)
def test_step_clocks_match_the_corpus_access_timing(stem: str) -> None:
    cases = read_m68000(VECTORS / f"{stem}.json.bin")
    checked = 0
    for case in cases:
        if any(t.kind in ("re", "we") for t in case.transactions):
            continue  # an aborted access never reaches the host's callbacks
        host = ClockedHost(case.initial.ram)
        cpu = _cpu(host)
        load(cpu, case.initial)
        total = cpu.step()
        assert host.clocks == _access_ends(case), case.name
        assert cpu.step_clocks == total == case.cycles, case.name
        checked += 1
    assert checked, stem
