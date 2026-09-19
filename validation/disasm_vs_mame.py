"""Compare the disassembler with MAME 0.285's on every instruction a trace ran.

    python validation/disasm_vs_mame.py altbeast [--tag 30s]
    python validation/disasm_vs_mame.py genesis ROM.zip

Reads the debugger's own trace (``disassembly.trace``: ``ADDRESS: text``)
that ``lockstep.py record`` leaves beside ``error.log``, takes each distinct
address inside the ROM, disassembles the ROM there with this package, and
compares the text with MAME's after collapsing runs of spaces.  Prints the
count of distinct instructions compared and every disagreement.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).parent)]

from lockstep import BOARDS, load_rom, run_directory  # noqa: E402

from m68000_python.disasm import disassemble  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("board", choices=sorted(BOARDS))
    parser.add_argument("rom", type=Path, nargs="?")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    board = BOARDS[args.board]
    rom_path = args.rom or getattr(board, "romset", None)
    rom = load_rom(board, rom_path)
    trace = run_directory(args.board, rom_path, args.tag) / "disassembly.trace"

    def read_word(address: int) -> int:
        return (rom[address] << 8) | rom[address + 1] if address + 1 < len(rom) else 0

    seen: dict[int, str] = {}
    with open(trace, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = re.match(r"^([0-9A-F]{6}): (.*)$", line.rstrip("\n"))
            if match:
                address = int(match.group(1), 16)
                if address not in seen and address + 1 < len(rom):
                    seen[address] = re.sub(r" +", " ", match.group(2).strip())
    disagreements = 0
    for address, theirs in sorted(seen.items()):
        ours = disassemble(read_word, address).text
        if ours != theirs:
            disagreements += 1
            print(f"{address:06X}  core: {ours!r}  MAME: {theirs!r}")
    print(f"{len(seen) - disagreements:,} of {len(seen):,} distinct instructions agree")
    return 1 if disagreements else 0


if __name__ == "__main__":
    raise SystemExit(main())
