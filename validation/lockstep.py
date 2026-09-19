"""Lockstep the core against a MAME 0.285 trace of a real game (rung 4).

    python validation/lockstep.py record genesis ROM.zip --seconds 20
    python validation/lockstep.py compare genesis ROM.zip [--limit N]

``record`` runs MAME headless with ``lockstep.lua`` (docs/mame-oracle.md) in
a fresh directory under ``validation/mame_runs/`` and leaves ``error.log``
there: one line per instruction with every register, and one line per read
of the device window.  ``compare`` builds the board's memory map around the
core -- ROM from the romset, work RAM zeroed as MAME zeroes it -- replays the
device reads in the order MAME made them, and checks, before every
instruction, that PC, SR, D0-D7, A0-A6, USP and SSP are MAME's.  An
interrupt is recognised where MAME's next line is a handler entered with the
mask raised; the host then asserts that level for one step, as the board's
interrupt line does, and the core must arrive at the same place.

The host is here, not in the core (docs/handoff-brief.md).  Nothing it reads
or writes is committed: ROMs stay where they are, traces under
``validation/mame_runs/`` (ignored).
"""

from __future__ import annotations

import argparse
import collections
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).resolve().parent)]

from mame_trace import FIELDS, Access, records  # noqa: E402

from m68000_python import M68000CPU  # noqa: E402

MAME = "/usr/games/mame"
RUNS = Path(__file__).resolve().parent / "mame_runs"


class Divergence(Exception):
    """The core and MAME disagree; the message says where."""


class Board:
    """A 24-bit memory map: ROM, optionally work RAM, and replayed device windows.

    Reads inside ``read_window`` are replayed from the trace; writes inside
    ``write_window`` are checked against it, value and all, in the order
    MAME made them.
    """

    name = ""
    driver = ""  # MAME machine name
    read_window = (0, 0)  # start, length
    write_window = (0, 0)
    ram_base = 0x1000000  # no RAM modelled unless a board sets it
    ram_mask = 0
    #: Extra debugger commands for lockstep.lua, e.g. to mark another bus master's accesses.
    extra_watch = ""

    def __init__(self, rom: bytes) -> None:
        self.rom = rom
        self.ram = bytearray(self.ram_mask + 1)
        self.pending: list[Access] = []

    def mame_arguments(self, rom_path: Path) -> list[str]:
        return [self.driver, "-cart", str(rom_path)]

    @staticmethod
    def _inside(window: tuple[int, int], address: int) -> bool:
        return window[0] <= address < window[0] + window[1]

    def _expect(self, kind: str, address: int, bits: int, value: int | None) -> int:
        if not self.pending:
            raise Divergence(f"core {kind} {address:06X}.{bits} that MAME did not make")
        expected = self.pending.pop(0)
        if (expected.kind, expected.address, expected.bits) != (kind, address, bits) or (
            value is not None and expected.value != value
        ):
            shown = "" if value is None else f"={value:X}"
            raise Divergence(
                f"core {kind} {address:06X}.{bits}{shown}, MAME {expected.kind} "
                f"{expected.address:06X}.{expected.bits}={expected.value:X}"
            )
        return expected.value

    # -- the four bus callables ------------------------------------------------

    def read_word(self, address: int) -> int:
        if address >= self.ram_base:
            offset = address & self.ram_mask
            return (self.ram[offset] << 8) | self.ram[offset + 1]
        if self._inside(self.read_window, address):
            return self._expect("R", address, 16, None)
        if address + 1 < len(self.rom):
            return (self.rom[address] << 8) | self.rom[address + 1]
        raise Divergence(f"read of unmapped {address:06X}")

    def read_byte(self, address: int) -> int:
        if address >= self.ram_base:
            return self.ram[address & self.ram_mask]
        if self._inside(self.read_window, address):
            return self._expect("R", address, 8, None)
        if address < len(self.rom):
            return self.rom[address]
        raise Divergence(f"read of unmapped {address:06X}")

    def write_word(self, address: int, value: int) -> None:
        if self._inside(self.write_window, address):
            self._expect("W", address, 16, value)
        if address >= self.ram_base:
            offset = address & self.ram_mask
            self.ram[offset] = value >> 8
            self.ram[offset + 1] = value & 0xFF

    def write_byte(self, address: int, value: int) -> None:
        if self._inside(self.write_window, address):
            self._expect("W", address, 8, value)
        if address >= self.ram_base:
            self.ram[address & self.ram_mask] = value

    def tas_write(self, address: int, value: int) -> None:
        self.write_byte(address, value)


class Genesis(Board):
    """MAME's ``genesis`` driver (sega/megadriv.cpp at mame0285).

    Cartridge ROM from $000000; work RAM $E00000-$FFFFFF, 64 KB mirrored,
    zeroed at reset (``memset`` in ``machine_reset``), modelled here;
    everything between the end of the ROM and $DFFFFF -- Z80 window, I/O,
    VDP -- has its reads replayed and its writes checked.  The bus drops
    TAS's write-back (``megadriv_tas_callback``: "writeback not allowed"),
    so the host does too.  Interrupts are autovectored.
    """

    name = "genesis"
    driver = "genesis"
    ram_base = 0xE00000
    ram_mask = 0xFFFF
    # The Z80 reaches the 68000's bus through its bank window; log its bank
    # register writes and window accesses so the reader can drop them.
    extra_watch = (
        "dbg:command('wpset 6000:genesis_snd_z80,100,w,1,{logerror \"B %X\\n\",wpdata; g}')\n"
        "dbg:command('wpset 8000:genesis_snd_z80,8000,rw,1,{logerror \"Z %X\\n\",wpaddr; g}')"
    )

    def __init__(self, rom: bytes) -> None:
        super().__init__(rom)
        self.read_window = (len(rom), 0xE00000 - len(rom))
        self.write_window = self.read_window

    def tas_write(self, address: int, value: int) -> None:
        pass  # the Genesis bus never completes TAS's write cycle


class System16B(Board):
    """MAME's ``altbeast`` (sega/segas16b.cpp at mame0285), System 16B.

    Only the program ROM is modelled (256 KB at $000000, two byte-wide ROMs
    interleaved).  The 315-5195 mapper, work RAM, tile, sprite and palette
    RAM, I/O and the i8751's shared memory are all outside it: every read
    past the ROM is replayed and every write anywhere is checked, so the
    lockstep needs no model of the mapper.
    """

    name = "altbeast"
    driver = "altbeast"
    # The i8751 reaches the 68000's bus through the mapper: writing 1 or 2
    # to register 5 makes it write or read one word (sega/315_5195.cpp).
    # Log its mapper writes so the trace reader can drop those accesses.
    extra_watch = (
        "dbg:command('wpset 0:mcu:data,10,w,1,{logerror \"M %X %X\\n\",wpaddr,wpdata; g}')"
    )
    romset = Path("/data/emu/source/myrient.erista.me/files/MAME/ROMs (non-merged)/altbeast.zip")
    program = ("epr-11907.a7", "epr-11906.a5")  # even bytes, odd bytes

    def __init__(self, rom: bytes) -> None:
        super().__init__(rom)
        self.read_window = (len(rom), 0x1000000 - len(rom))
        self.write_window = (0, 0x1000000)

    def mame_arguments(self, rom_path: Path) -> list[str]:
        return [self.driver, "-rompath", str(rom_path.parent)]

    @classmethod
    def load(cls, path: Path) -> bytes:
        with zipfile.ZipFile(path) as archive:
            even, odd = (archive.read(name) for name in cls.program)
        rom = bytearray(2 * len(even))
        rom[0::2] = even
        rom[1::2] = odd
        return bytes(rom)


BOARDS: dict[str, type[Board]] = {"genesis": Genesis, "altbeast": System16B}


def load_rom(board: type[Board], path: Path) -> bytes:
    if hasattr(board, "load"):
        return board.load(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            return archive.read(names[0])
    return path.read_bytes()


def run_directory(board: str, rom: Path, tag: str = "") -> Path:
    stem = "".join(c if c.isalnum() else "_" for c in rom.stem)[:40]
    return RUNS / f"{board}-{stem}{'-' + tag if tag else ''}"


def record(board_name: str, rom_path: Path, seconds: float, tag: str = "") -> Path:
    board = BOARDS[board_name](load_rom(BOARDS[board_name], rom_path))
    directory = run_directory(board_name, rom_path, tag)
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    script = (Path(__file__).resolve().parent / "lockstep.lua").read_text()
    script = script.replace("READ_START", f"0x{board.read_window[0]:X}")
    script = script.replace("READ_LENGTH", f"0x{board.read_window[1]:X}")
    script = script.replace("WRITE_START", f"0x{board.write_window[0]:X}")
    script = script.replace("WRITE_LENGTH", f"0x{board.write_window[1]:X}")
    script = script.replace("TRACEFILE", "disassembly.trace")
    script = script.replace("EXTRA", board.extra_watch)
    (directory / "lockstep.lua").write_text(script)
    command = [MAME, *board.mame_arguments(rom_path), "-homepath", ".", "-video", "none",
               "-sound", "none", "-nothrottle", "-noreadconfig", "-skip_gameinfo", "-debug",
               "-debugger", "none", "-log", "-autoboot_script", "lockstep.lua",
               "-str", str(seconds)]  # fmt: skip
    (directory / "command.txt").write_text(" ".join(command) + "\n")
    started = time.perf_counter()
    subprocess.run(command, cwd=directory, check=True, capture_output=True)
    print(f"recorded {directory} in {time.perf_counter() - started:.0f} s")
    return directory


def registers(cpu: M68000CPU) -> dict[str, int]:
    values = {"pc": cpu.PC, "sr": cpu.SR}
    values.update({f"d{i}": cpu.R[i] for i in range(8)})
    values.update({f"a{i}": cpu.R[8 + i] for i in range(7)})
    values["usp"] = cpu.usp
    values["ssp"] = cpu.ssp
    return values


def same(ours: dict[str, int], theirs: dict[str, int]) -> bool:
    return all(ours[k] == theirs[k] for k in FIELDS)


def difference(ours: dict[str, int], theirs: dict[str, int]) -> list[str]:
    return [f"{k}: core {ours[k]:X} MAME {theirs[k]:X}" for k in FIELDS if ours[k] != theirs[k]]


def compare(board_name: str, rom_path: Path, trace: Path, limit: int | None) -> int:
    board = BOARDS[board_name](load_rom(BOARDS[board_name], rom_path))
    cpu = M68000CPU(
        board.read_byte, board.read_word, board.write_byte, board.write_word,
        tas_write=board.tas_write,
    )  # fmt: skip
    cpu.reset()
    count = interrupts = resets = 0
    clock_checked = clock_mismatches = clock_stalls = pending_clocks = 0
    previous_clock: int | None = None
    clock_notes: list[str] = []
    interrupt_clocks: collections.Counter = collections.Counter()
    started = time.perf_counter()
    history: list[str] = []
    leftover: list[Access] = []
    reset_ssp = int.from_bytes(board.rom[0:4], "big")
    reset_pc = int.from_bytes(board.rom[4:8], "big") & 0xFFFFFF
    stream = records(trace)
    upcoming = next(stream, None)
    while upcoming is not None:
        state, accesses = upcoming
        upcoming = next(stream, None)
        if (
            upcoming is not None
            and upcoming[0]["pc"] == reset_pc
            and upcoming[0]["ssp"] == reset_ssp
            and upcoming[0]["sr"] == 0x2700
            and not accesses
        ):
            # The board reset the CPU (on altbeast the i8751 drives RESET)
            # partway through this instruction, which never completed.  The
            # reset defines only SSP, PC and SR; the other registers keep
            # whatever the aborted instruction had done to them, so they are
            # taken from MAME's next line (the one resynchronisation).
            if not same(registers(cpu), state):
                print(f"DIVERGENCE before the reset at record {count:,}")
                return 1
            cpu.reset()
            after = upcoming[0]
            for index in range(8):
                cpu.R[index] = after[f"d{index}"]
            for index in range(7):
                cpu.R[8 + index] = after[f"a{index}"]
            cpu.usp = after["usp"]
            resets += 1
            previous_clock = None
            continue
        ours = registers(cpu)
        clocks_here = 0
        if not same(ours, state):
            level = (state["sr"] >> 8) & 7
            if ours["pc"] != state["pc"] and level > ((cpu.SR >> 8) & 7):
                # MAME took an interrupt here: the board's line, held for one
                # step.  Its stack writes were logged after the previous
                # instruction's accesses.
                board.pending, leftover = leftover, []
                cpu.set_ipl(level)
                try:
                    clocks_here += cpu.step()
                except Divergence as error:
                    print(f"DIVERGENCE in the interrupt before {count:,}: {error}")
                    return 1
                cpu.set_ipl(0)
                leftover = board.pending
                interrupts += 1
                ours = registers(cpu)
        if leftover:
            print(f"DIVERGENCE: instruction {count - 1:,} left accesses unmade: {leftover[:4]}")
            return 1
        if not same(ours, state):
            print(f"DIVERGENCE before instruction {count:,} at {state['pc']:06X}")
            for line in difference(ours, state):
                print("   ", line)
            print("    last instructions:", *history[-8:], sep="\n      ")
            return 1
        if "clock" in state:
            if previous_clock is None:
                cpu.clock = state["clock"]  # the E-clock phase follows MAME's count
            else:
                spent = state["clock"] - previous_clock
                expected = pending_clocks + clocks_here
                if clocks_here and spent - expected <= 1000:
                    # An interrupt entry: record how its clocks compare, by
                    # the E-clock phase at the acknowledge (rung 6).
                    interrupt_clocks[(cpu.last_acknowledge_phase, spent - expected)] += 1
                if spent - expected > 1000:
                    # The board held the CPU (altbeast: the driver's
                    # spin_68k_w, 20,000 cycles when the i8751 asks): not an
                    # instruction's clocks.
                    clock_stalls += 1
                    cpu.clock = state["clock"]
                elif spent != expected:
                    clock_mismatches += 1
                    if len(clock_notes) < 12:
                        clock_notes.append(
                            f"before {count:,} at {state['pc']:06X}: MAME {spent}, core "
                            f"{expected} (last {history[-1] if history else '-'})"
                        )
                    cpu.clock = state["clock"]  # resynchronise the phase
                clock_checked += 1
            previous_clock = state["clock"]
        board.pending = list(accesses)
        try:
            pending_clocks = cpu.step()
        except Divergence as error:
            print(f"DIVERGENCE in instruction {count:,} at {state['pc']:06X}: {error}")
            return 1
        leftover = board.pending
        history.append(f"{state['pc']:06X}")
        count += 1
        if limit and count >= limit:
            break
    elapsed = time.perf_counter() - started
    if clock_checked:
        agreeing = clock_checked - clock_mismatches - clock_stalls
        print(
            f"clocks: {agreeing:,} of {clock_checked:,} intervals agree; "
            f"{clock_stalls:,} include a board stall of over 1,000 clocks"
        )
        if interrupt_clocks:
            items = sorted(interrupt_clocks.items())
            shown = ", ".join(f"phase {p}: {d:+d} x{n}" for (p, d), n in items)
            print(f"    interrupt entries, MAME minus core by E-clock phase: {shown}")
        for note in clock_notes:
            print("   ", note)
    print(
        f"{board_name} {rom_path.name}: {count:,} instructions identical "
        f"({interrupts:,} interrupts, {resets:,} resets) in {elapsed:.0f} s"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("record", "compare"))
    parser.add_argument("board", choices=sorted(BOARDS))
    parser.add_argument(
        "rom", type=Path, nargs="?", help="cartridge (genesis); altbeast uses its romset"
    )
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--tag", default="", help="keep this run apart from others of the board")
    args = parser.parse_args()
    if args.rom is None:
        args.rom = getattr(BOARDS[args.board], "romset", None)
    if args.action == "record":
        record(args.board, args.rom, args.seconds, args.tag)
        return 0
    trace = run_directory(args.board, args.rom, args.tag) / "error.log"
    return compare(args.board, args.rom, trace, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
