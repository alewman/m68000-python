"""A line-command debugger over :class:`~m68000_python.debug.DebugSession`.

``CommandDebugger(session).execute("step 3")`` returns the lines a terminal
would print; ``interact(stdin, stdout)`` is the prompt loop that
``python -m m68000_python`` runs.  Numbers are decimal, or hexadecimal with a
``$`` or ``0x`` prefix, the rule of every console in this family.
"""

from dataclasses import dataclass
from typing import TextIO

from m68000_python.debug import BoundaryKind, DebugSession, StepRecord
from m68000_python.disasm import disassemble

HELP = """\
registers | r            show the registers
step [n] | s [n]         run n boundaries (default 1), showing each
run [n] | c [n]          run until a breakpoint, watchpoint, STOP or n steps (default 1,000,000)
break ADDR | b ADDR      stop before the instruction at ADDR
delete ADDR              remove a breakpoint
watch ADDR [r|w|rw]      stop after a step that touches ADDR
unwatch ADDR             remove a watchpoint
disassemble [ADDR] [N]   N instructions from ADDR (default: PC, 8) | d
memory ADDR [N]          N bytes from ADDR (default 64) | m
set REG VALUE            set d0-d7, a0-a7, usp, ssp, sr or pc
ipl LEVEL                set the interrupt level (0-7)
history [N]              the last N boundaries (default 10)
help                     this text
quit | q                 leave"""


class CommandError(Exception):
    """A command that could not be run; the message says why."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """What one command printed, and whether it asked to leave."""

    lines: tuple[str, ...] = ()
    quit: bool = False

    def __post_init__(self) -> None:
        if type(self.lines) is not tuple or not all(type(line) is str for line in self.lines):
            raise ValueError("lines must be a tuple of strings")
        if type(self.quit) is not bool:
            raise ValueError("quit must be a bool")


def parse_number(text: str, name: str = "number", *, maximum: int = 0xFFFFFFFF) -> int:
    """Parse a decimal number, or a hexadecimal one written ``$1F`` or ``0x1F``."""
    body = text.strip()
    try:
        if body.startswith("$"):
            value = int(body[1:], 16)
        elif body[:2].lower() == "0x":
            value = int(body[2:], 16)
        else:
            value = int(body, 10)
    except ValueError:
        raise CommandError(f"{name}: {text!r} is not a number") from None
    if not 0 <= value <= maximum:
        raise CommandError(f"{name}: {text} is out of range 0..{maximum:#x}")
    return value


class CommandDebugger:
    """Execute debugger commands against a session."""

    def __init__(self, session: DebugSession) -> None:
        self.session = session

    # -- views ---------------------------------------------------------------

    def registers(self) -> list[str]:
        state = self.session.target.capture_state()
        d = " ".join(f"D{i}={value:08X}" for i, value in enumerate(state.d))
        a = " ".join(f"A{i}={value:08X}" for i, value in enumerate((*state.a, state.a7)))
        sr = state.sr
        flags = "".join(
            c if sr & bit else "."
            for c, bit in zip("TSXNZVC", (0x8000, 0x2000, 16, 8, 4, 2, 1), strict=True)
        )
        status = f"PC={state.pc & 0xFFFFFF:06X} SR={sr:04X} {flags} I={(sr >> 8) & 7}"
        extra = f"USP={state.usp:08X} SSP={state.ssp:08X} IPL={state.ipl} clock={state.clock}"
        if state.stopped:
            extra += " STOPPED"
        if state.halted:
            extra += " HALTED"
        return [d[:47], d[48:], a[:47], a[48:], status, extra]

    def _result(self, lines: list[str]) -> CommandResult:
        return CommandResult(tuple(lines))

    def _describe(self, record: StepRecord) -> str:
        if record.kind is BoundaryKind.INSTRUCTION:
            text = (
                record.instruction.text
                if record.instruction
                else f"(opcode {record.before.ir:04X})"
            )
            return f"{record.before.pc & 0xFFFFFF:06X}  {text:40} {record.cycles:4} clocks"
        return f"{record.before.pc & 0xFFFFFF:06X}  <{record.kind.value}> {record.cycles} clocks"

    def disassemble(self, address: int | None, count: int) -> list[str]:
        peek = self.session.peek_word
        if peek is None:
            raise CommandError("the session has no peek_word: nothing to disassemble from")
        if address is None:
            address = self.session.target.capture_state().pc & 0xFFFFFF
        lines = []
        for _ in range(count):
            instruction = disassemble(peek, address)
            words = " ".join(f"{word:04X}" for word in instruction.words)
            lines.append(f"{address:06X}  {words:24} {instruction.text}")
            address = (address + instruction.length) & 0xFFFFFF
        return lines

    def memory(self, address: int, count: int) -> list[str]:
        peek = self.session.peek_word
        if peek is None:
            raise CommandError("the session has no peek_word: no memory to show")
        lines = []
        for row in range(address & ~1, address + count, 16):
            words = [peek((row + i) & 0xFFFFFF) for i in range(0, 16, 2)]
            data = b"".join(word.to_bytes(2, "big") for word in words)
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
            lines.append(f"{row & 0xFFFFFF:06X}  {data.hex(' ')}  {text}")
        return lines

    # -- the command language --------------------------------------------------

    def execute(self, line: str) -> CommandResult:
        words = line.split()
        if not words:
            return CommandResult()
        command, arguments = words[0].lower(), words[1:]
        session = self.session
        if command in ("quit", "q", "exit"):
            return CommandResult(quit=True)
        if command == "help":
            return self._result(HELP.splitlines())
        if command in ("registers", "r", "regs"):
            return self._result(self.registers())
        if command in ("step", "s"):
            count = parse_number(arguments[0], "count") if arguments else 1
            if count == 0:
                raise CommandError("count must be positive")
            return self._result([self._describe(session.step()) for _ in range(count)])
        if command in ("run", "c", "continue"):
            count = parse_number(arguments[0], "count") if arguments else 1_000_000
            if count == 0:
                raise CommandError("count must be positive")
            result = session.run(max_steps=count)
            lines = [
                f"{result.reason.value} after {result.steps:,} steps, {result.cycles:,} clocks"
            ]
            lines += [
                f"  {kind} {address:06X} = {value:X}" for kind, address, value, _ in result.hits
            ]
            return self._result(lines + self.registers())
        if command in ("break", "b"):
            session.add_breakpoint(
                parse_number(self._one(arguments, "address"), "address", maximum=0xFFFFFF)
            )
            return self._result(
                [f"breakpoints: {', '.join(f'{a:06X}' for a in sorted(session.breakpoints))}"]
            )
        if command == "delete":
            session.remove_breakpoint(
                parse_number(self._one(arguments, "address"), "address", maximum=0xFFFFFF)
            )
            return CommandResult()
        if command == "watch":
            if not arguments:
                raise CommandError("watch needs an address")
            kind = arguments[1] if len(arguments) > 1 else "rw"
            try:
                session.add_watchpoint(
                    parse_number(arguments[0], "address", maximum=0xFFFFFF), kind
                )
            except ValueError as exc:
                raise CommandError(str(exc)) from None
            return CommandResult()
        if command == "unwatch":
            session.remove_watchpoint(
                parse_number(self._one(arguments, "address"), "address", maximum=0xFFFFFF)
            )
            return CommandResult()
        if command in ("disassemble", "d", "dis"):
            address = parse_number(arguments[0], "address", maximum=0xFFFFFF) if arguments else None
            count = parse_number(arguments[1], "count") if len(arguments) > 1 else 8
            return self._result(self.disassemble(address, count))
        if command in ("memory", "m"):
            address = parse_number(self._one(arguments[:1], "address"), "address", maximum=0xFFFFFF)
            count = parse_number(arguments[1], "count", maximum=4096) if len(arguments) > 1 else 64
            return self._result(self.memory(address, count))
        if command == "set":
            if len(arguments) != 2:
                raise CommandError("set needs a register and a value")
            self._set(arguments[0].lower(), parse_number(arguments[1], arguments[0]))
            return self._result(self.registers())
        if command == "ipl":
            session.cpu.set_ipl(parse_number(self._one(arguments, "level"), "level", maximum=7))
            return CommandResult()
        if command == "history":
            count = parse_number(arguments[0], "count") if arguments else 10
            records = list(session.iter_history())[-count:] if count else []
            return self._result([self._describe(record) for record in records])
        raise CommandError(f"unknown command {command!r} (try help)")

    @staticmethod
    def _one(arguments: list[str], name: str) -> str:
        if len(arguments) != 1:
            raise CommandError(f"expected one {name}")
        return arguments[0]

    def _set(self, name: str, value: int) -> None:
        cpu = self.session.cpu
        if len(name) == 2 and name[0] in "da" and name[1] in "01234567":
            cpu.R[(0 if name[0] == "d" else 8) + int(name[1])] = value
        elif name == "usp":
            cpu.usp = value
        elif name == "ssp":
            cpu.ssp = value
        elif name == "sr":
            if value > 0xFFFF:
                raise CommandError("sr is 16 bits")
            cpu.set_sr(value)
        elif name == "pc":
            cpu.set_pc(value)
        else:
            raise CommandError(f"no register {name!r}")

    def interact(self, stdin: TextIO, stdout: TextIO) -> None:
        """Read commands from ``stdin`` until ``quit`` or end of input."""
        while True:
            stdout.write("m68000> ")
            stdout.flush()
            line = stdin.readline()
            if not line:
                return
            try:
                result = self.execute(line)
            except CommandError as exc:
                stdout.write(f"error: {exc}\n")
                continue
            for text in result.lines:
                stdout.write(text + "\n")
            if result.quit:
                return


__all__ = ["CommandDebugger", "CommandError", "CommandResult", "parse_number"]
