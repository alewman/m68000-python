"""Check the opcode map against MAME 0.285's 68000 instruction listing, word for word.

    python scripts/check_decoder_vs_mame.py            # fetch the listing if needed, compare
    python scripts/check_decoder_vs_mame.py --show 20  # print up to 20 disagreements

MAME's microcoded 68000 decodes from ``m68000.lst``: one line per encoding,
``VALUE MASK MNEMONIC OPERANDS...``, a word being that instruction when
``word & MASK == VALUE``.  The listing at tag ``mame0285`` is fetched from
GitHub into validation/mame/ (ignored by git; it is MAME's, BSD-3-Clause) and
checked against a pinned SHA-256, then every one of the 65,536 first words is
compared: the set of defined words must agree, and for each defined word the
instruction family MAME names must be the handler ``_dispatch.NAMES`` gives
it.  The MAME lineage is T3 (docs/validation.md); this is a check that the
two decoders agree, not a hardware claim.  Exit status 1 on any difference.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from m68000_python._dispatch import NAMES  # noqa: E402

TAG = "mame0285"
URL = f"https://raw.githubusercontent.com/mamedev/mame/{TAG}/src/devices/cpu/m68000/m68000.lst"
SHA256 = "9b4605ef5e0bd2bb2e17a03146c37c6cf4757cf926ab1b06352d95ab09695631"
LISTING = ROOT / "validation" / "mame" / f"{TAG}-m68000.lst"

CONDITIONS = "t f hi ls cc cs ne eq vc vs pl mi ge lt gt le".split()
SHIFTS = {"asl": "asd", "asr": "asd", "lsl": "lsd", "lsr": "lsd", "roxl": "roxd", "roxr": "roxd",
          "rol": "rod", "ror": "rod"}  # fmt: skip
RENAMED = {"linea": "line_a", "linef": "line_f", "dbra": "dbcc"}


def fetch() -> str:
    if not LISTING.exists():
        LISTING.parent.mkdir(parents=True, exist_ok=True)
        print(f"fetching {URL}", flush=True)
        with urlopen(URL, timeout=60) as response:
            LISTING.write_bytes(response.read())
    data = LISTING.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"{LISTING}: SHA-256 {digest} is not the pinned {SHA256}")
    return data.decode()


def family(mnemonic: str, operands: list[str]) -> str:
    """The handler name this repository gives MAME's mnemonic and operand kinds."""
    base, _, size = mnemonic.partition(".")
    if base in RENAMED:
        return RENAMED[base]
    if base in ("ori", "andi", "eori") and operands and operands[-1] in ("ccr", "sr"):
        return f"{base}_to_{operands[-1]}"
    if base == "move":
        if operands and operands[0] == "sr":
            return "move_from_sr"
        if operands and operands[-1] in ("ccr", "sr"):
            return f"move_to_{operands[-1]}"
        if "usp" in operands:
            return "move_usp"
        return "move"
    if base in SHIFTS:
        return SHIFTS[base] if size else SHIFTS[base] + "_memory"
    for prefix, name in (("db", "dbcc"), ("s", "scc"), ("b", "bcc")):
        if base.startswith(prefix) and base[len(prefix) :] in CONDITIONS:
            return name
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", type=int, default=10, help="disagreements to print")
    args = parser.parse_args()
    rules = []
    for line in fetch().splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        value, mask, mnemonic, *operands = fields
        rules.append((int(value, 16), int(mask, 16), family(mnemonic, operands), line))
    theirs: list[str | None] = [None] * 0x10000
    ambiguous = 0
    for word in range(0x10000):
        matches = [name for value, mask, name, _ in rules if word & mask == value]
        if len(matches) > 1 and len(set(matches)) > 1:
            ambiguous += 1
        theirs[word] = matches[0] if matches else None
    undefined = {"illegal", "line_a", "line_f"}
    differences = []
    for word in range(0x10000):
        ours = NAMES[word]
        mame = theirs[word]
        if mame is None:
            # MAME's listing has no line for ILLEGAL ($4AFC-$4AFF are illegal anyway)
            # nor for the undefined words: both fall to its illegal handler, and
            # the line A/F words to their own exceptions.
            expected = "line_a" if word >> 12 == 0xA else "line_f" if word >> 12 == 0xF else None
            if ours not in undefined or (expected and ours != expected):
                differences.append((word, ours, "undefined"))
        elif mame != ours:
            differences.append((word, ours, mame))
    defined = sum(name is not None and name not in undefined for name in theirs)
    print(f"MAME {TAG} m68000.lst: {len(rules)} lines, {defined:,} defined words "
          f"(plus ILLEGAL and the line A/F words); this decoder: "
          f"{sum(n not in undefined for n in NAMES):,} defined words")  # fmt: skip
    if ambiguous:
        print(f"{ambiguous} words match two MAME lines of different families")
    for word, ours, mame in differences[: args.show]:
        print(f"  ${word:04X}: core {ours}, MAME {mame}")
    print(f"{len(differences)} of 65,536 words differ")
    return 1 if differences or ambiguous else 0


if __name__ == "__main__":
    raise SystemExit(main())
