"""Load a program and step through it: ``python -m m68000_python``.

    python -m m68000_python --load program.bin@1000 --pc 1000
    python -m m68000_python --zip ROMPATH/altbeast.zip:epr-11907.a7,epr-11906.a5@0 --reset
    python -m m68000_python --load game.md@0 --reset -c "break 206" -c "run 100000"

The host is a flat 16 MB RAM holding every image loaded, so ROM is writable
and there are no devices: good for reading and stepping through code, not for
running a board (for that, write a host -- validation/lockstep.py has two).
``--zip ZIP:EVEN,ODD@ADDRESS`` interleaves a pair of byte-wide ROMs, as 68000
boards wire them.  Commands given with ``-c`` run first; then the prompt reads
stdin, unless ``--batch`` is given.  ``help`` lists the commands.
"""

import argparse
import sys
import zipfile
from pathlib import Path

from m68000_python.console import CommandDebugger, CommandError, parse_number
from m68000_python.cpu import M68000CPU
from m68000_python.debug import DebugSession

SIZE = 1 << 24


def _image(spec: str, zipped: bool) -> tuple[bytes, int]:
    source, _, where = spec.rpartition("@")
    if not source:
        raise SystemExit(f"{spec!r}: give the load address as FILE@ADDRESS")
    try:
        address = parse_number(where, "load address", maximum=SIZE - 1)
    except CommandError as exc:
        raise SystemExit(str(exc)) from None
    if zipped:
        archive, _, members = source.rpartition(":")
        if not archive:
            raise SystemExit(f"{spec!r}: give --zip as ZIPFILE:MEMBER[,ODD]@ADDRESS")
        with zipfile.ZipFile(archive) as z:
            parts = [z.read(member) for member in members.split(",")]
        if len(parts) == 2:
            data = bytearray(2 * len(parts[0]))
            data[0::2], data[1::2] = parts
            data = bytes(data)
        else:
            data = parts[0]
    else:
        data = Path(source).read_bytes()
    if address + len(data) > SIZE:
        raise SystemExit(f"{spec!r}: {len(data)} bytes do not fit at ${address:06X}")
    return data, address


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m m68000_python",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--load", action="append", default=[], metavar="FILE@ADDRESS")
    parser.add_argument("--zip", action="append", default=[], metavar="ZIP:MEMBER[,ODD]@ADDRESS")
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--pc", help="start at this hex address")
    start.add_argument("--reset", action="store_true", help="start from the vectors at 0 and 4")
    parser.add_argument(
        "-c", "--command", action="append", default=[], help="run first (repeatable)"
    )
    parser.add_argument("--batch", action="store_true", help="exit after the -c commands")
    args = parser.parse_args(argv)

    memory = bytearray(SIZE)
    for spec in args.load:
        data, address = _image(spec, zipped=False)
        memory[address : address + len(data)] = data
    for spec in args.zip:
        data, address = _image(spec, zipped=True)
        memory[address : address + len(data)] = data

    def read_word(address: int) -> int:
        return (memory[address] << 8) | memory[(address + 1) & 0xFFFFFF]

    def write_word(address: int, value: int) -> None:
        memory[address] = value >> 8
        memory[(address + 1) & 0xFFFFFF] = value & 0xFF

    cpu = M68000CPU(memory.__getitem__, read_word, memory.__setitem__, write_word)
    if args.reset:
        cpu.reset()
    elif args.pc is not None:
        cpu.set_pc(parse_number(args.pc, "pc", maximum=SIZE - 1))
    else:
        cpu.set_pc(0)
    session = DebugSession(cpu, peek_word=read_word, track_accesses=True)
    debugger = CommandDebugger(session)
    for command in ["registers", "disassemble", *args.command]:
        print(f"m68000> {command}")
        try:
            result = debugger.execute(command)
        except CommandError as exc:
            print(f"error: {exc}")
            continue
        for line in result.lines:
            print(line)
        if result.quit:
            return
    if not args.batch:
        debugger.interact(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
