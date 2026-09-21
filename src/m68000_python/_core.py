"""Processor state, the bus, the prefetch queue, and exception entry.

Everything a handler touches goes through the helpers here: sized register
access, the host bus with its odd-address check, the two-word prefetch queue,
and the group 0/1/2 exception sequences.  Sources are cited as in
docs/start-here.md: PRM is the M68000 Family Programmer's Reference Manual,
UM the M68000 User's Manual.  Where the manuals are silent, the order of bus
accesses, the internal ("idle") clocks, and the value an address error
stacks as PC follow the pinned SingleStepTests/m68000 corpus, which records
them as MAME 0.285's microcode-transcribed core produces them (tier T3; see
docs/undocumented-behavior.md).

Time is counted in clocks as the core goes: every bus access adds 4 and every
internal step adds the clocks the microcode spends there, so an instruction
that faults halfway has spent exactly the clocks up to the fault.
"""

from collections.abc import Callable

# -- status register (PRM 1.3.1) ----------------------------------------------
T = 0x8000  # trace
S = 0x2000  # supervisor
IPL_MASK = 0x0700  # interrupt priority mask, I2-I0
X = 0x10  # extend
N = 0x08  # negative
Z = 0x04  # zero
V = 0x02  # overflow
C = 0x01  # carry
CCR_BITS = 0x1F
#: Bits 14, 12, 11, 7, 6 and 5 read as zero on the 68000 (PRM 1.3.1).
SR_BITS = 0xA71F

MASK24 = 0xFFFFFF  # the 68000 drives A23-A1 (UM 3.1)

# Function codes FC2-FC0 (UM Table 3-2).
FC_USER_DATA = 1
FC_USER_PROGRAM = 2
FC_SUPERVISOR_DATA = 5
FC_SUPERVISOR_PROGRAM = 6
FC_CPU_SPACE = 7

# Exception vectors (UM Table 6-2).
VECTOR_BUS_ERROR = 2
VECTOR_ADDRESS_ERROR = 3
VECTOR_ILLEGAL = 4
VECTOR_ZERO_DIVIDE = 5
VECTOR_CHK = 6
VECTOR_TRAPV = 7
VECTOR_PRIVILEGE = 8
VECTOR_TRACE = 9
VECTOR_LINE_A = 10
VECTOR_LINE_F = 11
VECTOR_UNINITIALIZED = 15
VECTOR_SPURIOUS = 24
VECTOR_AUTOVECTOR_BASE = 24  # level n autovectors through vector 24 + n
VECTOR_TRAP_BASE = 32

#: ``acknowledge(level)`` answers: a vector number 0-255, or one of these.
AUTOVECTOR = -1
SPURIOUS = -2

#: Operand sizes in bytes, and their masks and sign bits.
BYTE, WORD, LONG = 1, 2, 4
MASK = {1: 0xFF, 2: 0xFFFF, 4: 0xFFFFFFFF}
MSB = {1: 0x80, 2: 0x8000, 4: 0x80000000}

ReadFunction = Callable[..., int]
WriteFunction = Callable[..., None]
Acknowledge = Callable[[int], int]


class BusError(Exception):
    """Raise from a host read or write callable to assert BERR on that access.

    The core catches it at the access, aborts the instruction, and takes the
    bus-error exception (vector 2) with the seven-word group 0 frame
    (UM 6.3.9.1).  Most hosts never raise it.
    """


class GroupZero(Exception):
    """Internal: an address or bus error aborting the current instruction."""

    def __init__(self, vector: int, address: int, write: bool, program: bool) -> None:
        super().__init__(vector, address, write, program)
        self.vector = vector
        self.address = address  # the full 32-bit value the microcode computed
        self.write = write
        self.program = program


class CoreMixin:
    """Private implementation of the state and helpers every handler uses."""

    # -- construction -------------------------------------------------------

    def _init_core(
        self,
        read_byte: ReadFunction,
        read_word: ReadFunction,
        write_byte: WriteFunction,
        write_word: WriteFunction,
        acknowledge: Acknowledge | None,
        function_codes: bool,
        tas_write: WriteFunction | None,
        address_error: Callable[[int, bool, int], None] | None,
    ) -> None:
        # R[0..7] are D0-D7, R[8..15] are A0-A7; A7 is the active stack
        # pointer and the inactive one waits in _other_sp (PRM 1.3).
        self.R = [0] * 16
        self._other_sp = 0
        # Undefined at reset on silicon apart from S, T and the mask (UM 6.3.1).
        self.SR = S | IPL_MASK
        # The prefetch queue (UM "Prefetch", docs/start-here.md): ir is the
        # opcode word of the next instruction, irc the word after it, and
        # _pc the address the next queue refill reads, which is the
        # instruction's address + 4 at a boundary (the corpus's ``pc``).
        self.ir = 0
        self.irc = 0
        self._pc = 0
        # The microcode's PC register: an address error stacks it.  It trails
        # _pc and is brought up to it only at the steps where the microcode
        # copies the address unit into PC (see _commit_pc).
        self._fault_pc = 0
        self._opcode = 0  # the instruction being executed (IRD)
        self._cycles = 0  # clocks of the step in progress
        #: Clocks run since construction: the sum of every step() and reset().
        #: The host may set it; only the E-clock phase of an autovectored
        #: interrupt acknowledge depends on it.
        self.clock = 0
        # Interrupts, trace and the stopped/halted states (UM 6.3).
        self.ipl = 0  # the level on IPL2-IPL0 as the host last set it
        self._nmi_edge = False  # a 0-to-7 transition not yet taken
        self._trace_pending = False
        # Set by an instruction that is never executed (illegal, line A/F,
        # privilege violation): no trace follows it (UM 6.3.8).
        self._untraced = False
        self._processing_exception = False
        self.stopped = False
        self.halted = False
        #: E-clock phase (clock mod 10) at the last autovectored acknowledge.
        self.last_acknowledge_phase = 0

        self._acknowledge = acknowledge
        self._address_error_hook = address_error
        self.function_codes = function_codes
        self.tas_write = tas_write
        self.attach_bus(read_byte, read_word, write_byte, write_word)

    def attach_bus(
        self,
        read_byte: ReadFunction,
        read_word: ReadFunction,
        write_byte: WriteFunction,
        write_word: WriteFunction,
    ) -> None:
        """Give the core its four bus callables (the constructor's; a debugger's wrappers).

        The originals stay readable as ``read_byte``, ``read_word``,
        ``write_byte`` and ``write_word``.
        """
        self.read_byte, self.read_word = read_byte, read_word
        self.write_byte, self.write_word = write_byte, write_word
        tas_write = self.tas_write
        if self.function_codes:
            # Only a host that asks pays for function codes (docs/handoff-brief.md).
            self._read_program = lambda address: read_word(address, fc=self._fc(True))
            self._read_data_word = lambda address: read_word(address, fc=self._fc(False))
            self._read_data_byte = lambda address: read_byte(address, fc=self._fc(False))
            self._read_program_byte_host = lambda address: read_byte(address, fc=self._fc(True))
            self._write_data_word = lambda address, value: write_word(
                address, value, fc=self._fc(False)
            )
            self._write_data_byte = lambda address, value: write_byte(
                address, value, fc=self._fc(False)
            )
        else:
            self._read_program = read_word
            self._read_data_word = read_word
            self._read_data_byte = read_byte
            self._read_program_byte_host = read_byte
            self._write_data_word = write_word
            self._write_data_byte = write_byte
        if tas_write is None:
            self._tas_write = self._write_data_byte
        elif self.function_codes:
            self._tas_write = lambda address, value: tas_write(address, value, fc=self._fc(False))
        else:
            self._tas_write = tas_write

    # -- the stack pointers and the status register --------------------------

    def _fc(self, program: bool) -> int:
        if self.SR & S:
            return FC_SUPERVISOR_PROGRAM if program else FC_SUPERVISOR_DATA
        return FC_USER_PROGRAM if program else FC_USER_DATA

    def _set_sr(self, value: int) -> None:
        """Write the whole SR, swapping A7 with the other stack pointer if S changes."""
        value &= SR_BITS
        if (value ^ self.SR) & S:
            self.R[15], self._other_sp = self._other_sp, self.R[15]
        self.SR = value

    def _set_ccr(self, value: int) -> None:
        self.SR = (self.SR & 0xFF00) | (value & CCR_BITS)

    @property
    def usp(self) -> int:
        """The user stack pointer, whichever mode the CPU is in."""
        return self._other_sp if self.SR & S else self.R[15]

    @usp.setter
    def usp(self, value: int) -> None:
        if self.SR & S:
            self._other_sp = value & 0xFFFFFFFF
        else:
            self.R[15] = value & 0xFFFFFFFF

    @property
    def ssp(self) -> int:
        """The supervisor stack pointer, whichever mode the CPU is in."""
        return self.R[15] if self.SR & S else self._other_sp

    @ssp.setter
    def ssp(self, value: int) -> None:
        if self.SR & S:
            self.R[15] = value & 0xFFFFFFFF
        else:
            self._other_sp = value & 0xFFFFFFFF

    # -- the bus ------------------------------------------------------------
    # Every access checks alignment first: a word or long at an odd address
    # is an address error, and the aborted cycle never reaches the host
    # (UM 6.3.10; the corpus marks it "re"/"we", AS not asserted).

    def _fault(self, vector: int, address: int, write: bool, program: bool) -> GroupZero:
        return GroupZero(vector, address & 0xFFFFFFFF, write, program)

    def _read_word(self, address: int) -> int:
        if address & 1:
            raise self._fault(VECTOR_ADDRESS_ERROR, address, False, False)
        self._cycles += 4
        try:
            return self._read_data_word(address & MASK24)
        except BusError:
            raise self._fault(VECTOR_BUS_ERROR, address, False, False) from None

    def _read_byte(self, address: int) -> int:
        self._cycles += 4
        try:
            return self._read_data_byte(address & MASK24)
        except BusError:
            raise self._fault(VECTOR_BUS_ERROR, address, False, False) from None

    def _read_long(self, address: int) -> int:
        """Two word reads, high word first (UM 2.4)."""
        high = self._read_word(address)
        return (high << 16) | self._read_word(address + 2)

    def _write_word(self, address: int, value: int) -> None:
        if address & 1:
            raise self._fault(VECTOR_ADDRESS_ERROR, address, True, False)
        self._cycles += 4
        try:
            self._write_data_word(address & MASK24, value & 0xFFFF)
        except BusError:
            raise self._fault(VECTOR_BUS_ERROR, address, True, False) from None

    def _write_byte(self, address: int, value: int) -> None:
        self._cycles += 4
        try:
            self._write_data_byte(address & MASK24, value & 0xFF)
        except BusError:
            raise self._fault(VECTOR_BUS_ERROR, address, True, False) from None

    def _write_long(self, address: int, value: int) -> None:
        """Two word writes, high word first."""
        if address & 1:
            raise self._fault(VECTOR_ADDRESS_ERROR, address, True, False)
        self._write_word(address, value >> 16)
        self._write_word(address + 2, value)

    def _write_long_low_first(self, address: int, value: int) -> None:
        """Two word writes, low word (at address + 2) first.

        The order of -(An) destinations and of read-modify-write results:
        the microcode works toward the high word (corpus, T3).  An odd
        address faults on the first write, at ``address + 2``.
        """
        self._write_word(address + 2, value)
        self._write_word(address, value >> 16)

    def _read(self, size: int, address: int) -> int:
        if size == 2:
            return self._read_word(address)
        if size == 1:
            return self._read_byte(address)
        return self._read_long(address)

    def _write(self, size: int, address: int, value: int) -> None:
        """A byte or word write; every long write orders its halves at its caller."""
        if size == 2:
            self._write_word(address, value)
        else:
            self._write_byte(address, value)

    def _read_program_word(self, address: int) -> int:
        if address & 1:
            raise self._fault(VECTOR_ADDRESS_ERROR, address, False, True)
        self._cycles += 4
        try:
            return self._read_program(address & MASK24)
        except BusError:
            raise self._fault(VECTOR_BUS_ERROR, address, False, True) from None

    def _read_program_operand(self, size: int, address: int) -> int:
        """A PC-relative operand: read in program space (UM Table 3-2, FC 2/6)."""
        if size == 1:
            self._cycles += 4
            try:
                return self._read_program_byte_host(address & MASK24)
            except BusError:
                raise self._fault(VECTOR_BUS_ERROR, address, False, True) from None
        high = self._read_program_word(address)
        if size == 2:
            return high
        return (high << 16) | self._read_program_word(address + 2)

    # -- the prefetch queue ---------------------------------------------------

    def _commit_pc(self) -> None:
        """Copy the fetch address into the microcode's PC register.

        Only an address error can see the difference: it stacks this value
        (UM 6.2.5 "unpredictable"; the steps that commit it are the
        corpus's, T3).
        """
        self._fault_pc = self._pc

    def _extension(self) -> int:
        """Take the extension word waiting in IRC and refill IRC from _pc."""
        value = self.irc
        self.irc = self._read_program_word(self._pc)
        self._pc = (self._pc + 2) & 0xFFFFFFFF
        return value

    def _extension_long(self) -> int:
        high = self._extension()
        return (high << 16) | self._extension()

    def _prefetch(self) -> None:
        """The last step of every instruction: IRC moves to IR, IRC refills.

        The opcode of the next instruction is then in IR and its first
        extension word in IRC (UM "Prefetch"; corpus ``prefetch`` pair).
        """
        self._fault_pc = self._pc
        # IR takes IRC, and the decoder (IRD) takes IR, before the read: an
        # address error on this read already stacks the next opcode (T3).
        self.ir = self._opcode = self.irc
        self.irc = self._read_program_word(self._pc)
        self._pc = (self._pc + 2) & 0xFFFFFFFF

    def _prefetch_before_write(self) -> None:
        """The closing prefetch of an instruction that still has a write to do.

        IR takes IRC and IRC refills, but the decoder keeps the current
        opcode until the handler hands it over with ``self._opcode =
        self.ir`` at the step the microcode does (T3): an address error on
        a write before that point stacks the old opcode.
        """
        self._fault_pc = self._pc
        self.ir = self.irc
        self.irc = self._read_program_word(self._pc)
        self._pc = (self._pc + 2) & 0xFFFFFFFF

    def _jump(self, target: int) -> None:
        """Refill the queue from ``target``: two program reads (UM Table 8-9).

        The first read lands in IRC; the closing prefetch moves it to IR and
        reads the word after it.
        """
        target &= 0xFFFFFFFF
        self.irc = self._read_program_word(target)
        self._pc = (target + 2) & 0xFFFFFFFF
        self._prefetch()

    def _jump_idle(self, target: int) -> None:
        """A jump whose refill has two internal clocks between its reads."""
        target &= 0xFFFFFFFF
        self.irc = self._read_program_word(target)
        self._pc = (target + 2) & 0xFFFFFFFF
        self._cycles += 2
        self._prefetch()

    # -- the stack -------------------------------------------------------------

    def _push_long(self, value: int) -> None:
        """Push a long, high word first (BSR, JSR, PEA; corpus, T3)."""
        sp = (self.R[15] - 4) & 0xFFFFFFFF
        self.R[15] = sp
        self._write_long(sp, value)

    def _pop_word(self) -> int:
        sp = self.R[15]
        value = self._read_word(sp)
        self.R[15] = (sp + 2) & 0xFFFFFFFF
        return value

    def _pop_long(self) -> int:
        sp = self.R[15]
        value = self._read_long(sp)
        self.R[15] = (sp + 4) & 0xFFFFFFFF
        return value

    # -- exceptions (UM 6.2, 6.3) ---------------------------------------------

    def _enter_supervisor(self) -> int:
        """Step 1 of exception processing: copy SR, set S, clear T (UM 6.2.5)."""
        saved = self.SR
        self._set_sr((saved | S) & ~T)
        return saved

    def _exception(self, vector: int, pc: int, *, idle: int = 4, saved: int | None = None) -> None:
        """Group 1 and 2 exception entry with the three-word frame (UM Figure 6-5).

        ``pc`` is the value to stack; ``idle`` the internal clocks before the
        first push.  The pushes, the vector fetch and the refill are in the
        order the corpus records: PC low, SR, PC high, vector high and low,
        then the handler's first two words with two idle clocks between.
        """
        entered = self._enter_supervisor()
        if saved is None:
            saved = entered
        self._trace_pending = False
        self._cycles += idle
        # An address or bus error from here on is one "not an instruction"
        # access: I/N is set in its information word (UM Figure 6-7).
        self._processing_exception = True
        sp = (self.R[15] - 6) & 0xFFFFFFFF
        self.R[15] = sp
        self._write_word(sp + 4, pc)
        self._write_word(sp, saved)
        self._write_word(sp + 2, pc >> 16)
        self._fault_pc = pc
        target = self._read_vector(vector)
        self._jump_idle(target)
        self._processing_exception = False

    def _read_vector(self, vector: int) -> int:
        address = vector << 2
        high = self._read_word(address)
        return (high << 16) | self._read_word(address + 2)

    def _group_zero(self, fault: GroupZero) -> None:
        """Address or bus error: abort, stack the seven-word frame (UM Figure 6-7).

        The aborted access costs its four clocks and four more; two internal
        steps of two clocks follow (corpus, T3).  The frame is written in
        the corpus's order: PC low, SR, PC high, IR, access address low,
        access information, access address high.  A second group 0 fault
        while doing this halts the processor (UM 5.4.4).
        """
        if fault.vector == VECTOR_ADDRESS_ERROR and self._address_error_hook is not None:
            self._address_error_hook(fault.address & MASK24, fault.write, self._fc(fault.program))
        self._cycles += 4 + 4 + 2 + 2
        # The access information word: bits 15-5 are the undefined part and
        # carry IR's (corpus, T3; UM Figure 6-7 marks them undefined), R/W is
        # bit 4, I/N bit 3 (set when the access was part of exception
        # processing rather than of an instruction), and the function code.
        information = (
            (self._opcode & 0xFFE0)
            | (0 if fault.write else 0x10)
            | (0x08 if self._processing_exception else 0)
            | self._fc(fault.program)
        )
        self._processing_exception = False
        saved = self._enter_supervisor()
        self._trace_pending = False
        pc = self._fault_pc
        sp = (self.R[15] - 14) & 0xFFFFFFFF
        self.R[15] = sp
        try:
            self._write_word(sp + 12, pc)
            self._write_word(sp + 8, saved)
            self._write_word(sp + 10, pc >> 16)
            self._write_word(sp + 6, self._opcode)
            self._write_word(sp + 4, fault.address)
            self._write_word(sp, information)
            self._write_word(sp + 2, fault.address >> 16)
            target = self._read_vector(fault.vector)
            self._jump_idle(target)
        except GroupZero:
            # A group 0 fault while processing a group 0 exception: the double
            # bus fault halts the processor until reset (UM 5.4.4, 6.3.9.1).
            # MAME 0.285 takes another address error instead; the corpus has
            # no such case, and the manual is followed (docs/worklog.md).
            self.halted = True
