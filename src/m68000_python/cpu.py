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
from m68000_python._loads import LoadsMixin, MultipleMixin
from m68000_python._shifts import ShiftsMixin
from m68000_python._system import SystemMixin


class M68000CPU(
    ALUMixin,
    BCDMixin,
    BitsMixin,
    ControlMixin,
    LoadsMixin,
    MultipleMixin,
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
    ) -> None:
        self._init_core(
            read_byte,
            read_word,
            write_byte,
            write_word,
            acknowledge,
            function_codes,
            tas_write,
            address_error,
        )
        cls = type(self)
        if "_table" not in cls.__dict__:
            cls._table = build_table(cls)

    # -- the program counter as a programmer sees it --------------------------

    @property
    def PC(self) -> int:
        """The address of the next instruction (the queue reads 4 bytes ahead)."""
        return (self._pc - 4) & 0xFFFFFFFF

    def set_pc(self, address: int) -> None:
        """Start executing at ``address``: refill the prefetch queue from it.

        Two program reads, as a jump does; no clocks are counted.  The host
        uses this instead of a reset when it loads a program itself.
        """
        address &= 0xFFFFFFFF
        self.ir = self._read_program(address & MASK24)
        self.irc = self._read_program((address + 2) & MASK24)
        self._pc = (address + 4) & 0xFFFFFFFF
        self.stopped = False

    # -- external signals -----------------------------------------------------

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

        Nothing is pushed.  Returns the clocks spent: 40 on the chip,
        counted from RESET negated to the first instruction (UM Table 8-14).
        """
        self._cycles = 0
        self.halted = False
        self.stopped = False
        self._trace_pending = False
        self._nmi_edge = False
        self._set_sr((self.SR | S | IPL_MASK) & ~T)
        self._cycles += 16
        self.R[15] = (self._read_program_word(0) << 16) | self._read_program_word(2)
        pc = (self._read_program_word(4) << 16) | self._read_program_word(6)
        self._fault_pc = pc
        self._jump_idle(pc)
        return self._cycles

    # -- execution ------------------------------------------------------------

    def step(self) -> int:
        """Run one instruction or one exception entry; return its clock count.

        At an instruction boundary, in this order: a halted CPU idles; a
        trace exception left by the previous instruction is taken (UM 6.3.8:
        trace outranks interrupts); an interrupt above the mask, or a level
        7 edge, is taken (UM 6.3.2); a stopped CPU idles; otherwise the
        instruction in IR runs.
        """
        if self.halted:
            return 4
        self._cycles = 0
        try:
            if self._trace_pending:
                self._trace_pending = False
                self._opcode = self.ir
                self._exception(VECTOR_TRACE, self._pc - 4)
                return self._cycles
            level = self.ipl
            if level and (level > (self.SR >> 8) & 7 or (level == 7 and self._nmi_edge)):
                self._interrupt(level)
                return self._cycles
            if self.stopped:
                return 4
            opcode = self._opcode = self.ir
            self._fault_pc = self._pc - 2
            traced = self.SR & T
            self._table[opcode](self, opcode)
            if traced:
                # Trace follows an instruction that completed, as its own
                # boundary: the next step takes it (UM 6.3.8).  The corpus's
                # final states are captured before it (its issue #2).
                self._trace_pending = True
        except GroupZero as fault:
            self._group_zero(fault)
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
        self.stopped = False
        answer = AUTOVECTOR if self._acknowledge is None else self._acknowledge(level)
        if answer == AUTOVECTOR:
            vector = VECTOR_AUTOVECTOR_BASE + level
        elif answer == SPURIOUS:
            vector = VECTOR_SPURIOUS
        elif 0 <= answer <= 255:
            vector = answer
        else:
            vector = VECTOR_UNINITIALIZED
        self._opcode = self.ir
        saved = self.SR
        self._cycles += 6  # acknowledge cycle and internal steps: settled by rung 6
        self._set_sr((saved & ~IPL_MASK) | (level << 8))
        self._exception(vector, self._pc - 4, saved=saved)


__all__ = ["AUTOVECTOR", "M68000CPU", "SPURIOUS"]
