"""Run SingleStepTests/680x0 against the core as a detector (rung 5) and sort the results.

    python scripts/run_680x0.py                  # every file
    python scripts/run_680x0.py ASL.b --show 3   # one file, print 3 disagreements

The corpus is fetched with ``python scripts/fetch_test_vectors.py --with-680x0``
(no license file: never committed).  Each disagreement is sorted by what
differs and by whether the core took an address error; docs/validation.md
explains every category by a higher-tier source or the corpus's own issues.
"""

from __future__ import annotations

import argparse
import collections
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from corpus import read_680x0  # noqa: E402
from harness_680x0 import run_case_680x0  # noqa: E402

VECTORS = ROOT / "tests" / "68000_test_vectors" / "680x0" / "68000" / "v1"


def category(differences: list[str], ours: list[tuple]) -> str:
    kinds = sorted({line.split(":")[0].split("[")[0] for line in differences})
    address_error = any(entry[1] in (0x0C, 0x0E) and entry[0] == "r" for entry in ours)
    return ("address-error " if address_error else "") + "+".join(kinds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*")
    parser.add_argument("--show", type=int, default=0)
    args = parser.parse_args()
    paths = (
        [VECTORS / f"{stem}.json.gz" for stem in args.files]
        if args.files
        else sorted(VECTORS.glob("*.json.gz"))
    )
    total = agreed = 0
    summary: collections.Counter = collections.Counter()
    for path in paths:
        started = time.perf_counter()
        cases = read_680x0(path)
        counts: collections.Counter = collections.Counter()
        shown = 0
        for case in cases:
            differences, _, ours, theirs = run_case_680x0(case)
            total += 1
            if not differences:
                agreed += 1
                continue
            key = category(differences, ours)
            counts[key] += 1
            if shown < args.show:
                shown += 1
                print(f"  {case.name}: {differences}")
                print(f"    ours:   {ours}")
                print(f"    theirs: {theirs}")
        name = path.name.removesuffix(".json.gz")
        disagreed = sum(counts.values())
        detail = ", ".join(f"{k} {v}" for k, v in counts.most_common())
        elapsed = time.perf_counter() - started
        agreed_here = len(cases) - disagreed
        print(f"{name:16} {agreed_here:5}/{len(cases)}  {elapsed:5.1f}s  {detail}", flush=True)
        for key, value in counts.items():
            summary[(name, key)] += value
    print(f"TOTAL {agreed}/{total} agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
