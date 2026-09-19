"""The SingleStepTests/m68000 gate (T3, MAME 0.285 microcode-derived).

Every case of every file in ``GATED`` must match on registers, SR, USP, SSP,
the prefetch pair and address, RAM, the clock total, and the ordered bus
transactions (tests/harness.py says exactly what is compared).  The corpus
is pinned and fetched by scripts/fetch_test_vectors.py; without it these
tests skip.  docs/validation.md records which files are gated, and why any
case is excluded.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from corpus import read_m68000
from harness import run_case

VECTORS = Path(__file__).resolve().parent / "68000_test_vectors" / "m68000" / "v1"
REVISION = "64b253116a3de04aaac4346c43680960dc9b67e5"

#: Files that pass every case.  Rung 1 of docs/handoff-brief.md.
GATED = ["NOP", "MOVE.q", "Bcc", "RTS", "MOVE.w", "MOVE.b", "MOVE.l"]


def _available() -> bool:
    revision = VECTORS.parent / "REVISION"
    return revision.exists() and revision.read_text().strip() == REVISION


@pytest.mark.corpus
@pytest.mark.skipif(not _available(), reason="corpus not fetched (scripts/fetch_test_vectors.py)")
@pytest.mark.parametrize("stem", GATED)
def test_file(stem: str) -> None:
    cases = read_m68000(VECTORS / f"{stem}.json.bin")
    assert len(cases) == 2500
    failures = []
    for case in cases:
        differences, _ = run_case(case)
        if differences:
            failures.append((case.name, differences))
    assert not failures, f"{len(failures)} failed; first: {failures[0]}"
