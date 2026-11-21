# SPDX-License-Identifier: MIT
"""Fit the DIVU/DIVS clock rule to SingleStepTests/m68000 and check the core's.

    python scripts/fit_divide_clocks.py          # fit, then check _alu.py's functions

How ``divide_unsigned_clocks`` and ``divide_signed_clocks`` in
``src/m68000_python/_alu.py`` were derived (2026-11-19, provenance rewrite;
docs/provenance.md).  Only permitted sources: the corpus (MIT) and the
manual's maxima (UM Table 8-4).  No other program's divide code was read.

1. **Targets.**  Every DIVU/DIVS case is run through the core with both clock
   functions replaced by one that records its arguments and returns 0; the
   corpus's cycle count minus the core's is then exactly what the function
   must return for that case.  Cases that fault before dividing (address
   errors) never call it and are skipped.
2. **DIVU.**  Hypothesis: a 16-step shift-and-subtract (restoring) division
   of the dividend by the divisor, each step in one of three classes -- the
   remainder's top bit was set before the shift (the subtraction cannot
   fail), the subtraction succeeds, it fails -- each class with a cost, plus
   a constant.  Searched: every cost 0-12 per class for the first 15 steps,
   the last step either classed or fixed.  Overflow (high word not below the
   divisor) is detected before any step and takes a constant.
3. **DIVS.**  Hypothesis: the same division on magnitudes (a magnitude's
   remainder never has its top bit set), a cost per 0 quotient bit over a
   window of bits, and a constant per sign combination and overflow kind.

The search prints the best fits.  For DIVS two windows fit every case:
quotient bits 15-1 with four constants (the late overflow costs nothing
extra) and bits 14-1 with eight (it does); the shipped rule takes the first,
the simpler, and the two differ only for a quotient of exactly -32768, which
the corpus lacks.  Then the shipped functions are checked
against every case.  Result at the pinned corpus: 3,064 cases divide, and
the shipped rule leaves 0 of them unexplained.
"""

from __future__ import annotations

import collections
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from corpus import read_m68000  # noqa: E402
from harness import run_case  # noqa: E402

from m68000_python import _alu  # noqa: E402

VECTORS = ROOT / "tests" / "68000_test_vectors" / "m68000" / "v1"


def targets() -> list[tuple[str, int, int, int]]:
    """(stem, dividend, divisor, clocks the function must return) per dividing case."""
    shipped = _alu.divide_unsigned_clocks, _alu.divide_signed_clocks
    seen: list[tuple[int, int]] = []

    def record(dividend: int, divisor: int) -> int:
        seen.append((dividend, divisor))
        return 0

    _alu.divide_unsigned_clocks = _alu.divide_signed_clocks = record
    rows = []
    try:
        for stem in ("DIVU", "DIVS"):
            for case in read_m68000(VECTORS / f"{stem}.json.bin"):
                seen.clear()
                _, cycles = run_case(case)
                if seen:
                    ((dividend, divisor),) = seen
                    rows.append((stem, dividend, divisor, case.cycles - cycles))
    finally:
        _alu.divide_unsigned_clocks, _alu.divide_signed_clocks = shipped
    return rows


def unsigned_step_classes(dividend: int, divisor: int) -> list[int]:
    """Per step: 0 top bit set before the shift, 1 subtraction succeeds, 2 it fails."""
    remainder, low = dividend >> 16, dividend & 0xFFFF
    classes = []
    for _ in range(16):
        carry = remainder & 0x8000
        remainder = (remainder << 1) | (low >> 15)
        low = (low << 1) & 0xFFFF
        if carry or remainder >= divisor:
            remainder -= divisor
            classes.append(0 if carry else 1)
        else:
            classes.append(2)
    return classes


def fit_divu(rows: list[tuple[str, int, int, int]]) -> None:
    cases = [(d, s, t) for stem, d, s, t in rows if stem == "DIVU"]
    overflow = collections.Counter(t for d, s, t in cases if (d >> 16) >= s)
    print(f"DIVU: {len(cases)} cases divide; overflow clocks {dict(overflow)}")
    features = []
    for d, s, t in cases:
        if (d >> 16) >= s:
            continue
        classes = unsigned_step_classes(d, s)
        features.append(([classes[:15].count(k) for k in range(3)], classes[15], t))
    fits = []
    for costs in itertools.product(range(13), repeat=3):
        for last_fixed in (True, False):
            residues = collections.Counter()
            for counts, last, t in features:
                clocks = sum(n * c for n, c in zip(counts, costs, strict=True))
                if not last_fixed:
                    clocks += costs[last]
                residues[t - clocks] += 1
            constant, hits = residues.most_common(1)[0]
            fits.append((hits, costs, last_fixed, constant))
    fits.sort(key=lambda fit: (-fit[0], fit[1]))
    for hits, costs, last_fixed, constant in fits[:3]:
        print(
            f"  {hits}/{len(features)}: constant {constant}, step costs {costs}"
            f" (top bit set, subtract ok, subtract fails), last step "
            f"{'fixed' if last_fixed else 'classed'}"
        )


def fit_divs(rows: list[tuple[str, int, int, int]]) -> None:
    cases = [(d, s, t) for stem, d, s, t in rows if stem == "DIVS"]
    early = collections.Counter((d < 0, t) for d, s, t in cases if (abs(d) >> 16) >= abs(s))
    print(f"DIVS: {len(cases)} cases divide; early overflow (dividend<0, clocks) {dict(early)}")
    late = [(d, s, t) for d, s, t in cases if (abs(d) >> 16) < abs(s)]
    fits = []
    for low_bit, high_bit, cost in itertools.product(range(3), range(14, 17), (1, 2, 3, 4)):
        groups: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
        for d, s, t in late:
            quotient = abs(d) // abs(s)
            zeros = sum(1 for bit in range(low_bit, high_bit) if not (quotient >> bit) & 1)
            in_range = -0x8000 <= (quotient if (d < 0) == (s < 0) else -quotient) <= 0x7FFF
            groups[(d < 0, s < 0, not in_range)][t - cost * zeros] += 1
        hits = sum(counter.most_common(1)[0][1] for counter in groups.values())
        constants = {key: counter.most_common(1)[0][0] for key, counter in sorted(groups.items())}
        fits.append((hits, low_bit, high_bit, cost, constants))
    fits.sort(key=lambda fit: (-fit[0], fit[1]))
    for hits, low_bit, high_bit, cost, constants in fits[:2]:
        print(
            f"  {hits}/{len(late)}: {cost} per 0 among quotient bits {high_bit - 1}-{low_bit};"
            f" constants by (dividend<0, divisor<0, late overflow): {constants}"
        )


def check(rows: list[tuple[str, int, int, int]]) -> int:
    functions = {"DIVU": _alu.divide_unsigned_clocks, "DIVS": _alu.divide_signed_clocks}
    misses = [row for row in rows if functions[row[0]](row[1], row[2]) != row[3]]
    print(f"shipped rule: {len(rows) - len(misses)}/{len(rows)} cases explained")
    for row in misses[:10]:
        print("  miss", row)
    return 1 if misses else 0


def main() -> int:
    rows = targets()
    fit_divu(rows)
    fit_divs(rows)
    return check(rows)


if __name__ == "__main__":
    raise SystemExit(main())
