# SPDX-License-Identifier: MIT
"""Which of the core's hidden-state rules does the gate pin?  Remove each, one at a time.

    python scripts/ablate_hidden_state.py            # every site, the summary table
    python scripts/ablate_hidden_state.py --jobs 4   # in parallel (each run is one process)
    python scripts/ablate_hidden_state.py --list     # the sites only

Written 2026-11-19 for the wave 2 provenance rewrite (docs/provenance.md).
The core keeps a few pieces of state that only an address error can see: the
PC value an address error stacks (``_fault_pc``, brought up to the fetch
address by ``_commit_pc``), the opcode the decoder holds (``_opcode``, which
an address error stacks as IR and copies into the access word), the halfway
flags of a long result (``_flags_low_word`` / ``_flags_high_word``), and the
order of a long write's two halves (``_write_long_low_first``).  Where each of
these steps sits was settled against SingleStepTests/m68000 (MIT), but the
2026-09 build also read MAME's header-less microcode files, which are GPL.
This script shows, site by site, that the MIT corpus alone pins each step:
every site is removed (or its two halves swapped) in a copy of the core, and
the copy is run over the whole corpus.  A site whose removal makes some case
fail is **pinned by the corpus**: the corpus alone forces the step to be
there.  A site whose removal passes every case is **not pinned** and must
rest on something else (a manual, a closed-box run) or go.

Result at the pinned corpus (2026-11-19, docs/provenance.md "Wave 2, second
pass"): of 43 sites, 37 pinned; the ABCD/SBCD ``-(An)`` and immediate
bit-number commits are seen only by a bus error and kept on WinUAE's tester
core run as a closed box (OBSERVED, validation/referees/bus_errors.py); the
two ``cpu.py`` boundary hand-overs are the core's own model; the MOVE.L
``-(An)`` and PEA hand-overs were pinned by nothing and were removed, leaving
41 sites.

Each mutant runs against a copy of ``src/m68000_python`` in a scratch
directory, never ``src/`` itself.  A run stops at the first failing case and
names it.  Nothing here reads any other program's source.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "m68000_python"

#: (pattern, replacement) applied to one matching line; the replacement keeps the
#: line's indentation.  ``None`` as the replacement deletes the statement (``pass``).
RULES: tuple[tuple[str, str | None], ...] = (
    (r"self\._commit_pc\(\)", None),
    (r"^\s*self\._opcode = self\.ir$", None),
    (r"self\._fault_pc = target", None),
    (r"self\._flags_low_word\(value\)", "self._flags_high_word(value)"),
    (r"self\._flags_high_word\(value\)", "self._flags_low_word(value)"),
    (r"self\._write_long_low_first\(", "self._write_long("),
)
#: Files whose sites are instruction steps (cpu.py's sites are trace and
#: interrupt entry, which the corpus never reaches: they are listed apart).
FILES = ("_alu.py", "_bcd.py", "_bits.py", "_control.py", "_ea.py", "_loads.py", "_shifts.py",
         "_system.py", "cpu.py")  # fmt: skip

CHILD = r"""
import sys
sys.path[:0] = [{copy!r}, {tests!r}]
import m68000_python
assert m68000_python.__file__.startswith({copy!r}), m68000_python.__file__
from pathlib import Path
from corpus import read_m68000
from harness import run_case
cases = 0
for path in sorted(Path({vectors!r}).glob("*.json.bin")):
    for case in read_m68000(path):
        cases += 1
        try:
            differences, _ = run_case(case)
        except Exception as error:
            differences = [type(error).__name__ + ": " + str(error)]
        if differences:
            print("FAIL", case.name, "|", differences[0])
            raise SystemExit(1)
print("PASS", cases)
"""


@dataclass(frozen=True)
class Site:
    file: str
    line: int  # 1-based
    text: str
    replacement: str | None

    @property
    def label(self) -> str:
        change = "removed" if self.replacement is None else f"-> {self.replacement}"
        return f"{self.file}:{self.line}  {self.text.strip()}  ({change})"


def sites() -> list[Site]:
    found = []
    for name in FILES:
        for number, text in enumerate((SOURCE / name).read_text().splitlines(), 1):
            code = text.split("#", 1)[0].rstrip()
            for pattern, replacement in RULES:
                if re.search(pattern, code):
                    found.append(Site(name, number, text, replacement))
                    break
    return found


def mutate(site: Site, copy: Path) -> None:
    path = copy / "m68000_python" / site.file
    lines = path.read_text().splitlines(keepends=True)
    original = lines[site.line - 1]
    indent = original[: len(original) - len(original.lstrip())]
    code = original.rstrip("\n").split("#", 1)[0]
    if site.replacement is None:
        # Keep the line's other effects: only the matched statement becomes `pass`
        # (``address = self._fault_pc = self._pc`` style lines are not sites).
        lines[site.line - 1] = indent + "pass\n"
    else:
        for pattern, replacement in RULES:
            if re.search(pattern, code) and replacement == site.replacement:
                code = re.sub(pattern, lambda _m, r=replacement: r, code, count=1)
                break
        lines[site.line - 1] = code.rstrip() + "\n"
    path.write_text("".join(lines))


def run(site: Site, python: str, vectors: Path) -> tuple[Site, str]:
    with tempfile.TemporaryDirectory(prefix="m68k-ablate-") as scratch:
        copy = Path(scratch)
        shutil.copytree(SOURCE, copy / "m68000_python")
        mutate(site, copy)
        script = CHILD.format(copy=str(copy), tests=str(ROOT / "tests"), vectors=str(vectors))
        result = subprocess.run([python, "-c", script], capture_output=True, text=True)
        out = (result.stdout.strip().splitlines() or [result.stderr.strip()[-300:]])[-1]
        return site, out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--python", default=sys.executable, help="interpreter for the runs")
    args = parser.parse_args()
    found = sites()
    if args.list:
        for site in found:
            print(site.label)
        return 0
    vectors = ROOT / "tests" / "68000_test_vectors" / "m68000" / "v1"
    before = SOURCE.joinpath("_core.py").read_bytes()
    pinned = unpinned = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for site, out in pool.map(lambda s: run(s, args.python, vectors), found):
            verdict = "pinned" if out.startswith("FAIL") else "NOT PINNED"
            pinned += verdict == "pinned"
            unpinned += verdict != "pinned"
            print(f"{verdict:10}  {site.label}\n            {out[:160]}", flush=True)
    assert SOURCE.joinpath("_core.py").read_bytes() == before
    print(f"{len(found)} sites: {pinned} pinned by the corpus, {unpinned} not pinned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
