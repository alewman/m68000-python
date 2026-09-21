"""Calibrate a referee against a corpus: how often it agrees, field by field, per file.

    python validation/referees/calibrate.py winuae                 # every gate file
    python validation/referees/calibrate.py musashi ADD.w --show 3
    python validation/referees/calibrate.py winuae --corpus 680x0  # the CLK corpus

A referee is compared only on what it models (docs/referees.md):

* winuae: the pre-exception view -- exception number, registers, SR, PC,
  the stack frame's fields, memory written, and the clock total (the
  tester's count plus its exception cost).  Cases the tester cannot
  represent (an access in the top 4 KB, an odd SSP at an exception, a
  double fault) are counted as not judged.
* musashi: the post view -- registers, SR, PC and memory after the step --
  for cases without an address error; clocks are reported apart, as a
  property of Musashi, not a judgement.

Against the gate (SingleStepTests/m68000) this is a calibration: a referee
that disagrees on ordinary cases points at the harness first.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "src"), str(HERE.parents[1] / "tests")]

from corpus import read_680x0, read_m68000  # noqa: E402
from referee import (  # noqa: E402
    Driver,
    Outcome,
    compare,
    outcome_of_case,
    outcome_of_musashi,
    outcome_of_winuae,
    setup_from_case,
)

VECTORS = HERE.parents[1] / "tests" / "68000_test_vectors"
CORPORA = {
    "m68000": (VECTORS / "m68000" / "v1", ".json.bin", read_m68000, False),
    "680x0": (VECTORS / "680x0" / "68000" / "v1", ".json.gz", read_680x0, True),
}
UNJUDGED = {"oob", "doublefault", "oddssp", "halted", "stopped"}


def calibrate_file(driver: Driver, referee: str, cases, byte_ram: bool, show: int, dump) -> dict:
    setups = [setup_from_case(case, byte_ram) for case in cases]
    lines = [setup.line(str(index)) for index, setup in enumerate(setups)]
    counts: collections.Counter = collections.Counter()
    shown = 0
    for case, setup, result in zip(cases, setups, driver.run(lines), strict=True):
        pre, post = outcome_of_case(case, byte_ram)
        counts["cases"] += 1
        if referee == "winuae":
            theirs = outcome_of_winuae(result, setup)
            if theirs.notes & UNJUDGED:
                counts["not judged"] += 1
                continue
            ours = pre
            differences = compare(ours, theirs, setup)
        else:
            if pre.exception in (2, 3):
                counts["not judged"] += 1  # address and bus errors: outside Musashi's model
                continue
            theirs = outcome_of_musashi(result)
            ours = post
            if "stopped" in theirs.notes:
                # A stopped CPU has made no closing prefetch: the corpus's pc
                # is the resume address itself, not the next prefetch.
                ours = Outcome(
                    ours.exception,
                    {**ours.registers, "pc": ours.registers["pc"] + 4},
                    writes=ours.writes,
                    clocks=ours.clocks,
                )
            differences = compare(ours, theirs, setup, fields=("registers", "memory"))
            if ours.clocks != theirs.clocks:
                counts["clocks (property)"] += 1
        counts["judged"] += 1
        if not differences:
            counts["agree"] += 1
            continue
        for name in differences:
            counts[name] += 1
        if dump is not None:
            dump.write(
                json.dumps(
                    {
                        "case": case.name,
                        "differences": differences,
                        "corpus": {
                            "exception": ours.exception,
                            "registers": ours.registers,
                            "frame": ours.frame.hex(),
                            "clocks": ours.clocks,
                        },
                        "referee": {
                            "exception": theirs.exception,
                            "registers": theirs.registers,
                            "frame": theirs.frame.hex(),
                            "clocks": theirs.clocks,
                            "notes": sorted(theirs.notes),
                        },
                    }
                )
                + "\n"
            )
        if shown < show:
            shown += 1
            print(f"  {case.name}: {differences}")
            print(f"    corpus:  {describe(ours)}")
            print(f"    referee: {describe(theirs)}")
    return counts


def describe(outcome: Outcome) -> str:
    registers = " ".join(
        f"{k}={v:x}" for k, v in outcome.registers.items() if k in ("sr", "pc", "ssp", "usp")
    )
    return (
        f"exc={outcome.exception} {registers} frame={outcome.frame.hex()}"
        f" clk={outcome.clocks} {sorted(outcome.notes)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("referee", choices=["winuae", "musashi"])
    parser.add_argument("files", nargs="*")
    parser.add_argument("--corpus", choices=sorted(CORPORA), default="m68000")
    parser.add_argument("--limit", type=int, default=0, help="cases per file (0: all)")
    parser.add_argument("--show", type=int, default=0)
    parser.add_argument("--dump", type=Path, help="write every disagreement as JSON lines")
    args = parser.parse_args()
    directory, suffix, reader, byte_ram = CORPORA[args.corpus]
    paths = (
        [directory / f"{stem}{suffix}" for stem in args.files]
        if args.files
        else sorted(directory.glob(f"*{suffix}"))
    )
    driver = Driver(args.referee)
    dump = args.dump.open("w") if args.dump else None
    totals: collections.Counter = collections.Counter()
    started = time.perf_counter()
    for path in paths:
        cases = reader(path)
        if args.limit:
            cases = cases[: args.limit]
        counts = calibrate_file(driver, args.referee, cases, byte_ram, args.show, dump)
        totals.update(counts)
        name = path.name.removesuffix(suffix)
        detail = ", ".join(
            f"{k} {v}"
            for k, v in counts.most_common()
            if k not in ("cases", "judged", "agree", "not judged")
        )
        print(
            f"{name:16} {counts['agree']:6}/{counts['judged']:<6} judged of {counts['cases']:6}"
            f"  {detail}",
            flush=True,
        )
    driver.close()
    elapsed = time.perf_counter() - started
    detail = ", ".join(
        f"{k} {v}" for k, v in totals.most_common() if k not in ("cases", "judged", "agree")
    )
    print(
        f"TOTAL {args.referee} vs {args.corpus}: "
        f"{totals['agree']}/{totals['judged']} judged cases agree"
        f" ({totals['cases']} cases, {totals['not judged']} not judged); {detail}; {elapsed:.0f} s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
