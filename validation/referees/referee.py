"""Feed cases to the referee drivers and compare what they say with the core.

The drivers (winuae_referee, musashi_referee; built by build_referees.py)
read one case per line and print one result per line.  This module turns a
corpus case, or a hand-written state, into a case line, runs batches through
a driver, and reduces every source -- a referee's line, a corpus case's
final state, a run of this core -- to the same :class:`Outcome`, so that any
two of them can be compared field by field.

Two views, because the referees see an instruction differently:

* **pre-exception** (WinUAE's tester): the registers at the moment an
  exception is raised, the exception's number, and the stack frame it
  builds; the exception's own processing (vector fetch, refill) is not run.
  For a corpus case or a core run the view is recovered from the final
  state: the frame is read off the stack, the stacked SR is the SR before
  the exception, and the SSP before is the final SSP plus the frame.
* **post** (Musashi): the state after the whole step, exception entry
  included.

docs/referees.md says what each referee can judge.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from corpus import Case  # noqa: E402

from m68000_python import M68000CPU  # noqa: E402
from m68000_python._core import S  # noqa: E402

BINARIES = {
    "winuae": HERE / "build" / "winuae" / "winuae_referee",
    "musashi": HERE / "build" / "musashi" / "musashi_referee",
}
REGISTER_NAMES = tuple(f"d{i}" for i in range(8)) + tuple(f"a{i}" for i in range(7))

# ----------------------------------------------------------------------------
# Inputs


@dataclass
class Setup:
    """A starting state: registers, SR, the instruction's address, RAM bytes."""

    registers: dict[str, int]  # d0-d7, a0-a6, usp, ssp
    sr: int
    pc: int  # the instruction's own address
    ram: dict[int, int]  # byte address -> byte

    def line(self, ident: str) -> str:
        r = self.registers
        values = [r[name] for name in REGISTER_NAMES] + [r["usp"], r["ssp"], self.sr, self.pc]
        pairs = " ".join(f"{a:x}:{b:x}" for a, b in self.ram.items())
        return (
            f"C {ident} {' '.join(f'{v & 0xFFFFFFFF:x}' for v in values)} {len(self.ram):x} {pairs}"
        )

    def byte(self, address: int) -> int:
        return self.ram.get(address & 0xFFFFFF, 0)


def setup_from_case(case: Case, byte_ram: bool) -> Setup:
    """The starting state of a corpus case (m68000: word RAM; 680x0: byte RAM)."""
    initial = case.initial
    registers = {name: initial.registers[name] for name in (*REGISTER_NAMES, "usp", "ssp")}
    pc = (initial.registers["pc"] - 4) & 0xFFFFFF
    ram: dict[int, int] = {}
    if byte_ram:
        ram.update({a & 0xFFFFFF: v & 0xFF for a, v in initial.ram.items()})
    else:
        for address, word in initial.ram.items():
            ram[address & 0xFFFFFF] = word >> 8
            ram[(address + 1) & 0xFFFFFF] = word & 0xFF
    # The prefetch pair is the instruction's first two words; make sure RAM
    # holds them (both corpora list them, but a referee reads memory).
    for offset, word in zip((0, 2), initial.prefetch, strict=True):
        ram.setdefault((pc + offset) & 0xFFFFFF, word >> 8)
        ram.setdefault((pc + offset + 1) & 0xFFFFFF, word & 0xFF)
    return Setup(registers, initial.registers["sr"], pc, ram)


# ----------------------------------------------------------------------------
# Running a driver


class Driver:
    """One referee process; ``run`` streams case lines through it."""

    def __init__(self, name: str) -> None:
        binary = BINARIES[name]
        if not binary.exists():
            raise SystemExit(f"{binary} not built: python validation/referees/build_referees.py")
        self.name = name
        self.process = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1 << 20,
        )

    def run(self, lines: Iterable[str], batch: int = 4096) -> Iterator[dict]:
        """Yield one parsed result per case line, in order."""
        lines = list(lines)
        assert self.process.stdin and self.process.stdout

        def feed() -> None:
            stdin = self.process.stdin
            for index, line in enumerate(lines):
                stdin.write(line + "\n")
                if index % batch == batch - 1:
                    stdin.write("F\n")
                    stdin.flush()
            stdin.write("F\n")
            stdin.flush()

        writer = threading.Thread(target=feed, daemon=True)
        writer.start()
        for _ in lines:
            text = self.process.stdout.readline()
            if not text:
                raise RuntimeError(f"{self.name} referee exited early")
            yield parse_result(text)
        writer.join()

    def command(self, text: str) -> None:
        assert self.process.stdin
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.write("Q\n")
            self.process.stdin.close()
        self.process.wait()


def parse_result(text: str) -> dict:
    parts = text.split()
    result: dict = {"id": parts[1]}
    for part in parts[2:]:
        key, _, value = part.partition("=")
        result[key] = value
    for key in ("pc", "sr", "usp", "ssp"):
        result[key] = int(result[key], 16)
    for key in ("exc", "cyc", "excyc", "trace", "extra", "stopped"):
        if key in result:
            result[key] = int(result[key])
    result["r"] = [int(v, 16) for v in result["r"].split(",")]
    writes = {}
    if result.get("w"):
        for pair in result["w"].split(","):
            address, value = pair.split(":")
            writes[int(address, 16)] = int(value, 16)
    result["w"] = writes
    for key in ("frame", "frame1"):
        if key in result:
            result[key] = bytes.fromhex(result[key])
    result["flags"] = {f for f in result.get("flags", "").split(",") if f}
    return result


# ----------------------------------------------------------------------------
# Outcomes


@dataclass
class Outcome:
    """What one source says an instruction did (see the module docstring)."""

    exception: int  # vector number, 0 for none
    registers: dict[str, int]  # d0-d7, a0-a6, usp, ssp, sr, pc
    frame: bytes = b""
    frame1: bytes = b""  # a group 1/2 frame an odd vector cut short
    writes: dict[int, int] = field(default_factory=dict)  # byte address -> final byte
    clocks: int = 0
    notes: set[str] = field(default_factory=set)


def vector_fetch(log: list[tuple], last: bool = True) -> tuple[int, int] | None:
    """(vector, index) of the last vector fetch in an access log, or None.

    A log entry is (kind, address, size, value, fc).  A vector fetch is two
    supervisor-data word reads of a long in the vector table, after at least
    three supervisor-data writes (the frame); the one that ends a step is
    followed only by program reads (the refill), which ``last`` requires.
    """
    for index in range(len(log) - 2, -1, -1):
        first, second = log[index], log[index + 1]
        if (
            first[0] == "r"
            and second[0] == "r"
            and first[4] == 5
            and second[4] == 5
            and first[1] % 4 == 0
            and second[1] == first[1] + 2
            and first[1] < 0x400
            and index >= 3
            and all(e[0] in ("w", "we") and e[4] == 5 for e in log[index - 3 : index])
            and (not last or all(e[0] == "r" and e[4] == 6 for e in log[index + 2 :]))
        ):
            return first[1] // 4, index
    return None


def outcome_after_step(
    registers: dict[str, int],
    memory: dict[int, int],
    initial: dict[int, int],
    log: list[tuple],
    clocks: int,
) -> tuple[Outcome, Outcome]:
    """(pre-exception view, post view) of a finished step.

    ``registers`` hold d0-d7, a0-a6, usp, ssp, sr and the *prefetch* pc (the
    next instruction's address + 4); ``memory`` and ``initial`` map byte
    addresses to bytes after and before; ``log`` is the access log.
    """
    post_registers = dict(registers)
    post_registers["pc"] = (registers["pc"] - 4) & 0xFFFFFF

    def byte(address: int) -> int:
        address &= 0xFFFFFF
        return memory.get(address, initial.get(address, 0))

    written = set()
    for kind, address, size, _value, _fc in log:
        if kind in ("w", "t"):
            written.add(address & 0xFFFFFF)
            if size == ".w":
                written.add((address + 1) & 0xFFFFFF)
    # Byte writes in the m68000 corpus's shape name the even address; the
    # strobes say which half, so check both halves' values.
    post = Outcome(0, post_registers, writes={a: byte(a) for a in sorted(written)}, clocks=clocks)

    fetch = vector_fetch(log)
    pre_registers = dict(post_registers)
    if fetch is None:
        return Outcome(0, pre_registers, writes=dict(post.writes), clocks=clocks), post
    vector, _ = fetch
    post.exception = vector
    ssp = registers["ssp"]
    group0 = vector in (2, 3)
    size = 14 if group0 else 6
    frame = bytes(byte(ssp + i) for i in range(size))
    frame1 = b""
    extent = size
    # An address error in the middle of a group 1/2 exception: the earlier
    # vector fetch, and the six bytes it had stacked above the new frame.
    earlier = vector_fetch(log[: fetch[1]], last=False) if group0 else None
    if earlier is not None and earlier[0] not in (2, 3):
        frame1 = bytes(byte(ssp + 14 + i) for i in range(6))
        extent = 20
    if group0:
        sr = (frame[8] << 8) | frame[9]
        pc = int.from_bytes(frame[10:14], "big")
    else:
        sr = (frame[0] << 8) | frame[1]
        pc = int.from_bytes(frame[2:6], "big")
    if frame1:
        sr = (frame1[0] << 8) | frame1[1]
    pre_registers["sr"] = sr
    pre_registers["pc"] = pc & 0xFFFFFF
    pre_registers["ssp"] = (ssp + extent) & 0xFFFFFFFF
    # Before the exception, A7 was the stack pointer of the mode SR names.
    frame_bytes = {(ssp + i) & 0xFFFFFF for i in range(extent)}
    writes = {a: v for a, v in post.writes.items() if a not in frame_bytes}
    pre = Outcome(vector, pre_registers, frame, frame1, writes, clocks)
    if earlier is not None and earlier[0] not in (2, 3):
        pre.notes.add(f"odd vector {earlier[0]}")
    return pre, post


def outcome_of_case(case: Case, byte_ram: bool) -> tuple[Outcome, Outcome]:
    """(pre, post) views of a corpus case's recorded final state."""
    setup = setup_from_case(case, byte_ram)
    final = case.final
    registers = {
        name: final.registers[name] for name in (*REGISTER_NAMES, "usp", "ssp", "sr", "pc")
    }
    memory: dict[int, int] = {}
    if byte_ram:
        memory.update({a & 0xFFFFFF: v for a, v in final.ram.items()})
    else:
        for address, word in final.ram.items():
            memory[address & 0xFFFFFF] = word >> 8
            memory[(address + 1) & 0xFFFFFF] = word & 0xFF
    log = []
    for t in case.transactions:
        address = t.address
        if t.size == ".b" and not byte_ram and not t.uds:
            address |= 1  # m68000 corpus: a lower-byte access names the even address
        log.append((t.kind, address, t.size, t.data, t.fc))
    return outcome_after_step(registers, memory, setup.ram, log, case.cycles)


class _Host:
    """Byte RAM with the access log the outcome functions read."""

    def __init__(self, ram: dict[int, int]) -> None:
        self.memory = dict(ram)
        self.log: list[tuple] = []

    def read_byte(self, address: int, fc: int = 0) -> int:
        self.log.append(("r", address, ".b", 0, fc))
        return self.memory.get(address, 0)

    def read_word(self, address: int, fc: int = 0) -> int:
        self.log.append(("r", address, ".w", 0, fc))
        return (self.memory.get(address, 0) << 8) | self.memory.get((address + 1) & 0xFFFFFF, 0)

    def write_byte(self, address: int, value: int, fc: int = 0) -> None:
        self.log.append(("w", address, ".b", value, fc))
        self.memory[address] = value & 0xFF

    def write_word(self, address: int, value: int, fc: int = 0) -> None:
        self.log.append(("w", address, ".w", value, fc))
        self.memory[address] = (value >> 8) & 0xFF
        self.memory[(address + 1) & 0xFFFFFF] = value & 0xFF


def run_core(
    setup: Setup, bus_error: tuple[int, int, int] | None = None
) -> tuple[Outcome, Outcome, M68000CPU]:
    """Run this core for one step from ``setup``; return (pre, post, cpu).

    ``bus_error`` is (start, size, mode) with the drivers' mode bits: 1 data
    read, 2 write, 4 program read; an access there raises BusError.
    """
    from m68000_python import BusError

    host = _Host(setup.ram)
    read_byte, read_word = host.read_byte, host.read_word
    write_byte, write_word = host.write_byte, host.write_word
    if bus_error is not None:
        start, size, mode = bus_error

        def inside(address: int) -> bool:
            return start <= address < start + size

        def wrap_read(function):
            def read(address: int, fc: int = 0) -> int:
                program = fc in (2, 6)
                if inside(address) and ((mode & 4) if program else (mode & 1)):
                    raise BusError
                return function(address, fc)

            return read

        def wrap_write(function):
            def write(address: int, value: int, fc: int = 0) -> None:
                if inside(address) and mode & 2:
                    raise BusError
                function(address, value, fc)

            return write

        read_byte, read_word = wrap_read(read_byte), wrap_read(read_word)
        write_byte, write_word = wrap_write(write_byte), wrap_write(write_word)
    cpu = M68000CPU(read_byte, read_word, write_byte, write_word, function_codes=True)
    r = setup.registers
    for index, name in enumerate(REGISTER_NAMES):
        cpu.R[index] = r[name] & 0xFFFFFFFF
    cpu.SR = setup.sr
    if cpu.SR & S:
        cpu.R[15], cpu._other_sp = r["ssp"], r["usp"]
    else:
        cpu.R[15], cpu._other_sp = r["usp"], r["ssp"]
    cpu.ir = (setup.byte(setup.pc) << 8) | setup.byte(setup.pc + 1)
    cpu.irc = (setup.byte(setup.pc + 2) << 8) | setup.byte(setup.pc + 3)
    cpu._pc = (setup.pc + 4) & 0xFFFFFF
    host.log.clear()
    clocks = cpu.step()
    registers = {f"d{i}": cpu.R[i] for i in range(8)}
    registers.update({f"a{i}": cpu.R[8 + i] for i in range(7)})
    registers.update(usp=cpu.usp, ssp=cpu.ssp, sr=cpu.SR, pc=cpu._pc)
    pre, post = outcome_after_step(registers, host.memory, setup.ram, host.log, clocks)
    if cpu.halted:
        pre.notes.add("halted")
        post.notes.add("halted")
    return pre, post, cpu


def outcome_of_winuae(result: dict, setup: Setup) -> Outcome:
    """The pre-exception view from a winuae_referee line."""
    r = result["r"]
    registers = {name: r[i] for i, name in enumerate(REGISTER_NAMES)}
    registers.update(
        usp=result["usp"], ssp=result["ssp"], sr=result["sr"], pc=result["pc"] & 0xFFFFFF
    )
    exception = result["exc"]
    if exception > 0:
        frame = result["frame"]
        if exception in (2, 3):
            registers["pc"] = int.from_bytes(frame[10:14], "big") & 0xFFFFFF
        else:
            registers["pc"] = int.from_bytes(frame[2:6], "big") & 0xFFFFFF
        if result.get("frame1"):
            registers["pc"] = int.from_bytes(result["frame1"][2:6], "big") & 0xFFFFFF
    outcome = Outcome(
        exception,
        registers,
        result.get("frame", b""),
        result.get("frame1", b""),
        dict(result["w"]),
        result["cyc"] + result["excyc"],
    )
    outcome.notes |= result["flags"]
    if result.get("trace"):
        outcome.notes.add("trace pending")
    return outcome


def outcome_of_musashi(result: dict) -> Outcome:
    """The post view from a musashi_referee line."""
    r = result["r"]
    registers = {name: r[i] for i, name in enumerate(REGISTER_NAMES)}
    registers.update(
        usp=result["usp"], ssp=result["ssp"], sr=result["sr"], pc=result["pc"] & 0xFFFFFF
    )
    outcome = Outcome(0, registers, writes=dict(result["w"]), clocks=result["cyc"])
    if result.get("stopped") == 2:
        outcome.notes.add("halted")
    elif result.get("stopped"):
        outcome.notes.add("stopped")
    return outcome


# ----------------------------------------------------------------------------
# Comparison

FRAME0_FIELDS = (
    ("information", 0, 2),
    ("address", 2, 6),
    ("ir", 6, 8),
    ("sr", 8, 10),
    ("pc", 10, 14),
)


def compare(
    left: Outcome,
    right: Outcome,
    setup: Setup,
    *,
    fields: Iterable[str] = ("exception", "registers", "frame", "memory", "clocks"),
) -> list[str]:
    """Names of what differs between two outcomes of the same view."""
    fields = set(fields)
    differences = []
    if "exception" in fields and left.exception != right.exception:
        differences.append("exception")
    if "registers" in fields or "flags" in fields:
        if "registers" in fields:
            differences.extend(
                name
                for name in (*REGISTER_NAMES, "usp", "ssp", "pc")
                if (left.registers[name] ^ right.registers[name]) & 0xFFFFFFFF
            )
        sr_l, sr_r = left.registers["sr"], right.registers["sr"]
        if sr_l & 0xFF00 != sr_r & 0xFF00 and "registers" in fields:
            differences.append("sr-system")
        if (sr_l ^ sr_r) & 0x1F:
            differences.append("ccr")
    if "frame" in fields and left.exception == right.exception and left.exception:
        if left.exception in (2, 3):
            for name, start, end in FRAME0_FIELDS:
                if name in ("sr", "pc"):
                    continue  # compared as the registers before the exception
                if left.frame[start:end] != right.frame[start:end]:
                    differences.append(f"frame-{name}")
        if left.frame1[2:6] != right.frame1[2:6] and (left.frame1 or right.frame1):
            differences.append("frame1-pc")
    if "memory" in fields:
        for address in sorted(set(left.writes) | set(right.writes)):
            a = left.writes.get(address, setup.byte(address))
            b = right.writes.get(address, setup.byte(address))
            if a != b:
                differences.append("memory")
                break
    if "clocks" in fields and left.clocks != right.clocks:
        differences.append("clocks")
    return differences
