"""Run SingleStepTests/m68000 files against the core and summarize.

    python scripts/run_corpus.py NOP MOVE.q          # named files
    python scripts/run_corpus.py --all               # all 127 files
    python scripts/run_corpus.py ADD.w --show 3      # print the first 3 failures

Prints one line per file: passed/total and the wall time.  The pytest gate
(tests/test_corpus.py) runs the same comparison; this script is for sweeps
and for reading failures.  Exit status 1 if any case failed.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from corpus import read_m68000  # noqa: E402
from harness import run_case  # noqa: E402

VECTORS = ROOT / "tests" / "68000_test_vectors" / "m68000" / "v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="file stems, e.g. MOVE.w")
    parser.add_argument("--all", action="store_true", help="every file in the corpus")
    parser.add_argument("--show", type=int, default=0, help="print this many failures per file")
    parser.add_argument("--match", default="", help="only cases whose name contains this")
    args = parser.parse_args()
    if args.all:
        paths = sorted(VECTORS.glob("*.json.bin"))
    else:
        paths = [VECTORS / f"{stem}.json.bin" for stem in args.files]
    total_failed = total_cases = 0
    for path in paths:
        started = time.perf_counter()
        cases = [case for case in read_m68000(path) if args.match in case.name]
        failed = 0
        shown = 0
        for case in cases:
            try:
                differences, _ = run_case(case)
            except Exception as error:  # a crash is a failure with a reason
                differences = [f"{type(error).__name__}: {error}"]
            if differences:
                failed += 1
                if shown < args.show:
                    shown += 1
                    print(f"  FAIL {case.name}")
                    for line in differences:
                        print(f"    {line}")
        elapsed = time.perf_counter() - started
        name = path.name.removesuffix(".json.bin")
        print(f"{name:16} {len(cases) - failed:5}/{len(cases)}  {elapsed:6.1f}s", flush=True)
        total_failed += failed
        total_cases += len(cases)
    print(f"TOTAL {total_cases - total_failed}/{total_cases}")
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
