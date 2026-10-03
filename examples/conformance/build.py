"""Write the committed conformance manifests and their reference traces.

    python examples/conformance/build.py

Each program is hand-assembled below, one instruction per line with its
MAME-spelled disassembly as the comment; :func:`check` disassembles every
line with this package's disassembler and refuses to write a program whose
text does not match, so a wrong encoding cannot slip in.  The manifests and
traces this writes are committed beside it (docs/conformance.md), and
tests/test_conformance.py checks that both are what this script and the
package produce today.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path

from m68000_python.conformance import manifest_from_dict, trace_manifest
from m68000_python.disasm import disassemble
from m68000_python.trace import write_trace

HERE = Path(__file__).resolve().parent
INTERRUPTS = HERE / "interrupts"

Words = list[int]
Item = tuple[int, Callable[[int, dict[str, int]], Words], str]


class Program:
    """A two-pass assembler for hand-encoded words: labels, branches and comments."""

    def __init__(self, origin: int) -> None:
        self.origin = origin
        self.items: list[Item] = []
        self.marks: dict[int, str] = {}

    def label(self, name: str) -> Program:
        self.marks[len(self.items)] = name
        return self

    def __call__(self, words: Words | Callable, text: str, size: int | None = None) -> Program:
        """One instruction: its words (or a function of its address and the labels)."""
        if callable(words):
            self.items.append((size, words, text))
        else:
            self.items.append((len(words), lambda pc, labels, w=words: w, text))
        return self

    def layout(self) -> tuple[dict[str, int], list[tuple[int, Words, str]]]:
        labels: dict[str, int] = {}
        pc = self.origin
        for index, (size, _, _) in enumerate(self.items):
            if index in self.marks:
                labels[self.marks[index]] = pc
            pc += 2 * size
        if len(self.items) in self.marks:
            labels[self.marks[len(self.items)]] = pc
        out = []
        pc = self.origin
        for size, words, text in self.items:
            encoded = words(pc, labels)
            assert len(encoded) == size, text
            out.append((pc, encoded, text))
            pc += 2 * size
        return labels, out

    def data(self) -> bytes:
        _, lines = self.layout()
        return b"".join(word.to_bytes(2, "big") for _, words, _ in lines for word in words)


def branch(opcode: int, target: str) -> Callable[[int, dict[str, int]], Words]:
    """Bcc/BSR/BRA with a 16-bit displacement from the word after the opcode."""
    return lambda pc, labels: [opcode, (labels[target] - (pc + 2)) & 0xFFFF]


def short(opcode: int, target: str) -> Callable[[int, dict[str, int]], Words]:
    """Bcc/BSR/BRA with an 8-bit displacement in the opcode."""

    def encode(pc: int, labels: dict[str, int]) -> Words:
        displacement = labels[target] - (pc + 2)
        assert -128 <= displacement <= 127 and displacement not in (0, -1), displacement
        return [opcode | (displacement & 0xFF)]

    return encode


def absolute(opcode: int, target: str, *before: int) -> Callable[[int, dict[str, int]], Words]:
    """An instruction whose last extension is a label's 32-bit address."""
    return lambda pc, labels: [opcode, *before, labels[target] >> 16, labels[target] & 0xFFFF]


def long(value: int) -> Words:
    return [value >> 16, value & 0xFFFF]


def check(program: Program) -> None:
    """Disassemble every line; its text must be the comment written beside it."""
    _, lines = program.layout()
    wrong = []
    for pc, words, text in lines:
        if text.startswith("dc.w"):
            continue
        data = b"".join(word.to_bytes(2, "big") for word in words)

        def read_word(address: int, data=data, pc=pc) -> int:
            offset = address - pc
            return int.from_bytes(data[offset : offset + 2], "big")

        found = disassemble(read_word, pc)
        if found.text != text or found.length != 2 * len(words):
            wrong.append(f"{pc:06X}: {found.text!r} ({found.length} bytes) != {text!r}")
    assert not wrong, "\n".join(wrong)


def vector_table(handlers: dict[int, int], ssp: int, pc: int) -> bytes:
    """Vectors 0-63: the reset SSP and PC, then a handler per listed vector (others 0)."""
    table = bytearray(256)
    table[0:8] = ssp.to_bytes(4, "big") + pc.to_bytes(4, "big")
    for vector, address in handlers.items():
        table[4 * vector : 4 * vector + 4] = address.to_bytes(4, "big")
    return bytes(table)


# -- the programs ---------------------------------------------------------------

DATA = 0x3000


def flags_and_branches() -> dict:
    """Arithmetic, flags, every addressing mode, branches, loops, subroutines, then STOP."""
    p = Program(0x1000)
    p([0x7005], "moveq #$5, D0")
    p([0x7203], "moveq #$3, D1")
    p([0x7400], "moveq #$0, D2")
    p([0xD041], "add.w D1, D0")
    p([0x9041], "sub.w D1, D0")
    p([0xB041], "cmp.w D1, D0")
    p([0x0440, 0x0006], "subi.w #$6, D0")  # negative: N, X, C
    p([0x41F9, *long(DATA)], "lea $3000.l, A0")
    p([0x30C0], "move.w D0, (A0)+")
    p([0x3100], "move.w D0, -(A0)")
    p([0x2140, 0x0004], "move.l D0, ($4,A0)")
    p([0x3230, 0x2002], "move.w ($2,A0,D2.w), D1")
    p([0x4A78, DATA], "tst.w $3000.w")
    p([0x0C79, 0x0005, *long(DATA)], "cmpi.w #$5, $3000.l")
    p([0x303A, 0x0010], "move.w ($1040,PC), D0")
    p([0x4BFB, 0x2002], "lea ($2,PC,D2.w), A5")
    p([0x0640, 0x1234], "addi.w #$1234, D0")
    p([0x7203], "moveq #$3, D1")
    p.label("count")
    p([0x5341], "subq.w #1, D1")
    p(short(0x6600, "count"), "bne $103c", 1)
    p([0x7603], "moveq #$3, D3")
    p([0x51CB, 0xFFFE], "dbra D3, $1042")
    p(branch(0x6100, "subroutine"), "bsr $107a", 2)
    p(absolute(0x4EB9, "subroutine"), "jsr $107a.l", 3)
    p([0xC2C0], "mulu.w D0, D1")
    p([0x80FC, 0x0007], "divu.w #$7, D0")
    p([0xE348], "lsl.w #1, D0")
    p([0xE2A0], "asr.l D1, D0")
    p([0xC300], "abcd D0, D1")
    p([0x48E7, 0xC0C0], "movem.l D0-D1/A0-A1, -(A7)")
    p([0x4CDF, 0x0303], "movem.l (A7)+, D0-D1/A0-A1")
    p([0x4E56, 0xFFF8], "link A6, #-$8")
    p([0x4E5E], "unlk A6")
    p([0x57C4], "seq D4")
    p([0xC142], "exg D0, D2")
    p([0x4840], "swap D0")
    p([0x4880], "ext.w D0")
    p([0x4AF8, 0x3010], "tas $3010.w")
    p([0x4E72, 0x2700], "stop #$2700")
    p.label("subroutine")
    p([0x4E75], "rts")
    check(p)
    return {
        "version": 1,
        "name": "flags-and-branches",
        "host": "flat",
        "memory": [
            {"address": 0, "data": vector_table({}, 0x8000, 0x1000).hex()},
            {"address": 0x1000, "data": p.data().hex()},
            {"address": DATA, "data": "0005000000000000000000000000000000000000"},
        ],
        "reset": True,
        "stop": {"max_steps": 200},
    }


def exceptions() -> dict:
    """Every exception an instruction can raise, a bus error, STOP, and a double bus fault."""
    p = Program(0x1000)
    p([0x7014], "moveq #$14, D0")
    p([0x4E40], "trap #$0")
    p([0x44FC, 0x0002], "move #$2, CCR")
    p([0x4E76], "trapv")
    p([0x41BC, 0x000A], "chk.w #$a, D0")
    p([0x80FC, 0x0000], "divu.w #$0, D0")
    p([0x4AFC], "illegal")
    p([0xA000], "dc.w $a000; opcode 1010")
    p([0xF000], "dc.w $f000; opcode 1111")
    # Trace: T set by ORI is not traced; the NOP after it is.
    p([0x007C, 0x8000], "ori #$8000, SR")
    p([0x4E71], "nop")
    # An address error, then a bus error; the group 0 handler resumes at A6.
    p([0x227C, *long(0x3001)], "movea.l #$3001, A1")
    p(absolute(0x4DF9, "after_address_error"), "lea $102c.l, A6", 3)
    p([0x3011], "move.w (A1), D0")
    p.label("after_address_error")
    p(absolute(0x4DF9, "after_bus_error"), "lea $1038.l, A6", 3)
    p([0x3039, *long(0xF00000)], "move.w $f00000.l, D0")
    p.label("after_bus_error")
    p([0x4E70], "reset")
    # User mode through MOVE to SR (A7 becomes USP); a privileged
    # instruction there; the handler returns to supervisor mode past it.
    p([0x41F9, *long(0x6000)], "lea $6000.l, A0")
    p([0x4E60], "move A0, USP")
    p([0x46FC, 0x0000], "move #$0, SR")
    p([0x46FC, 0x2700], "move #$2700, SR")
    # STOP, ended by a level 1 interrupt (the manifest's events).
    p([0x4E72, 0x2000], "stop #$2000")
    # A double bus fault: an address error with an odd stack pointer.
    p([0x2E7C, *long(0x7001)], "movea.l #$7001, A7")
    p([0x3011], "move.w (A1), D0")
    check(p)

    h = Program(0x2000)
    handlers = {}
    for name in ("trap", "trapv", "chk", "divide", "level_1"):
        h.label(name)
        h([0x4E73], "rte")
    for name in ("illegal", "line_a", "line_f"):
        h.label(name)
        h([0x54AF, 0x0002], "addq.l #2, ($2,A7)")  # past the word that was never executed
        h([0x4E73], "rte")
    h.label("trace")
    h([0x0257, 0x7FFF], "andi.w #$7fff, (A7)")  # T clear in the stacked SR
    h([0x4E73], "rte")
    h.label("privilege")
    h([0x58AF, 0x0002], "addq.l #4, ($2,A7)")  # past MOVE #imm, SR
    h([0x0057, 0x2000], "ori.w #$2000, (A7)")  # back in supervisor mode
    h([0x4E73], "rte")
    h.label("group_0")
    h([0x4FEF, 0x000E], "lea ($e,A7), A7")  # drop the seven-word frame
    h([0x4ED6], "jmp (A6)")
    names, _ = h.layout()
    check(h)
    for vector, name in ((32, "trap"), (7, "trapv"), (6, "chk"), (5, "divide"), (25, "level_1"),
                         (4, "illegal"), (10, "line_a"), (11, "line_f"), (9, "trace"),
                         (8, "privilege"), (3, "group_0"), (2, "group_0")):  # fmt: skip
        handlers[vector] = names[name]
    manifest = {
        "version": 1,
        "name": "exceptions",
        "host": "flat",
        "memory": [
            {"address": 0, "data": vector_table(handlers, 0x8000, 0x1000).hex()},
            {"address": 0x1000, "data": p.data().hex()},
            {"address": 0x2000, "data": h.data().hex()},
        ],
        "reset": True,
        "bus_error": [{"address": 0xF00000, "length": 0x10}],
        "stop": {"max_steps": 300},
    }
    # The level 1 request comes three idle steps into the STOP and is
    # withdrawn after the interrupt boundary, as a device acknowledges it.
    stop = idle_step(manifest)
    manifest["events"] = [
        {"at_step": stop + 3, "kind": "ipl", "level": 1},
        {"at_step": stop + 4, "kind": "ipl", "level": 0},
    ]
    return manifest


def tas_drop() -> dict:
    """TAS on a bus that never completes its write cycle (the Genesis)."""
    p = Program(0x1000)
    p([0x4AF8, DATA], "tas $3000.w")
    p([0x1038, DATA], "move.b $3000.w, D0")
    p([0x7205], "moveq #$5, D1")
    p([0x4AC1], "tas D1")  # a register: no bus cycle to drop
    p([0x4AF8, DATA + 2], "tas $3002.w")
    p([0x4E72, 0x2700], "stop #$2700")
    check(p)
    return {
        "version": 1,
        "name": "tas-drop",
        "host": "flat",
        "memory": [
            {"address": 0x1000, "data": p.data().hex()},
            {"address": DATA, "data": "05008000"},
        ],
        "initial": {"pc": 0x1000, "ssp": 0x8000},
        "tas_write": "drop",
        "stop": {"max_steps": 20},
    }


# -- interrupt scenarios (tests/test_interrupts.py, docs/validation.md rung 6) ---

NOPS = 0x40  # a run of NOPs at $1000 for scenarios that only need time to pass


def _interrupt_manifest(name: str, program: Program, handlers: Program, vectors: dict[str, int],
                        *, sr: int = 0x2000, events: list[dict], max_steps: int,
                        **extra) -> dict:  # fmt: skip
    check(program)
    check(handlers)
    names, _ = handlers.layout()
    table = {vector: names[label] for label, vector in vectors.items()}
    return {
        "version": 1,
        "name": name,
        "host": "flat",
        "memory": [
            {"address": 0, "data": vector_table(table, 0x8000, 0x1000).hex()},
            {"address": 0x1000, "data": program.data().hex()},
            {"address": 0x2000, "data": handlers.data().hex()},
        ],
        "initial": {"pc": 0x1000, "ssp": 0x8000, "sr": sr},
        **extra,
        "events": events,
        "stop": {"max_steps": max_steps},
    }


def _nops(count: int = NOPS, then_stop: bool = True) -> Program:
    p = Program(0x1000)
    for _ in range(count):
        p([0x4E71], "nop")
    if then_stop:
        p([0x4E72, 0x2700], "stop #$2700")
    return p


def _rte_handlers(*labels: str) -> Program:
    h = Program(0x2000)
    for label in labels:
        h.label(label)
        h([0x4E73], "rte")
    return h


def interrupt_scenarios() -> list[dict]:
    out = []
    # A level above the mask is taken at the next boundary; the device drops
    # its request once acknowledged.
    out.append(_interrupt_manifest(
        "level-above-mask-taken", _nops(8), _rte_handlers("level_4"), {"level_4": 28},
        sr=0x2300, max_steps=20,
        events=[{"at_step": 1, "kind": "ipl", "level": 4},
                {"at_step": 2, "kind": "ipl", "level": 0}],
    ))  # fmt: skip
    # A level at the mask is held until MOVE to SR lowers the mask.
    p = Program(0x1000)
    p([0x4E71], "nop")
    p([0x4E71], "nop")
    p([0x46FC, 0x2300], "move #$2300, SR")
    p([0x4E71], "nop")
    p([0x4E72, 0x2700], "stop #$2700")
    out.append(_interrupt_manifest(
        "level-at-mask-held-until-mask-lowered", p, _rte_handlers("level_4"), {"level_4": 28},
        sr=0x2400, max_steps=20,
        events=[{"at_step": 1, "kind": "ipl", "level": 4},
                {"at_step": 4, "kind": "ipl", "level": 0}],
    ))  # fmt: skip
    # Level 7 is an edge: taken with the mask at 7, once while held, and
    # again on the next 0-to-7 edge.
    out.append(_interrupt_manifest(
        "level-seven-edge-ignores-mask", _nops(12), _rte_handlers("level_7"), {"level_7": 31},
        sr=0x2700, max_steps=30,
        events=[{"at_step": 1, "kind": "ipl", "level": 7},
                {"at_step": 6, "kind": "ipl", "level": 0},
                {"at_step": 8, "kind": "ipl", "level": 7}],
    ))  # fmt: skip
    # The acknowledge cycle's three answers besides the autovector.
    for name, answer, vector in (("acknowledge-vectored", 64, 64),
                                 ("acknowledge-spurious", "spurious", 24),
                                 ("acknowledge-uninitialized-vector-15", 15, 15)):  # fmt: skip
        out.append(_interrupt_manifest(
            name, _nops(6), _rte_handlers("handler"), {"handler": vector},
            max_steps=16, acknowledge={"4": answer},
            events=[{"at_step": 2, "kind": "ipl", "level": 4},
                    {"at_step": 3, "kind": "ipl", "level": 0}],
        ))  # fmt: skip
    # Trace outranks a pending interrupt (UM 6.3.8): the traced NOP's trace
    # exception is taken first, and the interrupt enters before the trace
    # handler's first instruction, with T clear.
    p = Program(0x1000)
    p([0x007C, 0x8000], "ori #$8000, SR")
    p([0x4E71], "nop")
    p([0x4E71], "nop")
    p([0x4E72, 0x2700], "stop #$2700")
    h = Program(0x2000)
    h.label("trace")
    h([0x0257, 0x7FFF], "andi.w #$7fff, (A7)")
    h([0x4E73], "rte")
    h.label("level_4")
    h([0x4E73], "rte")
    out.append(_interrupt_manifest(
        "trace-before-pending-interrupt", p, h, {"trace": 9, "level_4": 28},
        max_steps=20,
        events=[{"at_step": 2, "kind": "ipl", "level": 4},
                {"at_step": 4, "kind": "ipl", "level": 0}],
    ))  # fmt: skip
    # STOP waits for a level above its new mask, then resumes after itself.
    p = Program(0x1000)
    p([0x4E72, 0x2300], "stop #$2300")
    p([0x4E71], "nop")
    p([0x4E72, 0x2700], "stop #$2700")
    out.append(_interrupt_manifest(
        "stop-waits-for-level-above-new-mask", p, _rte_handlers("level_3", "level_4"),
        {"level_3": 27, "level_4": 28}, max_steps=20,
        events=[{"at_step": 2, "kind": "ipl", "level": 3},
                {"at_step": 4, "kind": "ipl", "level": 4},
                {"at_step": 6, "kind": "ipl", "level": 0}],
    ))  # fmt: skip
    # STOP in user mode is a privilege violation; the handler returns past it.
    p = Program(0x1000)
    p([0x46FC, 0x0000], "move #$0, SR")
    p([0x4E72, 0x2700], "stop #$2700")
    p([0x4E71], "nop")
    h = Program(0x2000)
    h.label("privilege")
    h([0x58AF, 0x0002], "addq.l #4, ($2,A7)")
    h([0x0057, 0x2700], "ori.w #$2700, (A7)")
    h([0x4E73], "rte")
    p.label("end")
    p([0x4E72, 0x2700], "stop #$2700")
    out.append(_interrupt_manifest(
        "stop-in-user-mode-privilege-violation", p, h, {"privilege": 8},
        max_steps=20, events=[],
    ))  # fmt: skip
    # A traced STOP takes the trace exception instead of stopping for good.
    p = Program(0x1000)
    p([0x007C, 0x8000], "ori #$8000, SR")
    p([0x4E72, 0xA000], "stop #-$6000")
    p([0x4E71], "nop")
    p([0x4E72, 0x2700], "stop #$2700")
    h = Program(0x2000)
    h.label("trace")
    h([0x0257, 0x7FFF], "andi.w #$7fff, (A7)")
    h([0x4E73], "rte")
    out.append(_interrupt_manifest(
        "traced-stop-takes-trace", p, h, {"trace": 9}, sr=0x2700, max_steps=20, events=[],
    ))  # fmt: skip
    out.extend(autovector_phases())
    return out


def autovector_phases() -> list[dict]:
    """An autovectored interrupt at each of the ten phases of the E clock.

    The acknowledge cycle begins 10 clocks into the interrupt boundary, so
    its phase is the clock at the boundary mod 10.  Every bus access and
    internal step costs an even number of clocks, and only the E-clock wait
    of an autovector can change the clock's parity, so one run cannot reach
    every phase; each manifest instead starts its clock where one NOP brings
    the boundary to its phase.
    """
    out = []
    for phase in range(10):
        manifest = _interrupt_manifest(
            f"autovector-e-clock-phase-{phase}", _nops(4), _rte_handlers("level_4"),
            {"level_4": 28}, max_steps=10,
            events=[{"at_step": 1, "kind": "ipl", "level": 4},
                    {"at_step": 2, "kind": "ipl", "level": 0}],
        )  # fmt: skip
        manifest["initial"]["clock"] = (phase - 4) % 10 + 10
        assert _last_phase(manifest) == phase
        out.append(manifest)
    return out


def _last_phase(manifest: dict) -> int:
    from m68000_python.conformance import ConformanceHost, _apply_event

    parsed = manifest_from_dict(manifest)
    host = ConformanceHost(parsed)
    events = list(parsed.events)
    for step in range(3):  # the NOP, then the interrupt
        while events and events[0].at_step == step:
            _apply_event(host.cpu, events.pop(0))
        host.cpu.step()
    return host.cpu.last_acknowledge_phase


def idle_step(manifest: dict) -> int:
    """The step at which a run with no events stops idle (inside its STOP)."""
    result: list = []
    for _ in trace_manifest(manifest_from_dict(manifest), result=result):
        pass
    assert result[0].reason == "idle", result[0]
    return result[0].steps


# -- writing ---------------------------------------------------------------------


def manifests() -> dict[Path, dict]:
    out = {HERE / f"{m['name']}.json": m for m in (flags_and_branches(), exceptions(), tas_drop())}
    out.update({INTERRUPTS / f"{m['name']}.json": m for m in interrupt_scenarios()})
    return out


def manifest_text(manifest: dict) -> str:
    return json.dumps(manifest, indent=2) + "\n"


def trace_text(manifest: dict) -> str:
    stream = io.StringIO()
    write_trace(trace_manifest(manifest_from_dict(manifest)), stream)
    return stream.getvalue()


if __name__ == "__main__":
    INTERRUPTS.mkdir(exist_ok=True)
    for path, manifest in manifests().items():
        path.write_text(manifest_text(manifest), encoding="utf-8")
        path.with_suffix(".jsonl").write_text(trace_text(manifest), encoding="utf-8")
        print(f"{path.relative_to(HERE)}: written with its trace")
