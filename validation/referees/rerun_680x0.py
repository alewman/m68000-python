"""Re-derive the 680x0 disagreement table by running WinUAE on the cases.

    python validation/referees/rerun_680x0.py                # all 124 files
    python validation/referees/rerun_680x0.py DBcc JSR --jobs 1

Every case of SingleStepTests/680x0 (CLK's corpus) is run three ways: this
core, the corpus's recorded answer, and WinUAE's CPU-tester core.  Each is
reduced to the pre-exception view (referee.py).  For every case where the
core and CLK disagree, each field they disagree on is sorted by what WinUAE
says: the core's value, CLK's value, or neither.  The case is also given its
cause from scripts/classify_680x0.py, so the result can be read against the
rung 5 table in docs/validation.md -- but the table is not consulted here.

A field WinUAE's tester does not model (bus order, function codes of
accesses that do not fault, the per-access log) never enters the view: a
cause whose disagreement lies only there is reported as having no
pre-exception difference.  Fields where the core and CLK agree but WinUAE
does not are reported too ("WinUAE differs from both").
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")]

from classify_680x0 import causes  # noqa: E402
from corpus import read_680x0  # noqa: E402
from harness_680x0 import run_case_680x0  # noqa: E402
from referee import (  # noqa: E402
    FRAME0_FIELDS,
    REGISTER_NAMES,
    Driver,
    Outcome,
    Setup,
    outcome_of_case,
    outcome_of_winuae,
    run_core,
    setup_from_case,
)

VECTORS = ROOT / "tests" / "68000_test_vectors" / "680x0" / "68000" / "v1"
UNJUDGED = {"oob", "doublefault", "oddssp", "halted", "stopped"}


def fields_of(outcome: Outcome, setup: Setup, addresses: list[int]) -> dict[str, object]:
    """Every pre-exception field of an outcome, by name."""
    values: dict[str, object] = {"exception": outcome.exception}
    for name in (*REGISTER_NAMES, "usp", "ssp", "pc"):
        values[name] = outcome.registers[name] & 0xFFFFFFFF
    values["sr-system"] = outcome.registers["sr"] & 0xFF00
    values["ccr"] = outcome.registers["sr"] & 0x1F
    if outcome.exception in (2, 3):
        for name, start, end in FRAME0_FIELDS:
            if name not in ("sr", "pc"):
                values[f"frame-{name}"] = outcome.frame[start:end].hex()
    values["frame1-pc"] = outcome.frame1[2:6].hex()
    values["memory"] = tuple(outcome.writes.get(a, setup.byte(a)) for a in addresses)
    values["clocks"] = outcome.clocks
    return values


def rerun_file(path: Path) -> dict:
    stem = path.name.removesuffix(".json.gz")
    cases = read_680x0(path)
    setups = [setup_from_case(case, True) for case in cases]
    driver = Driver("winuae")
    results = list(driver.run(setup.line(str(i)) for i, setup in enumerate(setups)))
    driver.close()
    table: collections.Counter = collections.Counter()
    examples: dict[str, str] = {}
    for case, setup, result in zip(cases, setups, results, strict=True):
        clk, _ = outcome_of_case(case, True)
        core, _, cpu = run_core(setup)
        core_log = cpu.referee_log
        winuae = outcome_of_winuae(result, setup)
        addresses = sorted(set(clk.writes) | set(core.writes) | set(winuae.writes))
        f_clk = fields_of(clk, setup, addresses)
        f_core = fields_of(core, setup, addresses)
        judged = not (winuae.notes & UNJUDGED)
        f_uae = fields_of(winuae, setup, addresses) if judged else None
        if stem in ("RTE", "RTR") and judged and core.exception not in (2, 3):
            # The order of the stack reads: the tester's core logs its data
            # accesses (referee.py), the others their bus logs.
            f_clk["read-order"] = data_reads(t[:5] for t in clk_log(case))
            f_core["read-order"] = data_reads(core_log)
            f_uae["read-order"] = tuple(
                address + offset
                for kind, size, address in result["a"]
                if kind == "r"
                for offset in range(0, size, 2)
            )
        differences, _, ours, theirs = run_case_680x0(case)
        if not differences:
            table[("(core and CLK agree)", "cases")] += 1
            if not judged:
                reason = ",".join(sorted(winuae.notes & UNJUDGED))
                table[("(core and CLK agree)", f"not judged: {reason}")] += 1
            else:
                same = all(f_uae[k] == f_core[k] for k in f_core)
                table[("(core and CLK agree)", "WinUAE agrees" if same else "WinUAE differs")] += 1
                if not same:
                    diff = [k for k in f_core if f_uae[k] != f_core[k]]
                    key = f"(core and CLK agree): WinUAE differs on {','.join(diff)}"
                    table[(key, "cases")] += 1
                    examples.setdefault(key, case.name)
            continue
        for cause in causes(stem, case.name, differences, ours, theirs):
            table[(cause, "cases")] += 1
            fields = [k for k in f_core if f_core[k] != f_clk[k]]
            if not judged:
                reason = ",".join(sorted(winuae.notes & UNJUDGED))
                table[(cause, f"not judged: {reason}")] += 1
                continue
            both = {group(k) for k in f_core if f_core[k] == f_clk[k] != f_uae[k]}
            if not fields and not both:
                table[(cause, "no pre-exception difference")] += 1
                continue
            by_verdict: dict[str, set] = collections.defaultdict(set)
            for name in fields:
                by_verdict[verdict_of(f_uae, f_core, f_clk, name)].add(group(name))
            parts = [
                f"WinUAE = {verdict}: {','.join(sorted(by_verdict[verdict]))}"
                for verdict in ("core", "CLK", "neither")
                if verdict in by_verdict
            ]
            if not fields:
                parts.insert(0, "no pre-exception difference")
            if both:
                parts.append(f"WinUAE differs from both: {','.join(sorted(both))}")
            label = "; ".join(parts)
            table[(cause, label)] += 1
            examples.setdefault(f"{cause} | {label}", case.name)
    return {"file": stem, "table": [[list(k), v] for k, v in table.items()], "examples": examples}


def clk_log(case) -> list[tuple]:
    return [(t.kind, t.address, t.size, t.data, t.fc) for t in case.transactions]


def data_reads(log) -> tuple[int, ...]:
    """Word addresses of the data-space reads (FC 1 or 5) in a log, in order."""
    return tuple(
        address for kind, address, _size, _value, fc in log if kind == "r" and fc in (1, 5)
    )


def group(name: str) -> str:
    """Registers named as a class, so that the table stays short."""
    if name[0] in "da" and name[1:].isdigit():
        return name[0].upper() + "n"
    return name


def verdict_of(uae: dict, core: dict, clk: dict, name: str) -> str:
    if uae[name] == core[name]:
        return "core"
    if uae[name] == clk[name]:
        return "CLK"
    return "neither"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--json", type=Path, help="write the per-file tables as JSON")
    args = parser.parse_args()
    paths = (
        [VECTORS / f"{stem}.json.gz" for stem in args.files]
        if args.files
        else sorted(VECTORS.glob("*.json.gz"))
    )
    started = time.perf_counter()
    totals: collections.Counter = collections.Counter()
    files: dict[str, set] = collections.defaultdict(set)
    examples: dict[str, str] = {}
    outputs = []
    with ProcessPoolExecutor(args.jobs) as pool:
        for output in pool.map(rerun_file, paths):
            outputs.append(output)
            for (cause, what), count in output["table"]:
                totals[(cause, what)] += count
                files[cause].add(output["file"])
            for key, name in output["examples"].items():
                examples.setdefault(key, f"{output['file']} {name}")
            print(f"{output['file']:16} done", file=sys.stderr, flush=True)
    if args.json:
        args.json.write_text(json.dumps(outputs))
    by_cause: dict[str, list] = collections.defaultdict(list)
    for (cause, what), count in totals.items():
        by_cause[cause].append((what, count))
    for cause in sorted(by_cause, key=lambda c: -totals[(c, "cases")]):
        shown = sorted(files[cause])
        more = f" and {len(shown) - 5} more" if len(shown) > 5 else ""
        print(f"{totals[(cause, 'cases')]:9,}  {cause}  [{', '.join(shown[:5])}{more}]")
        for what, count in sorted(by_cause[cause], key=lambda item: -item[1]):
            if what != "cases":
                example = examples.get(f"{cause} | {what}", "")
                print(f"{'':11}{count:9,}  {what}  {example}")
    print(f"{time.perf_counter() - started:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
