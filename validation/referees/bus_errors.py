"""Bus errors: the core against WinUAE's tester core, over the gate's own states.

    python validation/referees/bus_errors.py                 # every gate file
    python validation/referees/bus_errors.py MOVE.w --show 3

No corpus models BERR.  This script makes one: for every case of the gate
corpus (SingleStepTests/m68000) that takes no exception, it picks one access
from the gate's own bus log -- the first data read, the first data write, or
the first program read -- and runs the case again with that word asserting
BERR, on this core and on WinUAE's CPU-tester core (whose bus-error region
is the tester's own "safe memory" mechanism).  Both are reduced to the
pre-exception view (referee.py) and compared: exception, registers, SR,
stacked PC, the frame's access information, access address and IR, and
memory.  Clocks are counted apart: the tester does not verify bus-error
cycle counts (cputest/readme.txt, 18.01.2020; WinUAE changelog 4.4.0).

Scope (docs/referees.md): WinUAE's author verified prefetch and data-read
bus errors on hardware with extra logic; write bus errors are claimed but
were not in the last re-verification, so a write disagreement is a question
(T3), not a verdict.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "src"), str(HERE.parents[1] / "tests")]

from corpus import read_m68000  # noqa: E402
from referee import (  # noqa: E402
    Driver,
    compare,
    outcome_of_case,
    outcome_of_winuae,
    run_core,
    setup_from_case,
)

GATE = HERE.parents[1] / "tests" / "68000_test_vectors" / "m68000" / "v1"
UNJUDGED = {"oob", "doublefault", "oddssp", "halted", "stopped"}
KINDS = {"read": 1, "write": 2, "program": 4}
#: Instructions whose first program read is a jump target computed from a
#: register or the stack, which may carry an upper address byte.  The
#: tester's program fetches check the bus-error region against the full 32
#: bits (winuae_referee.cpp can only re-check data accesses), so a target
#: whose upper byte is set would not fault there; these are left out of the
#: program-read sweep.
JUMPS = {"JMP", "JSR", "RTS", "RTE", "RTR"}


def targets(case) -> dict[str, int]:
    """The word address of the first data read, data write and program read."""
    found: dict[str, int] = {}
    for t in case.transactions:
        if t.kind == "r" and t.fc in (1, 5):
            found.setdefault("read", t.address & 0xFFFFFE)
        elif t.kind == "w":
            found.setdefault("write", t.address & 0xFFFFFE)
        elif t.kind == "r" and t.fc in (2, 6):
            found.setdefault("program", t.address & 0xFFFFFE)
    return found


def mode_of(name: str) -> str:
    return re.sub(r"A[0-7]", "An", re.sub(r"D[0-7]", "Dn", " ".join(name.split()[1:-1])))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*")
    parser.add_argument("--show", type=int, default=0)
    parser.add_argument("--dump", type=Path)
    args = parser.parse_args()
    paths = (
        [GATE / f"{stem}.json.bin" for stem in args.files]
        if args.files
        else sorted(GATE.glob("*.json.bin"))
    )
    driver = Driver("winuae")
    dump = args.dump.open("w") if args.dump else None
    totals: collections.Counter = collections.Counter()
    by_mode: collections.Counter = collections.Counter()
    started = time.perf_counter()
    for path in paths:
        stem = path.name.removesuffix(".json.bin")
        counts: collections.Counter = collections.Counter()
        jobs = []
        for case in read_m68000(path):
            pre, _ = outcome_of_case(case, False)
            if pre.exception:
                continue
            setup = setup_from_case(case, False)
            for kind, address in targets(case).items():
                if kind == "program" and stem in JUMPS:
                    continue  # the target may carry an upper byte (see JUMPS)
                jobs.append((case, setup, kind, (address, 2, KINDS[kind])))
        lines = []
        for index, (_, setup, _, region) in enumerate(jobs):
            lines.append("B {:x} {:x} {:x}".format(*region))
            lines.append(setup.line(str(index)))
        lines.append("B 0 0 0")
        shown = 0
        for (case, setup, kind, region), result in zip(jobs, driver.run(lines), strict=True):
            core, _, _ = run_core(setup, region)
            theirs = outcome_of_winuae(result, setup)
            counts[f"{kind} cases"] += 1
            if theirs.notes & UNJUDGED:
                counts[f"{kind} not judged"] += 1
                continue
            differences = compare(core, theirs, setup)
            clocks = "clocks" in differences
            differences = [d for d in differences if d != "clocks"]
            if clocks:
                counts[f"{kind} clocks differ (not judged)"] += 1
            if not differences:
                counts[f"{kind} agree"] += 1
                continue
            counts[f"{kind} disagree"] += 1
            key = (kind, stem, mode_of(case.name), tuple(differences))
            by_mode[key] += 1
            if dump is not None:
                dump.write(
                    json.dumps(
                        {
                            "case": case.name,
                            "kind": kind,
                            "differences": differences,
                            "core": core.registers,
                            "winuae": theirs.registers,
                            "core_frame": core.frame.hex(),
                            "winuae_frame": theirs.frame.hex(),
                            "core_exc": core.exception,
                            "winuae_exc": theirs.exception,
                        }
                    )
                    + "\n"
                )
            if shown < args.show:
                shown += 1
                print(f"  {kind} {case.name}: {differences}")
                for label, outcome in (("core:  ", core), ("winuae:", theirs)):
                    print(
                        f"    {label} exc={outcome.exception} pc={outcome.registers['pc']:x}"
                        f" frame={outcome.frame.hex()}"
                    )
        totals.update(counts)
        summary = ", ".join(
            f"{kind} {counts[f'{kind} agree']}/"
            f"{counts[f'{kind} cases'] - counts[f'{kind} not judged']}"
            for kind in KINDS
            if counts[f"{kind} cases"]
        )
        print(f"{stem:16} {summary}", flush=True)
    driver.close()
    print()
    for kind in KINDS:
        judged = totals[f"{kind} cases"] - totals[f"{kind} not judged"]
        print(
            f"TOTAL {kind}: {totals[f'{kind} agree']}/{judged} agree"
            f" ({totals[f'{kind} not judged']} not judged;"
            f" clocks differ in {totals[f'{kind} clocks differ (not judged)']})"
        )
    print("\nDisagreements by instruction form:")
    for (kind, stem, mode, differences), count in sorted(by_mode.items(), key=lambda kv: -kv[1]):
        print(f"{count:7}  {kind:8} {stem:12} {mode:32} {','.join(differences)}")
    print(f"{time.perf_counter() - started:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
