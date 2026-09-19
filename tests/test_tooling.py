"""State capture, the debug session, traces, the command debugger, and the CLI."""

from __future__ import annotations

import io

import pytest
from conftest import make

from m68000_python import (
    BoundaryKind,
    CommandDebugger,
    CommandError,
    CPUState,
    DebugSession,
    StopReason,
    first_trace_divergence,
    read_trace,
    write_trace,
)
from m68000_python.__main__ import main
from m68000_python.disasm import disassemble, disassemble_bytes

NOP = 0x4E71
PROGRAM = [
    0x7005,  # moveq #5, D0
    0x5380,  # subq.l #1, D0
    0x66FC,  # bne $1002
    0x33C0, 0x0000, 0x3000,  # move.w D0, $3000.l
    0x4E72, 0x2700,  # stop #$2700
]  # fmt: skip


def session(**kwargs):
    cpu, bus = make(PROGRAM)
    return cpu, bus, DebugSession(cpu, peek_word=bus.word, **kwargs)


def test_capture_and_restore_round_trip():
    cpu, _bus = make(PROGRAM)
    for _ in range(4):
        cpu.step()
    saved = cpu.capture_state()
    for _ in range(3):
        cpu.step()
    assert cpu.capture_state() != saved
    cpu.restore_state(saved)
    assert cpu.capture_state() == saved


def test_restore_puts_each_stack_pointer_in_its_place():
    cpu, _ = make(PROGRAM)
    state = cpu.capture_state()
    user = CPUState(**{**_fields(state), "sr": 0x0000, "usp": 0x1234, "ssp": 0x5678})
    cpu.restore_state(user)
    assert cpu.R[15] == 0x1234 and cpu.ssp == 0x5678
    cpu.set_sr(0x2000)
    assert cpu.R[15] == 0x5678 and cpu.usp == 0x1234


def _fields(state: CPUState) -> dict:
    return {name: getattr(state, name) for name in state.__dataclass_fields__}


@pytest.mark.parametrize(
    "change", [{"sr": 0x4000}, {"ipl": 8}, {"d": (0,) * 7}, {"ir": 0x10000}, {"stopped": 1}]
)
def test_state_rejects_impossible_values(change):
    with pytest.raises(ValueError):
        CPUState(**change)


def test_session_steps_and_names_boundaries():
    _cpu, _bus, debug = session()
    record = debug.step()
    assert record.kind is BoundaryKind.INSTRUCTION
    assert record.instruction.text == "moveq #$5, D0"
    assert record.before.pc == 0x1000 and record.after.pc == 0x1002
    assert record.cycles == 4


def test_run_stops_at_breakpoint_watchpoint_and_stop():
    cpu, bus, debug = session(track_accesses=True)
    debug.add_breakpoint(0x1006)
    result = debug.run(max_steps=100)
    assert result.reason is StopReason.BREAKPOINT and result.state.pc == 0x1006
    debug.add_watchpoint(0x3001, "w")
    result = debug.run(max_steps=100)
    assert result.reason is StopReason.WATCHPOINT
    assert result.hits == (("w", 0x3000, 0, 2),)
    result = debug.run(max_steps=100)
    assert result.reason is StopReason.STOPPED
    debug.close()
    assert cpu.read_word == bus.read_word


def test_interrupt_boundary_is_named():
    cpu, bus, debug = session()
    for vector in range(256):
        bus.set_long(vector * 4, 0x4000)
    bus.load(0x4000, [NOP] * 4)
    cpu.set_sr(0x2000)
    cpu.set_ipl(3)
    assert debug.step().kind is BoundaryKind.INTERRUPT


def test_trace_round_trip_and_divergence():
    _, _, debug = session(track_accesses=True)
    records = [debug.step() for _ in range(6)]
    stream = io.StringIO()
    assert write_trace(records, stream) == 6
    stream.seek(0)
    again = list(read_trace(stream))
    assert first_trace_divergence(records, again) is None
    _, _, other = session(track_accesses=True)
    other.cpu.R[0] = 7
    divergence = first_trace_divergence(records, [other.step() for _ in range(6)])
    assert divergence is not None and divergence.position == 0


def test_command_debugger():
    _, _, debug = session(track_accesses=True)
    commands = CommandDebugger(debug)
    assert commands.execute("step 2").lines[1].startswith("001002  subq.l #1, D0")
    assert "PC=001004" in "\n".join(commands.execute("registers").lines)
    commands.execute("break 1006")
    assert commands.execute("run").lines[0].startswith("breakpoint")
    assert commands.execute("disassemble 1006 1").lines == [
        "001006  33C0 0000 3000           move.w D0, $3000.l"
    ]
    assert commands.execute("quit").quit
    with pytest.raises(CommandError):
        commands.execute("frobnicate")


def test_cli_batch(tmp_path, capsys):
    image = tmp_path / "program.bin"
    image.write_bytes(b"".join(word.to_bytes(2, "big") for word in PROGRAM))
    main(["--load", f"{image}@1000", "--pc", "1000", "-c", "step 3", "--batch"])
    out = capsys.readouterr().out
    assert "bne $1002" in out and "moveq #$5, D0" in out


def test_every_word_disassembles():
    words = {}

    def read_word(address: int) -> int:
        return words.get(address, 0x1234)

    for opcode in range(0x10000):
        words[0x1000] = opcode
        instruction = disassemble(read_word, 0x1000)
        assert instruction.words[0] == opcode
        assert disassemble_bytes(instruction.data, 0x1000) == instruction


@pytest.mark.parametrize(
    "words,text",
    [
        ([0x6000, 0x000C], "bra $40e"),
        ([0x4FF8, 0xFF00], "lea $ff00.w, A7"),
        ([0x46FC, 0x2700], "move #$2700, SR"),
        ([0x51C8, 0xFFFC], "dbra D0, $3fe"),
        ([0x48E7, 0xFFFE], "movem.l D0-D7/A0-A6, -(A7)"),
        ([0x4CDF, 0x7FFF], "movem.l (A7)+, D0-D7/A0-A6"),
        ([0x3030, 0x1804], "move.w ($4,A0,D1.l), D0"),
        ([0xE1A8], "lsl.l D0, D0"),
    ],
)
def test_texts_in_mame_form(words, text):
    data = b"".join(word.to_bytes(2, "big") for word in words)
    assert disassemble_bytes(data, 0x400).text == text
