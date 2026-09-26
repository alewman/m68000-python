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
from corpus import M68000_REVISION, read_m68000
from harness import run_case

VECTORS = Path(__file__).resolve().parent / "68000_test_vectors" / "m68000" / "v1"
REVISION = M68000_REVISION

#: Every file of the pinned corpus: 127 files of 2,500 cases (rung 3).  No
#: case is excluded (docs/validation.md).
GATED = sorted(path.name.removesuffix(".json.bin") for path in VECTORS.glob("*.json.bin"))


def _available() -> bool:
    revision = VECTORS.parent / "REVISION"
    return revision.exists() and revision.read_text().strip() == REVISION


def test_the_whole_corpus_is_gated() -> None:
    if not _available():
        pytest.skip("corpus not fetched (scripts/fetch_test_vectors.py)")
    assert len(GATED) == 127


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
