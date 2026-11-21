# SPDX-License-Identifier: MIT
"""Check the opcode map against Musashi's 68000 decoder, word for word.

    python scripts/check_decoder_vs_musashi.py            # fetch Musashi if needed, build, compare
    python scripts/check_decoder_vs_musashi.py --show 20  # print up to 20 disagreements

Musashi (Karl Stenerud, MIT) is a hand-written 680x0 interpreter of its own
lineage.  Its disassembler answers, for any first word and CPU type, whether
the word is a valid instruction (``m68k_is_valid_instruction``) and what it
is (``m68k_disassemble``).  validation/referees/musashi_decoder.c prints both
for all 65,536 words with the 68000 selected; the Musashi tree is the one
build_referees.py fetches at its pin (never committed).  Then every word is
compared with ``_dispatch.NAMES``:

* the words Musashi calls valid must be the words the map defines, except the
  known difference below;
* for each such word, Musashi's mnemonic must belong to the family the map
  names (``bne`` to ``bcc``, ``asl`` to ``asd``, ``move`` from SR to
  ``move_from_sr`` ...);
* every $Axxx and $Fxxx word must be ``line_a`` / ``line_f`` (they trap
  whatever Musashi's table says of other CPUs' F-line instructions), and every
  word Musashi rejects that the map does not name ``illegal`` is reported.

Known difference, from the manual: Bcc, BRA and BSR with an 8-bit
displacement of $FF.  On the MC68020 and later $FF announces a 32-bit
displacement, and Musashi's validity table rejects these 16 words for the
68000 too; on the 68000 there is no 32-bit form and $FF is a displacement of
-1 (PRM 4-25 and 4-59, Bcc/BRA and BSR: the 32-bit displacement is for the
MC68020 and later only).  The map defines them; SingleStepTests/m68000 runs them.

This replaced, on 2026-11-19, a check against MAME's ``m68000.lst``, a file
with no licence header (so GPL-2.0+ under MAME's COPYING; docs/provenance.md).
Exit status 1 on any unexpected difference.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFEREES = ROOT / "validation" / "referees"
sys.path[:0] = [str(ROOT / "src"), str(REFEREES)]

from build_referees import MUSASHI_REPOSITORY, MUSASHI_REVISION, fetch  # noqa: E402

from m68000_python._dispatch import NAMES  # noqa: E402

CONDITIONS = "t f hi ls cc cs ne eq vc vs pl mi ge lt gt le".split()
#: Musashi mnemonic (size suffix dropped) -> the map's family, where they differ.
FAMILY = {
    **{"b" + c: "bcc" for c in CONDITIONS if c not in ("t", "f")},
    **{"db" + c: "dbcc" for c in CONDITIONS},
    "dbra": "dbcc",
    **{"s" + c: "scc" for c in CONDITIONS},
    "asl": "asd", "asr": "asd", "lsl": "lsd", "lsr": "lsd",
    "rol": "rod", "ror": "rod", "roxl": "roxd", "roxr": "roxd",
}  # fmt: skip
#: Map families that print under another mnemonic: the map's name -> Musashi's.
PRINTED_AS = {
    "andi_to_ccr": "andi", "andi_to_sr": "andi", "eori_to_ccr": "eori", "eori_to_sr": "eori",
    "ori_to_ccr": "ori", "ori_to_sr": "ori", "move_from_sr": "move", "move_to_ccr": "move",
    "move_to_sr": "move", "move_usp": "move", "asd_memory": "asd", "lsd_memory": "lsd",
    "rod_memory": "rod", "roxd_memory": "roxd",
}  # fmt: skip
TRAPS = ("illegal", "line_a", "line_f")


def musashi_table() -> list[tuple[bool, str]]:
    """(valid, mnemonic) for every first word, from Musashi built at its pin."""
    tree = fetch("musashi", MUSASHI_REPOSITORY, MUSASHI_REVISION)
    build = REFEREES / "build" / "musashi_decoder"
    build.mkdir(parents=True, exist_ok=True)
    binary = build / "musashi_decoder"
    source = REFEREES / "musashi_decoder.c"
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        subprocess.run(
            ["gcc", "-O1", "-w", f"-I{tree}", "-o", str(binary), str(source),
             str(tree / "m68kdasm.c")],
            check=True,
        )  # fmt: skip
    out = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout
    table = []
    for line in out.splitlines():
        _word, valid, text = line.split(None, 2)
        table.append((valid == "1", text.split()[0].split(".")[0]))
    assert len(table) == 0x10000
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", type=int, default=10, help="disagreements to print")
    args = parser.parse_args()
    table = musashi_table()
    unexpected: list[str] = []
    known = agree = traps = 0
    for word, (valid, mnemonic) in enumerate(table):
        ours = NAMES[word]
        top = word >> 12
        if top in (0xA, 0xF):
            expected = "line_a" if top == 0xA else "line_f"
            if ours == expected:
                traps += 1
            else:
                unexpected.append(f"${word:04X}: map {ours}, expected {expected}")
            continue
        if ours in TRAPS:
            if valid:
                unexpected.append(f"${word:04X}: map {ours}, Musashi {mnemonic}")
            else:
                traps += 1
            continue
        if not valid:
            if ours in ("bcc", "bra", "bsr") and word & 0xFF == 0xFF:
                known += 1
            else:
                unexpected.append(f"${word:04X}: map {ours}, Musashi rejects it")
            continue
        family = FAMILY.get(mnemonic, mnemonic)
        if PRINTED_AS.get(ours, ours) == family or ours == family:
            agree += 1
        else:
            unexpected.append(f"${word:04X}: map {ours}, Musashi {mnemonic}")
    defined = sum(name not in TRAPS for name in NAMES)
    print(f"Musashi {MUSASHI_REVISION[:12]}: {agree:,} defined words agree in family, "
          f"{known} known differences (Bcc/BRA/BSR $FF, PRM), {traps:,} trap words agree; "
          f"the map defines {defined:,}")  # fmt: skip
    for line in unexpected[: args.show]:
        print("  " + line)
    print(f"{len(unexpected)} unexpected differences of 65,536")
    return 1 if unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
