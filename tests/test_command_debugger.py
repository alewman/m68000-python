"""The line-command debugger: every command, the number grammar, the text-stream loop."""

from __future__ import annotations

from io import StringIO

import pytest
from conftest import make

from m68000_python import CommandDebugger, CommandError, CommandResult, DebugSession
from m68000_python.console import parse_number

NOP = 0x4E71
PROGRAM = [
    0x7005,  # $1000 moveq #5, D0
    0x5380,  # $1002 subq.l #1, D0
    0x66FC,  # $1004 bne $1002
    0x33C0, 0x0000, 0x3000,  # $1006 move.w D0, $3000.l
    0x4E72, 0x2700,  # $100C stop #$2700
]  # fmt: skip


def debugger(program=PROGRAM, *, track: bool = False, peek: bool = True):
    cpu, bus = make(program)
    session = DebugSession(
        cpu, peek_word=bus.word if peek else None, history_limit=16, track_accesses=track
    )
    return cpu, bus, CommandDebugger(session)


def test_registers_render_the_whole_processor_state() -> None:
    cpu, _, commands = debugger()
    commands.execute("step")
    cpu.set_ipl(2)

    lines = commands.execute("registers").lines

    assert lines[0] == "D0=00000005 D1=00000000 D2=00000000 D3=00000000"
    assert lines[2] == "A0=00000000 A1=00000000 A2=00000000 A3=00000000"
    assert lines[3].endswith("A7=00008000")
    assert lines[4] == "PC=001002 SR=2700 .S..... I=7"
    assert lines[5] == "USP=00000000 SSP=00008000 IPL=2 clock=46"  # reset 42 + moveq 4
    assert commands.execute("r").lines == lines == commands.execute("regs").lines


def test_step_run_break_delete_and_history_share_the_session() -> None:
    cpu, _, commands = debugger()

    assert commands.execute("step 2").lines == (
        "001000  moveq #$5, D0                               4 clocks",
        "001002  subq.l #1, D0                               8 clocks",
    )
    assert commands.execute("break $1006").lines == ("breakpoints: 001006",)
    run = commands.execute("run 100").lines
    assert run[0] == "breakpoint after 9 steps, 80 clocks"  # 5 x bne (4 taken), 4 x subq
    assert run[5].startswith("PC=001006")
    assert cpu.PC == 0x1006
    assert len(commands.execute("history 3").lines) == 3
    assert commands.execute("history 0").lines == ()
    assert commands.execute("delete 0x1006").lines == ()
    assert commands.execute("c").lines[0] == "stopped after 2 steps, 20 clocks"
    assert commands.execute("registers").lines[5].endswith("STOPPED")


def test_a_stopped_processor_shows_in_the_boundary_description() -> None:
    _, _, commands = debugger()
    commands.execute("run")
    assert commands.execute("step").lines == ("00100C  <stopped_idle> 4 clocks",)


def test_disassemble_and_memory_read_through_the_side_effect_free_peek() -> None:
    _, _, commands = debugger()

    assert commands.execute("disassemble 0x1006 1").lines == (
        "001006  33C0 0000 3000           move.w D0, $3000.l",
    )
    assert len(commands.execute("d").lines) == 8  # from PC, eight instructions
    assert commands.execute("dis $1000 2").lines[1].startswith("001002  5380")
    memory = commands.execute("memory 0x1000 4").lines
    assert memory == ("001000  70 05 53 80 66 fc 33 c0 00 00 30 00 4e 72 27 00  p.S.f.3...0.Nr'.",)
    assert len(commands.execute("m 0 64").lines) == 4
    with pytest.raises(CommandError, match="out of range"):
        commands.execute("memory 0 5000")


def test_commands_needing_peek_fail_explicitly_without_it() -> None:
    _, _, commands = debugger(peek=False)
    with pytest.raises(CommandError, match="no peek_word"):
        commands.execute("disassemble")
    with pytest.raises(CommandError, match="no peek_word"):
        commands.execute("memory 0")
    assert commands.execute("step").lines == (f"001000  {'(opcode 7005)':40} {4:4} clocks",)


def test_set_writes_every_register_kind_through_the_processor_api() -> None:
    cpu, _, commands = debugger()
    commands.execute("set d1 0x12345678")
    commands.execute("set a2 $100")
    commands.execute("set usp 4096")
    commands.execute("set ssp 0x7000")
    assert (cpu.R[1], cpu.R[10], cpu.usp, cpu.R[15]) == (0x12345678, 0x100, 4096, 0x7000)
    commands.execute("set pc 0x1004")
    assert cpu.PC == 0x1004
    commands.execute("set sr 0")
    assert cpu.SR == 0 and cpu.R[15] == 4096  # user mode: A7 is now the USP
    with pytest.raises(CommandError, match="no register"):
        commands.execute("set q 1")
    with pytest.raises(CommandError, match="16 bits"):
        commands.execute("set sr 0x10000")
    with pytest.raises(CommandError, match="needs a register"):
        commands.execute("set d0")


def test_ipl_sets_the_interrupt_level() -> None:
    cpu, _, commands = debugger()
    assert commands.execute("ipl 4").lines == ()
    assert cpu.ipl == 4
    with pytest.raises(CommandError, match="out of range"):
        commands.execute("ipl 8")


def test_watch_and_unwatch_need_tracking() -> None:
    _, _, commands = debugger(track=True)
    assert commands.execute("watch $3001 w").lines == ()
    stopped = commands.execute("run").lines
    assert stopped[0] == "watchpoint after 12 steps, 108 clocks"
    assert stopped[1] == "  w 003000 = 0"
    assert commands.execute("unwatch 0x3001").lines == ()
    with pytest.raises(CommandError, match="kind"):
        commands.execute("watch 0x3000 x")
    _, _, plain = debugger()
    with pytest.raises(CommandError, match="track_accesses"):
        plain.execute("watch 0x3000")
    with pytest.raises(CommandError, match="needs an address"):
        plain.execute("watch")


def test_help_quit_and_unknown_commands() -> None:
    _, _, commands = debugger()
    text = "\n".join(commands.execute("help").lines)
    for command in ("registers", "step", "run", "break", "delete", "watch", "unwatch",
                    "disassemble", "memory", "set", "ipl", "history", "help", "quit"):  # fmt: skip
        assert command in text
    for word in ("quit", "q", "exit"):
        assert commands.execute(word).quit
    assert commands.execute("").lines == ()
    with pytest.raises(CommandError, match="unknown command 'frobnicate'"):
        commands.execute("frobnicate")


@pytest.mark.parametrize("command", ["step 0", "run 0", "step x", "break", "break 0x1000000"])
def test_invalid_arguments_raise_command_errors(command: str) -> None:
    _, _, commands = debugger()
    with pytest.raises(CommandError):
        commands.execute(command)


@pytest.mark.parametrize(
    ("text", "value"), [("10", 10), ("$10", 16), ("0x10", 16), ("0X1f", 31), (" 7 ", 7)]
)
def test_numbers_are_decimal_or_prefixed_hexadecimal(text: str, value: int) -> None:
    assert parse_number(text) == value


@pytest.mark.parametrize("text", ["#10", "1F", "-1", "", "$", "0x", "1.5"])
def test_other_number_forms_are_rejected(text: str) -> None:
    with pytest.raises(CommandError, match=r"not a number|out of range"):
        parse_number(text)


def test_numbers_respect_the_maximum() -> None:
    assert parse_number("$ff", maximum=0xFF) == 0xFF
    with pytest.raises(CommandError, match=r"out of range 0\.\.0xff"):
        parse_number("$100", "address", maximum=0xFF)


def test_interactive_loop_reports_errors_and_leaves_on_quit_or_end_of_input() -> None:
    _, _, commands = debugger()
    output = StringIO()
    commands.interact(StringIO("bad\nstep\nquit\nstep\n"), output)
    text = output.getvalue()
    assert text.startswith("m68000> error: unknown command 'bad' (try help)\nm68000> 001000  moveq")
    assert text.count("m68000> ") == 3

    output = StringIO()
    commands.interact(StringIO("step\n"), output)
    assert output.getvalue().endswith("m68000> ")


def test_command_result_is_frozen_and_validated() -> None:
    result = CommandResult(("one",), quit=True)
    with pytest.raises(AttributeError):
        result.quit = False  # type: ignore[misc]
    with pytest.raises(ValueError, match="tuple of strings"):
        CommandResult(["one"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="bool"):
        CommandResult(quit=1)  # type: ignore[arg-type]
