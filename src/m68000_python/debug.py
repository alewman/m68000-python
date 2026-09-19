"""Dependency-free execution control and structured debugging records.

``DebugSession`` drives an existing CPU -- any object with ``step()`` and
``capture_state()`` -- one boundary at a time, with execute breakpoints,
bounded runs, a history ring and, optionally, memory-access tracking and
watchpoints.  It never changes what the core does.  See docs/debug-session.md.
"""

from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from m68000_python.disasm import Instruction, WordReader, disassemble
from m68000_python.state import CPUState


@runtime_checkable
class DebugTarget(Protocol):
    """The minimum a :class:`DebugSession` needs from a CPU."""

    def step(self) -> int:
        """Advance one instruction or exception boundary; return its clocks."""

    def capture_state(self) -> CPUState:
        """Capture the current CPU-owned state."""


class BoundaryKind(Enum):
    """What one ``step()`` did."""

    INSTRUCTION = "instruction"
    TRACE = "trace"  # the trace exception after a traced instruction
    INTERRUPT = "interrupt"  # an interrupt accepted
    STOPPED_IDLE = "stopped_idle"  # clocks spent inside STOP
    HALTED_IDLE = "halted_idle"  # clocks spent halted by a double bus fault


class StopReason(Enum):
    """Why a bounded run returned control."""

    BREAKPOINT = "breakpoint"  # before the instruction at a breakpoint
    WATCHPOINT = "watchpoint"  # after the step that touched a watched address
    STOPPED = "stopped"  # inside STOP with no interrupt able to end it
    HALTED = "halted"  # double bus fault; only reset leaves it
    STEP_LIMIT = "step_limit"
    CYCLE_LIMIT = "cycle_limit"


#: One bus access: ("r" or "w", address, value, size in bytes).
Access = tuple[str, int, int, int]


@dataclass(frozen=True, slots=True)
class StepRecord:
    """Immutable before/after evidence for one boundary."""

    sequence: int
    kind: BoundaryKind
    before: CPUState
    after: CPUState
    cycles: int
    instruction: Instruction | None
    #: Every bus access the step made, in order, when the session tracks
    #: accesses; ``None`` otherwise.
    accesses: tuple[Access, ...] | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if type(self.kind) is not BoundaryKind:
            raise ValueError("kind must be a BoundaryKind")
        if type(self.before) is not CPUState or type(self.after) is not CPUState:
            raise ValueError("before and after must be CPUState values")
        if type(self.cycles) is not int or self.cycles <= 0:
            raise ValueError("cycles must be a positive integer")
        if self.kind is not BoundaryKind.INSTRUCTION and self.instruction is not None:
            raise ValueError("only instruction boundaries carry an instruction")


@dataclass(frozen=True, slots=True)
class RunResult:
    """Summary of one bounded run."""

    reason: StopReason
    steps: int
    instructions: int
    cycles: int
    state: CPUState
    last_record: StepRecord | None
    #: For WATCHPOINT: the watched accesses that stopped the run.
    hits: tuple[Access, ...] = ()


def next_boundary(state: CPUState) -> BoundaryKind:
    """What the next ``step()`` will do, decided exactly as ``M68000CPU.step()`` decides it."""
    if state.halted:
        return BoundaryKind.HALTED_IDLE
    if state.trace_pending:
        return BoundaryKind.TRACE
    if state.ipl and (state.ipl > (state.sr >> 8) & 7 or (state.ipl == 7 and state.nmi_edge)):
        return BoundaryKind.INTERRUPT
    if state.stopped:
        return BoundaryKind.STOPPED_IDLE
    return BoundaryKind.INSTRUCTION


class DebugSession:
    """Control an existing CPU without modifying its execution core.

    ``peek_word`` must be side-effect-free (the host's memory, not its bus);
    without it stepping and breakpoints work but records carry no
    disassembly.  ``track_accesses=True`` re-attaches the CPU's four bus
    callables through wrappers that record every access and enable
    watchpoints; :meth:`close` puts the originals back.

    The target may be a whole board rather than a bare CPU: an object whose
    ``step()`` runs its devices around one CPU step and whose ``cpu``
    attribute is the processor.
    """

    def __init__(
        self,
        target: DebugTarget,
        *,
        peek_word: WordReader | None = None,
        history_limit: int = 256,
        track_accesses: bool = False,
    ) -> None:
        if not isinstance(target, DebugTarget):
            raise TypeError("target must provide step() and capture_state()")
        if peek_word is not None and not callable(peek_word):
            raise TypeError("peek_word must be callable or None")
        if type(history_limit) is not int or history_limit < 0:
            raise ValueError("history_limit must be a non-negative integer")
        self.target = target
        #: The processor: the target itself, or the ``cpu`` a board target carries.
        self.cpu = getattr(target, "cpu", target)
        self.peek_word = peek_word
        self.history_limit = history_limit
        self.breakpoints: set[int] = set()
        self.watchpoints: dict[int, str] = {}  # address -> "r", "w" or "rw"
        self.total_steps = 0
        self.total_instructions = 0
        self.total_cycles = 0
        self._history: deque[StepRecord] = deque(maxlen=history_limit or 1)
        self._accesses: list[Access] | None = None
        self._originals: tuple[Callable, ...] | None = None
        if track_accesses:
            self._wrap_bus()

    # -- access tracking ---------------------------------------------------

    @property
    def tracking(self) -> bool:
        return self._originals is not None

    def _wrap_bus(self) -> None:
        cpu = self.cpu
        read_byte, read_word = cpu.read_byte, cpu.read_word
        write_byte, write_word = cpu.write_byte, cpu.write_word
        self._originals = (read_byte, read_word, write_byte, write_word)
        self._accesses = []
        log = self._accesses

        def tracked_read_byte(address: int, **kw) -> int:
            value = read_byte(address, **kw)
            log.append(("r", address, value, 1))
            return value

        def tracked_read_word(address: int, **kw) -> int:
            value = read_word(address, **kw)
            log.append(("r", address, value, 2))
            return value

        def tracked_write_byte(address: int, value: int, **kw) -> None:
            log.append(("w", address, value, 1))
            write_byte(address, value, **kw)

        def tracked_write_word(address: int, value: int, **kw) -> None:
            log.append(("w", address, value, 2))
            write_word(address, value, **kw)

        cpu.attach_bus(tracked_read_byte, tracked_read_word, tracked_write_byte, tracked_write_word)

    def close(self) -> None:
        """Stop tracking accesses and give the CPU its own bus callables back."""
        if self._originals is not None:
            self.cpu.attach_bus(*self._originals)
            self._originals = None
            self._accesses = None

    # -- breakpoints and watchpoints ---------------------------------------

    def add_breakpoint(self, address: int) -> None:
        """Stop before executing the instruction at ``address``."""
        self.breakpoints.add(_address(address))

    def remove_breakpoint(self, address: int) -> None:
        self.breakpoints.discard(_address(address))

    def add_watchpoint(self, address: int, kind: str = "rw") -> None:
        """Stop after any step that reads (``"r"``), writes (``"w"``) or either (``"rw"``).

        A word access watches both of its bytes.
        """
        if not self.tracking:
            raise ValueError("watchpoints need a session created with track_accesses=True")
        if kind not in ("r", "w", "rw"):
            raise ValueError('kind must be "r", "w" or "rw"')
        self.watchpoints[_address(address)] = kind

    def remove_watchpoint(self, address: int) -> None:
        self.watchpoints.pop(_address(address), None)

    # -- history -----------------------------------------------------------

    @property
    def history(self) -> tuple[StepRecord, ...]:
        """Bounded immutable view of the retained records, oldest first."""
        return tuple(self._history)

    def iter_history(self, *, newest_first: bool = False) -> Iterator[StepRecord]:
        return reversed(self._history) if newest_first else iter(self._history)

    def clear_history(self) -> None:
        self._history.clear()

    # -- execution ---------------------------------------------------------

    def step(self) -> StepRecord:
        """Advance exactly one boundary, ignoring breakpoints."""
        before = self.target.capture_state()
        kind = next_boundary(before)
        instruction = None
        if kind is BoundaryKind.INSTRUCTION and self.peek_word is not None:
            instruction = disassemble(self.peek_word, before.pc)
        if self._accesses is not None:
            self._accesses.clear()
        cycles = self.target.step()
        if type(cycles) is not int or cycles <= 0:
            raise ValueError("target step() must return a positive cycle count")
        record = StepRecord(
            sequence=self.total_steps,
            kind=kind,
            before=before,
            after=self.target.capture_state(),
            cycles=cycles,
            instruction=instruction,
            accesses=None if self._accesses is None else tuple(self._accesses),
        )
        self.total_steps += 1
        self.total_cycles += cycles
        if kind is BoundaryKind.INSTRUCTION:
            self.total_instructions += 1
        if self.history_limit:
            self._history.append(record)
        return record

    def run(
        self,
        *,
        max_steps: int,
        max_cycles: int | None = None,
        stop_on_stop: bool = True,
        stop_on_halt: bool = True,
    ) -> RunResult:
        """Run until a stop condition or the mandatory step budget.

        Breakpoints stop *before* the instruction; watchpoints stop *after*
        the step that touched the address.  A cycle limit is checked after each
        atomic step and may be exceeded by that step's cost.
        """
        if type(max_steps) is not int or max_steps <= 0:
            raise ValueError("max_steps must be a positive integer")
        if max_cycles is not None and (type(max_cycles) is not int or max_cycles <= 0):
            raise ValueError("max_cycles must be a positive integer or None")
        steps = instructions = cycles = 0
        last = None

        def result(reason: StopReason, state: CPUState, **extra) -> RunResult:
            return RunResult(reason, steps, instructions, cycles, state, last, **extra)

        while steps < max_steps:
            state = self.target.capture_state()
            kind = next_boundary(state)
            if (
                kind is BoundaryKind.INSTRUCTION
                and state.pc & 0xFFFFFF in self.breakpoints
                and steps
            ):
                return result(StopReason.BREAKPOINT, state)
            if stop_on_stop and kind is BoundaryKind.STOPPED_IDLE:
                return result(StopReason.STOPPED, state)
            if stop_on_halt and kind is BoundaryKind.HALTED_IDLE:
                return result(StopReason.HALTED, state)
            last = self.step()
            steps += 1
            cycles += last.cycles
            if last.kind is BoundaryKind.INSTRUCTION:
                instructions += 1
            hits = self._watch_hits(last)
            if hits:
                return result(StopReason.WATCHPOINT, last.after, hits=hits)
            if max_cycles is not None and cycles >= max_cycles:
                return result(StopReason.CYCLE_LIMIT, last.after)
        return result(StopReason.STEP_LIMIT, last.after if last else self.target.capture_state())

    def _watch_hits(self, record: StepRecord) -> tuple[Access, ...]:
        if not self.watchpoints or not record.accesses:
            return ()
        watched = self.watchpoints
        return tuple(
            access
            for access in record.accesses
            if any(
                (access[1] + offset) in watched and access[0] in watched[access[1] + offset]
                for offset in range(access[3])
            )
        )


def _address(address: int) -> int:
    if type(address) is not int or not 0 <= address <= 0xFFFFFF:
        raise ValueError("address must be an integer in range 0x000000..0xFFFFFF")
    return address


__all__ = [
    "Access",
    "BoundaryKind",
    "DebugSession",
    "DebugTarget",
    "RunResult",
    "StepRecord",
    "StopReason",
    "next_boundary",
]
