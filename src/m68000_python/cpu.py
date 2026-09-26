"""The public MC68000 CPU class.

The host owns memory and every device.  It passes four callables in --
``read_byte(address)``, ``read_word(address)``, ``write_byte(address, value)``
and ``write_word(address, value)`` over a 24-bit address space -- calls
:meth:`M68000CPU.step`, and adds the returned clock count to its own clock.
Interrupts are a level the host sets with :meth:`M68000CPU.set_ipl`; the
optional ``acknowledge(level)`` callable answers the interrupt-acknowledge
cycle with a vector number, :data:`AUTOVECTOR` or :data:`SPURIOUS`.  See
README.md, "The embedding contract".
"""

from collections.abc import Callable

from m68000_python._alu import ALUMixin
from m68000_python._bcd import BCDMixin
from m68000_python._bits import BitsMixin
from m68000_python._control import ControlMixin
from m68000_python._core import (
    AUTOVECTOR,
    IPL_MASK,
    MASK24,
    SPURIOUS,
    VECTOR_AUTOVECTOR_BASE,
    VECTOR_SPURIOUS,
    VECTOR_TRACE,
    VECTOR_UNINITIALIZED,
    Acknowledge,
    CoreMixin,
    GroupZero,
    ReadFunction,
    S,
    T,
    WriteFunction,
)
from m68000_python._dispatch import Handler, build_table
from m68000_python._ea import EAMixin
from m68000_python._flags import FlagsMixin
from m68000_python._loads import LoadsMixin
from m68000_python._shifts import ShiftsMixin
from m68000_python._system import SystemMixin
from m68000_python.state import CPUState


class M68000CPU(
    ALUMixin,
    BCDMixin,
    BitsMixin,
    ControlMixin,
    LoadsMixin,
    ShiftsMixin,
    SystemMixin,
    EAMixin,
    FlagsMixin,
    CoreMixin,
):
    """A Motorola MC68000 instruction core (also the MC68HC000 and MC68EC000).

    Registers: ``R`` is a list of sixteen 32-bit values, D0-D7 then A0-A7,
    where A7 is the stack pointer of the current mode; ``usp`` and ``ssp``
    name the two stack pointers whatever the mode.  ``SR`` is the 16-bit
    status register.  ``PC`` is the address of the next instruction; the
    prefetch queue behind it is ``ir`` (that instruction's first word) and
    ``irc`` (the word after it), read from memory ahead of execution as the
    chip does (docs/start-here.md, "Prefetch").

    Keyword options, each costing nothing unless used:

    * ``acknowledge(level)``: the interrupt-acknowledge cycle.  Return a
      vector number (0-255), :data:`AUTOVECTOR`, or :data:`SPURIOUS`.  Left
      out, every interrupt is autovectored, as on most arcade boards.
    * ``function_codes=True``: every bus call gets ``fc=`` (UM Table 3-2):
      1/2 user data/program, 5/6 supervisor data/program, 7 CPU space.
    * ``tas_write(address, value)``: the write half of TAS's read-modify-write
      cycle, for a bus that treats it differently (the Genesis drops it;
      docs/undocumented-behavior.md).  Defaults to ``write_byte``.
    * ``address_error(address, write, fc)``: told about the access an address
      error aborted, which never reaches the bus (UM 6.3.10).
    * ``reset_devices()``: called when the RESET instruction pulses the RESET
      line (PRM 6-83); the processor itself is not reset.

    A host raises :class:`BusError` from any bus callable to assert BERR.
    """

    _table: list[Handler]

    def __init__(
        self,
        read_byte: ReadFunction,
        read_word: ReadFunction,
        write_byte: WriteFunction,
        write_word: WriteFunction,
        *,
        acknowledge: Acknowledge | None = None,
        function_codes: bool = False,
        tas_write: WriteFunction | None = None,
        address_error: Callable[[int, bool, int], None] | None = None,
        reset_devices: Callable[[], None] | None = None,
    ) -> None:
        for name, value in (("acknowledge", acknowledge), ("tas_write", tas_write),
                            ("address_error", address_error),
                            ("reset_devices", reset_devices)):  # fmt: skip
            if value is not None and not callable(value):
                raise TypeError(f"{name} must be callable or None")
        if type(function_codes) is not bool:
            raise TypeError("function_codes must be a bool")
        self._init_core(
            read_byte,
            read_word,
            write_byte,
            write_word,
            acknowledge,
            function_codes,
            tas_write,
            address_error,
            reset_devices,
        )
        cls = type(self)
        if "_table" not in cls.__dict__:
            cls._table = build_table(cls)

    # -- state capture and restore (docs/cpu-state.md) --------------------------

    def capture_state(self) -> CPUState:
        """Return an immutable snapshot of all CPU-owned state; no host reads."""
        R = self.R
        return CPUState(
            d=tuple(R[0:8]),
            a=tuple(R[8:15]),
            usp=self.usp,
            ssp=self.ssp,
            sr=self.SR,
            pc=(self._pc - 4) & 0xFFFFFFFF,
            ir=self.ir,
            irc=self.irc,
            ipl=self.ipl,
            nmi_edge=self._nmi_edge,
            trace_pending=self._trace_pending,
            stopped=self.stopped,
            halted=self.halted,
            clock=self.clock,
        )

    def restore_state(self, state: CPUState) -> None:
        """Restore a captured state without touching the host's memory or devices."""
        if type(state) is not CPUState:
            raise TypeError("state must be a CPUState")
        R = self.R
        R[0:8] = state.d
        R[8:15] = state.a
        self.SR = state.sr
        if state.sr & S:
            R[15], self._other_sp = state.ssp, state.usp
        else:
            R[15], self._other_sp = state.usp, state.ssp
        self._pc = (state.pc + 4) & 0xFFFFFFFF
        self.ir = state.ir
        self.irc = state.irc
        self.ipl = state.ipl
        self._nmi_edge = state.nmi_edge
        self._trace_pending = state.trace_pending
        self.stopped = state.stopped
        self.halted = state.halted
        self.clock = state.clock

    # -- the program counter as a programmer sees it --------------------------

    @property
    def PC(self) -> int:
        """The address of the next instruction (the queue reads 4 bytes ahead)."""
        return (self._pc - 4) & 0xFFFFFFFF

    def set_pc(self, address: int) -> None:
        """Start executing at ``address``: refill the prefetch queue from it.

        Two program reads, as a jump does; no clocks are counted.  The host
        uses this instead of a reset when it loads a program itself.  An odd
        address is refused: instructions live at even addresses (UM 6.3.10),
        and a jump to an odd one is an address error, not a start.
        """
        if address & 1:
            raise ValueError("an instruction address must be even")
        address &= 0xFFFFFFFF
        self.ir = self._read_program(address & MASK24)
        self.irc = self._read_program((address + 2) & MASK24)
        self._pc = (address + 4) & 0xFFFFFFFF
        self.stopped = False

    # -- external signals -----------------------------------------------------

    def set_sr(self, value: int) -> None:
        """Write SR as an instruction would: A7 follows S to the other stack pointer.

        Assigning ``SR`` directly changes the bits and nothing else, which is
        what a state restore wants and a host usually does not.
        """
        self._set_sr(value)

    def _next_pc(self) -> int:
        """The address execution resumes at: what an interrupt or trace stacks.

        At a boundary the queue has read 4 bytes ahead.  STOP leaves the queue
        as it was (its immediate still in IRC, corpus T3), so a stopped CPU
        resumes at the prefetch address itself: the instruction after STOP.
        """
        return self._pc if self.stopped else (self._pc - 4) & 0xFFFFFFFF

    def set_ipl(self, level: int) -> None:
        """Set the interrupt level on IPL2-IPL0 (0 = none, 7 = non-maskable).

        Level 7 is edge-triggered: a change to 7 from below is taken once
        even with the mask at 7 (UM 6.3.2).
        """
        if not 0 <= level <= 7:
            raise ValueError("IPL level must be 0-7")
        if level == 7 and self.ipl != 7:
            self._nmi_edge = True
        self.ipl = level

    def reset(self) -> int:
        """The reset exception (UM 6.3.1): S set, T clear, mask 7, SSP and PC from 0 and 4.

        Nothing is pushed.  A fault while fetching the vectors or the first
        instruction (an odd initial PC) halts the processor as a double bus
        fault (UM 5.4.4).  Returns the clocks spent, 42: 16 internal, the
        four vector reads, and the two-read refill of the queue with its 2
        idle clocks, as every other exception entry refills it.  UM Table
        8-14 prints 40(6/0) for reset; no corpus has a reset-pin case and
        the referees are not run on one, so the 2-clock difference is open
        (docs/claims.md, "Undecidable here").
        """
        self._cycles = 0
        self.halted = False
        self.stopped = False
        self._trace_pending = False
        self._nmi_edge = False
        self._set_sr((self.SR | S | IPL_MASK) & ~T)
        self._cycles += 16
        try:
            self.R[15] = (self._read_program_word(0) << 16) | self._read_program_word(2)
            pc = (self._read_program_word(4) << 16) | self._read_program_word(6)
            self._fault_pc = pc
            self._jump_idle(pc)
        except GroupZero:
            # An address or bus error during the reset sequence (an odd initial
            # PC, BERR on a vector) is a double bus fault: halt (UM 5.4.4).
            self.halted = True
        self.clock += self._cycles
        return self._cycles

    # -- execution ------------------------------------------------------------

    @property
    def step_clocks(self) -> int:
        """Clocks the step in progress has spent so far (read-only).

        Read from inside a bus callback, it counts the access being made as
        complete: that access occupies clocks ``step_clocks - 4`` to
        ``step_clocks`` of the step, so ``clock + step_clocks - 4`` is when it
        began on the host's running count.  A host that stalls the CPU (a
        wait state, a device holding the bus) uses it to place the stall at
        the right clock; the core itself does not model wait states, so the
        host adds its own stall clocks to the ``step()`` total.  Inside an
        ``acknowledge`` callback the acknowledge cycle's own four clocks are
        not yet counted.  Between steps it is the last ``step()``'s (or
        ``reset()``'s) total.
        """
        return self._cycles

    def step(self) -> int:
        """Run one instruction or one exception entry; return its clock count.

        At an instruction boundary, in this order: a halted CPU idles; a
        trace exception left by the previous instruction is taken (UM 6.3.8:
        trace outranks interrupts); an interrupt above the mask, or a level
        7 edge, is taken (UM 6.3.2); a stopped CPU idles; otherwise the
        instruction in IR runs.
        """
        if self.halted:
            self._cycles = 4
            self.clock += 4
            return 4
        self._cycles = 0
        try:
            level = self.ipl
            if self._trace_pending:
                self._trace_pending = False
                self._opcode = self.ir
                self._exception(VECTOR_TRACE, self._next_pc())
                self.stopped = False
            elif level and (level > (self.SR >> 8) & 7 or (level == 7 and self._nmi_edge)):
                self._interrupt(level)
            elif self.stopped:
                self._cycles = 4
            else:
                opcode = self._opcode = self.ir
                self._fault_pc = self._pc - 2
                traced = self.SR & T
                if traced:
                    self._untraced = False
                self._table[opcode](self, opcode)
                if traced and not self._untraced:
                    # Trace follows an instruction that completed, as its own
                    # boundary: the next step takes it (UM 6.3.8).  An illegal
                    # or privileged instruction was never executed and is not
                    # traced (_system._not_executed).  The corpus's final
                    # states are captured before the trace (its issue #2).
                    self._trace_pending = True
        except GroupZero as fault:
            self._group_zero(fault)
        self.clock += self._cycles
        return self._cycles

    def _interrupt(self, level: int) -> None:
        """Interrupt entry (UM 6.3.2-6.3.4): acknowledge, stack, vector.

        The mask rises to the accepted level; the acknowledge cycle names the
        vector, or asks for the autovector (24 + level), or reports spurious
        (vector 24).  A vector number outside 0-255 is an uninitialized
        vector (15).
        """
        if level == 7:
            self._nmi_edge = False
        self._opcode = self.ir
        pc = self._next_pc()  # the instruction the interrupt came before
        self.stopped = False
        # Three internal steps: SR copied, S set and T cleared, the mask
        # raised to the level being taken (UM 6.3.2; MAME 0.285's order).
        self._cycles += 6
        saved = self.SR
        self._set_sr(((saved | S) & ~T & ~IPL_MASK) | (level << 8))
        self._processing_exception = True
        sp = self.R[15]
        self._write_word(sp - 2, pc)
        # The acknowledge cycle comes between the first push and the rest.
        answer = AUTOVECTOR if self._acknowledge is None else self._acknowledge(level)
        self._cycles += 4
        if answer == AUTOVECTOR:
            vector = VECTOR_AUTOVECTOR_BASE + level
            # VPA: the cycle waits for the E clock (CLK/10) as the manual
            # describes (UM 5.1.4, 6.3.2); the phase is the host's running
            # clock count, ``clock``, as MAME 0.285's vpa_sync takes it.
            self._cycles += self._e_clock_wait()
        elif answer == SPURIOUS:
            vector = VECTOR_SPURIOUS
        elif 0 <= answer <= 255:
            vector = answer
        else:
            vector = VECTOR_UNINITIALIZED
        self._cycles += 4
        sp = (sp - 6) & 0xFFFFFFFF
        self.R[15] = sp
        self._write_word(sp, saved)
        self._write_word(sp + 2, pc >> 16)
        target = self._read_vector(vector)
        self._jump_idle(target)
        self._processing_exception = False

    def _e_clock_wait(self) -> int:
        """Clocks an autovectored acknowledge waits for the E clock.

        MAME 0.285 (m68000.cpp, ``vpa_sync`` and ``vpa_after``): with t the
        clock count at the start of the cycle, the transfer is aligned to the
        next E-clock period boundary, one period later when fewer than 3
        clocks remain, and one clock is added after it.  The MAME lockstep
        on System 16B agrees at every phase (docs/validation.md, rung 6).
        """
        now = self.clock + self._cycles - 4
        phase = now % 10
        self.last_acknowledge_phase = phase
        return ((10 - phase) if phase < 7 else (20 - phase)) + 1


__all__ = ["AUTOVECTOR", "M68000CPU", "SPURIOUS"]
