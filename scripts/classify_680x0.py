"""Sort every SingleStepTests/680x0 disagreement into a named cause (rung 5).

    python scripts/classify_680x0.py            # all 124 files, a table of causes

Each cause is a rule over what differs; docs/validation.md ("Rung 5") says
which source explains it and at what tier.  A case matching no rule is
printed in full: nothing is skipped silently.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from corpus import read_680x0  # noqa: E402
from harness_680x0 import run_case_680x0  # noqa: E402

VECTORS = ROOT / "tests" / "68000_test_vectors" / "680x0" / "68000" / "v1"
FRAME = ("pc_low", "sr", "pc_high", "ir", "address_low", "information", "address_high")


def address_error(log: list[tuple]) -> int | None:
    """Index of the vector-3 fetch in an access log, or None."""
    for index, entry in enumerate(log):
        if entry[0] == "r" and entry[1] == 0x0C:
            return index
    return None


def causes(stem: str, name: str, differences: list[str], ours: list, theirs: list) -> list[str]:
    fields = {line.split(":")[0].split("[")[0] for line in differences}
    found = []
    ours_ae, theirs_ae = address_error(ours), address_error(theirs)
    if ours_ae is not None and theirs_ae is not None:
        if "cycles" in fields:
            found.append("address error: +8 clocks (aborted cycle counted)")
        frame_ours = ours[ours_ae - 7 : ours_ae]
        frame_theirs = theirs[theirs_ae - 7 : theirs_ae]
        slots = {s for s, a, b in zip(FRAME, frame_ours, frame_theirs, strict=True) if a != b}
        if slots & {"pc_low", "pc_high"}:
            target = any(e[0] == "r" and e[4] in (2, 6) and e[1] & 1 for e in theirs)
            found.append("address error: stacked PC" + (" (odd jump target)" if target else ""))
        if "information" in slots and not slots & {"pc_low", "pc_high"}:
            found.append("address error: FC of a PC-relative access")
        if "ir" in slots:
            found.append("address error: IR word")
        if ours[: ours_ae - 7] != theirs[: theirs_ae - 7]:
            found.append("address error: accesses before the fault")
        registers = {f for f in fields if f[:1] in "ad" and f[1:].isdigit()}
        if registers:
            found.append("address error: register moved or not")
        if "sr" in fields:
            found.append("address error: halfway flags of a long")
        return found or ["address error: other"]
    if ours_ae is not None or theirs_ae is not None:
        return ["address error on one side only"]
    if stem == "ASL.b" and name.endswith((" 1583", " 1761")):
        return ["corpus issue #4 (ASL.b 1583, 1761)"]
    if stem.startswith("ASR") and fields == {"sr"}:
        return ["ASR by a register count: X and C"]
    if stem == "TAS":
        return ["TAS logged as one read-modify-write access"]
    if stem in ("RTE", "RTR"):
        return ["RTE/RTR: order of the stack reads"]
    if stem == "LINK":
        return ["LINK A7: value pushed"]
    if stem == "CHK":
        found = []
        if "transactions" in fields:
            found.append("CHK trap: queue refill before the frame")
        if "sr" in fields:
            found.append("CHK: undefined flags")
        if "cycles" in fields and "transactions" not in fields:
            found.append("CHK: clocks")
        return found
    if stem in ("DIVU", "DIVS"):
        found = []
        if "sr" in fields:
            found.append(f"{stem}: flags")
        if "cycles" in fields:
            found.append(f"{stem}: clocks")
        if "transactions" in fields:
            found.append("PC-relative operand: function code")
        return found
    if fields == {"cycles"} and stem in ("ADD.l", "SUB.l"):
        return ["ADDQ/SUBQ.L to An: clocks"]
    if fields == {"transactions"}:
        pairs = [(a, b) for a, b in zip(ours, theirs, strict=False) if a != b]
        if len(ours) == len(theirs) and all(a[:4] == b[:4] for a, b in pairs):
            return ["PC-relative operand: function code"]
    return ["UNCLASSIFIED"]


def main() -> int:
    table: collections.Counter = collections.Counter()
    files: dict[str, set] = collections.defaultdict(set)
    total = agreed = 0
    for path in sorted(VECTORS.glob("*.json.gz")):
        stem = path.name.removesuffix(".json.gz")
        for case in read_680x0(path):
            total += 1
            differences, _, ours, theirs = run_case_680x0(case)
            if not differences:
                agreed += 1
                continue
            for cause in causes(stem, case.name, differences, ours, theirs):
                table[cause] += 1
                files[cause].add(stem)
                if cause == "UNCLASSIFIED":
                    print(stem, case.name, differences, ours, theirs, sep="\n  ")
        print(f"{stem:16} done", file=sys.stderr, flush=True)
    print(f"{agreed:,} of {total:,} cases agree; causes of the rest (a case may have several):")
    for cause, count in table.most_common():
        shown = sorted(files[cause])
        more = f" and {len(shown) - 6} more" if len(shown) > 6 else ""
        print(f"{count:9,}  {cause}  [{', '.join(shown[:6])}{more}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
