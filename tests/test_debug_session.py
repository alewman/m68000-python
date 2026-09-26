"""DebugSession: stepping, breakpoints, watchpoints, history, targets, evidence values."""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import make

from m68000_python import (
    BoundaryKind,
    DebugSession,
    DebugTarget,
    RunResult,
    StopReason,
    next_boundary,
)

NOP = 0x4E71
PROGRAM = [
    0x7005,  # $1000 moveq #5, D0
    0x5380,  # $1002 subq.l #1, D0
    0x66FC,  # $1004 bne $1002
    0x33C0, 0x0000, 0x3000,  # $1006 move.w D0, $3000.l
    0x4E72, 0x2700,  # $100C stop #$2700
]  # fmt: skip


def session(program=PROGRAM, **options):
    cpu, bus = make(program)
    return cpu, bus, DebugSession(cpu, peek_word=bus.word, **options)


def test_step_records_disassembly_state_delta_and_totals() -> None:
    cpu, _, debug = session()

    record = debug.step()

    assert record.sequence == 0
    assert record.kind is BoundaryKind.INSTRUCTION
    assert record.instruction is not None
    assert record.instruction.text == "moveq #$5, D0"
    assert (record.before.pc, record.after.pc, record.after.d[0], record.cycles) == (
        0x1000,
        0x1002,
        5,
        4,
    )
    assert (debug.total_steps, debug.total_instructions, debug.total_cycles) == (1, 1, 4)
    assert debug.history == (record,)
    assert cpu.PC == 0x1002


def test_breakpoint_stops_before_the_instruction_and_step_crosses_it() -> None:
    cpu, _, debug = session()
    debug.add_breakpoint(0x1002)

    result = debug.run(max_steps=100)

    assert result.reason is StopReason.BREAKPOINT
    assert (result.steps, result.instructions, result.cycles, result.state.pc) == (1, 1, 4, 0x1002)
    assert cpu.PC == 0x1002
    assert debug.step().after.pc == 0x1004
    debug.remove_breakpoint(0x1002)
    assert debug.run(max_steps=3).reason is StopReason.STEP_LIMIT


def test_a_breakpoint_at_the_current_pc_does_not_stop_a_run_before_it_starts() -> None:
    _, _, debug = session()
    debug.add_breakpoint(0x1000)
    result = debug.run(max_steps=1)
    assert (result.reason, result.steps) == (StopReason.STEP_LIMIT, 1)


def test_stop_ends_a_run_and_idle_steps_can_be_consumed_explicitly() -> None:
    cpu, _, debug = session()

    result = debug.run(max_steps=100)

    assert result.reason is StopReason.STOPPED
    assert result.state.stopped and cpu.stopped
    assert result.instructions == 1 + 5 * 2 + 1 + 1  # moveq, 5 x (subq, bne), move, stop
    assert next_boundary(cpu.capture_state()) is BoundaryKind.STOPPED_IDLE
    idle = debug.run(max_steps=2, stop_on_stop=False)
    assert (idle.reason, idle.steps, idle.instructions, idle.cycles) == (
        StopReason.STEP_LIMIT,
        2,
        0,
        8,
    )
    assert all(record.kind is BoundaryKind.STOPPED_IDLE for record in debug.history[-2:])


def test_a_halted_processor_is_reported_and_can_be_idled() -> None:
    cpu, _, debug = session()
    cpu.halted = True  # what a double bus fault leaves behind

    assert next_boundary(cpu.capture_state()) is BoundaryKind.HALTED_IDLE
    assert debug.run(max_steps=5).reason is StopReason.HALTED
    record = debug.run(max_steps=1, stop_on_halt=False).last_record
    assert record is not None
    assert (record.kind, record.instruction, record.cycles) == (BoundaryKind.HALTED_IDLE, None, 4)


def test_trace_and_interrupt_boundaries_are_named_and_carry_no_instruction() -> None:
    cpu, bus, debug = session([NOP] * 8)
    for vector in range(256):
        bus.set_long(vector * 4, 0x3000)
    bus.load(0x3000, [NOP] * 8)
    cpu.SR = 0xA000  # T set, S set, mask 0
    debug.step()
    assert next_boundary(cpu.capture_state()) is BoundaryKind.TRACE
    trace = debug.step()
    assert (trace.kind, trace.instruction, trace.cycles, trace.after.pc) == (
        BoundaryKind.TRACE,
        None,
        34,
        0x3000,
    )
    cpu.set_ipl(3)
    assert next_boundary(cpu.capture_state()) is BoundaryKind.INTERRUPT
    interrupt = debug.step()
    assert (interrupt.kind, interrupt.instruction, interrupt.after.pc) == (
        BoundaryKind.INTERRUPT,
        None,
        0x3000,
    )
    assert debug.total_instructions == 1


def test_cycle_budget_is_checked_after_an_atomic_step() -> None:
    _, _, debug = session()
    result = debug.run(max_steps=10, max_cycles=3)
    assert (result.reason, result.steps, result.cycles) == (StopReason.CYCLE_LIMIT, 1, 4)


def test_history_is_bounded_clearable_and_optionally_disabled() -> None:
    _, _, debug = session(history_limit=2)
    debug.run(max_steps=3)

    assert [record.sequence for record in debug.history] == [1, 2]
    assert [record.sequence for record in debug.iter_history(newest_first=True)] == [2, 1]
    debug.clear_history()
    assert debug.history == ()

    _, _, disabled = session(history_limit=0)
    record = disabled.step()
    assert (record.sequence, disabled.history, disabled.total_steps) == (0, (), 1)


def test_session_without_peek_retains_execution_control() -> None:
    cpu, _ = make(PROGRAM)
    debug = DebugSession(cpu)
    record = debug.step()
    assert record.instruction is None
    assert record.after.pc == 0x1002


def test_debug_target_is_a_runtime_checkable_structural_protocol() -> None:
    cpu, _ = make(PROGRAM)
    assert isinstance(cpu, DebugTarget)
    assert not isinstance(object(), DebugTarget)
    with pytest.raises(TypeError, match="step"):
        DebugSession(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="peek_word"):
        DebugSession(cpu, peek_word=5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="history_limit"):
        DebugSession(cpu, history_limit=-1)


def test_a_board_shaped_target_steps_its_devices_around_the_cpu() -> None:
    cpu, bus = make(PROGRAM)

    class Board:
        def __init__(self) -> None:
            self.cpu = cpu
            self.ticks = 0

        def step(self) -> int:
            self.ticks += 1
            return self.cpu.step()

        def capture_state(self):
            return self.cpu.capture_state()

    board = Board()
    debug = DebugSession(board, peek_word=bus.word, track_accesses=True)
    assert debug.cpu is cpu
    record = debug.step()
    assert board.ticks == 1
    assert record.accesses == (("r", 0x1004, 0x66FC, 2),)


def test_tracked_steps_record_every_bus_access_in_order() -> None:
    _, _, debug = session(track_accesses=True)
    assert debug.tracking
    records = [debug.step() for _ in range(4)]
    assert [record.accesses for record in records] == [
        (("r", 0x1004, 0x66FC, 2),),  # moveq: the closing prefetch
        (("r", 0x1006, 0x33C0, 2),),  # subq.l
        (("r", 0x1002, 0x5380, 2), ("r", 0x1004, 0x66FC, 2)),  # bne taken: the refill
        (("r", 0x1006, 0x33C0, 2),),
    ]


def test_untracked_steps_carry_no_accesses_and_close_gives_the_bus_back() -> None:
    cpu, bus, debug = session()
    assert not debug.tracking
    assert debug.step().accesses is None

    cpu, bus, tracked = session(track_accesses=True)
    assert cpu.read_word is not bus.read_word
    tracked.close()
    assert (cpu.read_byte, cpu.read_word, cpu.write_byte, cpu.write_word) == (
        bus.read_byte,
        bus.read_word,
        bus.write_byte,
        bus.write_word,
    )
    assert not tracked.tracking
    assert tracked.step().accesses is None


@pytest.mark.parametrize(("kind", "stops"), [("w", True), ("r", False), ("rw", True)])
def test_watchpoint_stops_after_the_step_that_touches_the_byte(kind: str, stops: bool) -> None:
    _, _, debug = session(track_accesses=True)
    debug.add_watchpoint(0x3001, kind)  # the low byte of the word MOVE.W writes at $3000

    result = debug.run(max_steps=100)

    if stops:
        assert result.reason is StopReason.WATCHPOINT
        assert result.hits == (("w", 0x3000, 0, 2),)
        assert result.state.pc == 0x100C
    else:
        assert result.reason is StopReason.STOPPED
        assert result.hits == ()


def test_watchpoints_need_tracking_a_valid_kind_and_a_24_bit_address() -> None:
    _, _, plain = session()
    with pytest.raises(ValueError, match="track_accesses"):
        plain.add_watchpoint(0x3000)
    _, _, tracked = session(track_accesses=True)
    with pytest.raises(ValueError, match="kind"):
        tracked.add_watchpoint(0x3000, "x")
    with pytest.raises(ValueError, match=r"0x000000\.\.0xFFFFFF"):
        tracked.add_watchpoint(0x1000000)
    with pytest.raises(ValueError, match=r"0x000000\.\.0xFFFFFF"):
        tracked.add_breakpoint(-1)
    tracked.add_watchpoint(0x3000)
    tracked.remove_watchpoint(0x3000)
    assert tracked.run(max_steps=100).reason is StopReason.STOPPED


def test_public_debug_values_reject_invalid_construction() -> None:
    _, _, debug = session()
    record = debug.step()

    with pytest.raises(ValueError, match="sequence"):
        replace(record, sequence=-1)
    with pytest.raises(ValueError, match="instruction boundaries"):
        replace(record, kind=BoundaryKind.TRACE)
    with pytest.raises(ValueError, match="cycles"):
        replace(record, cycles=0)
    with pytest.raises(ValueError, match="Instruction"):
        replace(record, instruction="moveq")
    with pytest.raises(ValueError, match="accesses"):
        replace(record, accesses=(("x", 0, 0, 1),))
    with pytest.raises(ValueError, match="accesses"):
        replace(record, accesses=[("r", 0, 0, 1)])
    assert RunResult(StopReason.STEP_LIMIT, 1, 1, 4, record.after, record).hits == ()


@pytest.mark.parametrize(
    ("arguments", "message"),
    [({"max_steps": 0}, "max_steps"), ({"max_steps": 1, "max_cycles": 0}, "max_cycles")],
)
def test_run_rejects_invalid_or_unbounded_limits(arguments, message: str) -> None:
    _, _, debug = session()
    with pytest.raises(ValueError, match=message):
        debug.run(**arguments)


def test_a_target_step_must_return_a_positive_clock_count() -> None:
    class Broken:
        def step(self) -> int:
            return 0

        def capture_state(self):
            return make([NOP])[0].capture_state()

    with pytest.raises(ValueError, match="positive cycle count"):
        DebugSession(Broken()).step()
