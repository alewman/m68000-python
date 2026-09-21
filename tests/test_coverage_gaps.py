"""The gaps the coverage report found, where the manuals decide the answer.

docs/coverage.md is the map: which of the 45,815 defined opcode words the
SingleStepTests/m68000 gate executes (38,019), which behavioural paths it
reaches, and which source lines of the core no test runs.  This file closes
the gaps that are decidable **without an external oracle** -- encodings that
are the same handler with an unsampled field, and paths the Motorola manuals
state plainly.  Every assertion names the section it comes from:

* **PRM** -- M68000 Family Programmer's Reference Manual (M68000PRM/AD Rev 1),
  Section 4 by page for the instructions, Table 3-18 for the condition codes,
  Table 3-19 for the conditional tests.
* **UM** -- M68000 8-/16-/32-Bit Microprocessors User's Manual (M68000UM/AD
  Rev 1), Section 6 for exceptions and Section 8 for the clock tables.

The manual text is paraphrased, not quoted.  Nothing here asserts a value the
manuals call undefined or unpredictable, and no expected value is taken from
the core: flag rules are restated independently below from PRM Table 3-18's
boolean formulas.  Where a gap needs an oracle to settle -- undefined flags,
the clocks of an undocumented path, the PC an exception of an undecided kind
stacks -- it is left open in docs/coverage.md, "Open gaps", not turned into a
test of what this core happens to do.
"""

from __future__ import annotations

import pytest
from conftest import Bus, make

from m68000_python import M68000CPU
from m68000_python._core import BusError

NOP = 0x4E71
ILLEGAL = 0x4AFC
HANDLER = 0x2000
START = 0x1000
STACK = 0x8000

# -- helpers ------------------------------------------------------------------


def with_vectors(**handlers):
    """A CPU at $1000 with every exception vector pointing at its own handler.

    Vector n lands at ``$2000 + 16n`` unless ``vN=address`` names another, so a
    test can tell which exception was taken by where the PC ends up.
    """
    cpu, bus = make([NOP] * 16)
    for vector in range(256):
        bus.set_long(vector * 4, handlers.get(f"v{vector}", HANDLER + 16 * vector))
    bus.load(HANDLER, [NOP] * 0x800)
    return cpu, bus


def restart(cpu, bus, words, *, at=START, sr=0x2700, sp=STACK):
    """Reload a program and start again at ``at`` without a reset or a clock cost."""
    bus.load(at, words)
    cpu.SR = sr  # set directly: no stack-pointer swap, as a test fixture wants
    cpu.R[15] = sp
    cpu.set_pc(at)
    cpu.clock = 0
    bus.log.clear()


def frame(bus, cpu):
    """The three-word group 1/2 frame on the stack: (status, program counter)."""
    return bus.word(cpu.R[15]), bus.long(cpu.R[15] + 2)


def sign_extend_8(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def sign_extend_16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def condition_holds(condition: int, ccr: int) -> bool:
    """PRM Table 3-19, written out here independently of the core's table."""
    n, z, v, c = bool(ccr & 8), bool(ccr & 4), bool(ccr & 2), bool(ccr & 1)
    return {
        0x0: True,  # T
        0x1: False,  # F
        0x2: not c and not z,  # HI
        0x3: c or z,  # LS
        0x4: not c,  # CC (HS)
        0x5: c,  # CS (LO)
        0x6: not z,  # NE
        0x7: z,  # EQ
        0x8: not v,  # VC
        0x9: v,  # VS
        0xA: not n,  # PL
        0xB: n,  # MI
        0xC: n == v,  # GE
        0xD: n != v,  # LT
        0xE: not z and n == v,  # GT
        0xF: z or n != v,  # LE
    }[condition]


def add_flags(destination: int, source: int, size: int) -> tuple[int, bool, bool, bool, bool]:
    """ADD's result and N Z V C by PRM Table 3-18's formulas, bit by bit.

    V = Sm.Dm.~Rm + ~Sm.~Dm.Rm and C = Sm.Dm + ~Rm.Dm + Sm.~Rm, where Sm, Dm
    and Rm are the most significant bits of source, destination and result.
    Written from the table, not from the core's arithmetic.
    """
    bits = 8 * size
    mask = (1 << bits) - 1
    result = (destination + source) & mask
    sm, dm, rm = source >> (bits - 1) & 1, destination >> (bits - 1) & 1, result >> (bits - 1) & 1
    v = (sm and dm and not rm) or (not sm and not dm and rm)
    c = (sm and dm) or (not rm and dm) or (sm and not rm)
    return result, bool(rm), result == 0, bool(v), bool(c)


def sub_flags(destination: int, source: int, size: int) -> tuple[int, bool, bool, bool, bool]:
    """SUB's (and CMP's) result and N Z V C by PRM Table 3-18's formulas.

    V = ~Sm.Dm.~Rm + Sm.~Dm.Rm and C = Sm.~Dm + Rm.~Dm + Sm.Rm.
    """
    bits = 8 * size
    mask = (1 << bits) - 1
    result = (destination - source) & mask
    sm, dm, rm = source >> (bits - 1) & 1, destination >> (bits - 1) & 1, result >> (bits - 1) & 1
    v = (not sm and dm and not rm) or (sm and not dm and rm)
    c = (sm and not dm) or (rm and not dm) or (sm and rm)
    return result, bool(rm), result == 0, bool(v), bool(c)


def assert_flags(cpu, n: bool, z: bool, v: bool, c: bool, what: object = "") -> None:
    assert bool(cpu.SR & 8) is n, f"{what}: N"
    assert bool(cpu.SR & 4) is z, f"{what}: Z"
    assert bool(cpu.SR & 2) is v, f"{what}: V"
    assert bool(cpu.SR & 1) is c, f"{what}: C"


# -- encodings the gate corpus never executes ---------------------------------
# The gate runs 38,019 of the 45,815 defined first words.  Where the unrun
# words are the same handler with a field value or a field combination that
# nothing sampled, the manual gives the answer and the words can simply run.


def test_bra_takes_every_eight_bit_displacement():
    """BRA -- PC <- PC + d8, measured from the word after the opcode (PRM 4-55).

    UM Table 8-9: 10 clocks.  The gate corpus runs 131 of the 256 byte
    displacements; all 255 non-zero ones run here.  An odd target faults on
    the refill's first word fetch (UM 6.3.10), so the address-error handler
    runs instead.
    """
    cpu, bus = with_vectors(v3=0x3000)
    bus.load(0x3000, [NOP] * 4)
    for displacement in range(1, 256):
        restart(cpu, bus, [0x6000 | displacement])
        clocks = cpu.step()
        target = 0x1002 + sign_extend_8(displacement)
        if target & 1:
            assert cpu.PC == 0x3000, f"odd target {target:#x} must fault (UM 6.3.10)"
        else:
            assert cpu.PC == target, f"BRA.b {displacement:#04x}"
            assert clocks == 10  # UM Table 8-9


def test_bra_and_bsr_take_a_sixteen_bit_displacement():
    """A zero byte displacement means the next word is a 16-bit one (PRM 4-55, 4-59).

    UM Table 8-9: BRA 10 clocks, BSR 18.  BSR pushes the address after the
    displacement word (PRM 4-59).
    """
    cpu, bus = with_vectors()
    for displacement in (2, 4, 0x100, 0x7FFE, 0xFFFE, 0x8000):
        target = (0x1002 + sign_extend_16(displacement)) & 0xFFFFFFFF
        restart(cpu, bus, [0x6000, displacement])
        assert cpu.step() == 10
        assert cpu.PC == target

        restart(cpu, bus, [0x6100, displacement])
        assert cpu.step() == 18
        assert cpu.PC == target
        assert bus.long(cpu.R[15]) == 0x1004


def test_bcc_every_condition_against_every_ccr():
    """Bcc -- branch when PRM Table 3-19's condition holds (PRM 4-25).

    UM Table 8-9: taken 10 clocks, not taken 8 with a byte displacement.  The
    gate runs every condition and every displacement but only 1,696 of the
    3,584 (condition, displacement) words; here every condition meets every
    CCR value, against an independent statement of Table 3-19.
    """
    cpu, bus = with_vectors()
    for condition in range(2, 16):
        for ccr in range(16):
            restart(cpu, bus, [0x6000 | (condition << 8) | 0x04, NOP, NOP], sr=0x2700 | ccr)
            clocks = cpu.step()
            if condition_holds(condition, ccr):
                assert cpu.PC == 0x1006, (condition, ccr)
                assert clocks == 10
            else:
                assert cpu.PC == 0x1002, (condition, ccr)
                assert clocks == 8
            assert cpu.SR & 0x1F == ccr, "Bcc changes no condition code"


def test_bcc_not_taken_with_a_word_displacement_costs_twelve():
    """UM Table 8-9: a Bcc not taken over a 16-bit displacement is 12 clocks."""
    cpu, bus = with_vectors()
    restart(cpu, bus, [0x6700, 0x0010, NOP], sr=0x2700)  # BEQ with Z clear
    assert cpu.step() == 12
    assert cpu.PC == 0x1004  # past the displacement word


def test_bcc_takes_every_displacement():
    """Every byte displacement of a taken Bcc (BNE with Z clear; PRM 4-25)."""
    cpu, bus = with_vectors(v3=0x3000)
    bus.load(0x3000, [NOP] * 4)
    for displacement in range(1, 256):
        restart(cpu, bus, [0x6600 | displacement], sr=0x2700)
        cpu.step()
        target = 0x1002 + sign_extend_8(displacement)
        assert cpu.PC == (0x3000 if target & 1 else target), displacement


def test_moveq_every_register_and_every_byte():
    """MOVEQ -- Dn <- the 8-bit data sign-extended to 32 bits (PRM 4-134).

    PRM 4-134: N and Z from the result, V and C cleared, X unaffected.  UM
    Table 8-5: 4 clocks.  The gate runs 1,430 of the 2,048 words.
    """
    cpu, bus = with_vectors()
    for register in range(8):
        for data in range(256):
            for extend in (0, 0x10):
                restart(cpu, bus, [0x7000 | (register << 9) | data], sr=0x2700 | extend)
                cpu.R[register] = 0xDEADBEEF
                assert cpu.step() == 4
                expected = sign_extend_8(data) & 0xFFFFFFFF
                assert cpu.R[register] == expected, (register, data)
                assert_flags(cpu, bool(data & 0x80), data == 0, False, False, (register, data))
                assert cpu.SR & 0x10 == extend, "X unaffected"


def test_addq_and_subq_every_quick_value_on_a_data_register():
    """ADDQ/SUBQ -- add or subtract 1 to 8 (PRM 4-11, 4-182).

    PRM 4-11: the three-bit data field holds 1-7, and 0 stands for 8.  Flags
    are PRM Table 3-18's add and subtract rules (restated here), X a copy of
    C.  UM Table 8-5: 4 clocks to Dn for a byte or word, 8 for a long.
    """
    cpu, bus = with_vectors()
    for encoded in range(8):
        data = 8 if encoded == 0 else encoded
        for size_bits, size, clocks in ((0, 1, 4), (1, 2, 4), (2, 4, 8)):
            mask = (1 << (8 * size)) - 1
            for start in (0, 1, mask, mask >> 1, (mask >> 1) + 1, 0x5A):
                base = start if size == 4 else 0xAAAA0000 | start
                for add, flags in ((True, add_flags), (False, sub_flags)):
                    opcode = (0x5000 if add else 0x5100) | (encoded << 9) | (size_bits << 6) | 2
                    restart(cpu, bus, [opcode])
                    cpu.R[2] = base
                    assert cpu.step() == clocks
                    result, n, z, v, c = flags(start, data, size)
                    assert cpu.R[2] == (base & ~mask) | result, (add, data, size, start)
                    assert_flags(cpu, n, z, v, c, (add, data, size, start))
                    assert bool(cpu.SR & 0x10) is c, "X is a copy of C"


def test_addq_and_subq_on_an_address_register_touch_the_whole_register():
    """ADDQ/SUBQ #,An -- all 32 bits whatever the size, and no flag changes.

    PRM 4-11, 4-182: with an address register destination the whole register
    is used regardless of the size and the condition codes are not affected.
    The clocks are not asserted: UM Table 8-5 prints 4 for ADDQ.W #,An and 8
    for SUBQ.W #,An, and the gate corpus (118 ADDQ.W #,An cases) says 8 for
    both; docs/coverage.md, "Open gaps".
    """
    cpu, bus = with_vectors()
    for encoded in range(8):
        data = 8 if encoded == 0 else encoded
        for size_bits in (1, 2):  # word and long; a byte An form does not exist
            for subtract, sign in ((0, 1), (1, -1)):
                opcode = 0x5000 | (encoded << 9) | (subtract << 8) | (size_bits << 6) | 0x0A
                restart(cpu, bus, [opcode], sr=0x271F)  # every flag set
                cpu.R[10] = 0x0001FFFF
                cpu.step()
                assert cpu.R[10] == (0x0001FFFF + sign * data) & 0xFFFFFFFF
                assert cpu.SR & 0x1F == 0x1F, "no condition code changes"


#: The (source mode, destination mode, size) combinations of MOVE that the
#: gate corpus never runs, from docs/coverage.md.  Memory sources hold
#: $A1B2C3D4 at $4000 (absolute) or at $1020 (PC-relative); every
#: destination but one is $4100.
MOVE_GAPS = (
    # (name, program, size, source value)
    ("(xxx).W -> (xxx).W, byte", [0x11F8, 0x4000, 0x4100], 1, 0xA1),
    ("(xxx).W -> (xxx).L, byte", [0x13F8, 0x4000, 0x0000, 0x4100], 1, 0xA1),
    ("(xxx).L -> (xxx).L, byte", [0x13F9, 0x0000, 0x4000, 0x0000, 0x4100], 1, 0xA1),
    ("(d16,PC) -> (xxx).W, byte", [0x11FA, 0x001E, 0x4100], 1, 0xA1),
    ("(d8,PC,Xn) -> (xxx).W, byte", [0x11FB, 0x001E, 0x4100], 1, 0xA1),
    ("(xxx).W -> Dn, word", [0x3038, 0x4000], 2, 0xA1B2),
    ("(xxx).W -> (xxx).L, word", [0x33F8, 0x4000, 0x0000, 0x4100], 2, 0xA1B2),
    ("(xxx).L -> (xxx).L, word", [0x33F9, 0x0000, 0x4000, 0x0000, 0x4100], 2, 0xA1B2),
    ("(d16,PC) -> (xxx).W, word", [0x31FA, 0x001E, 0x4100], 2, 0xA1B2),
    ("(d16,PC) -> (xxx).L, word", [0x33FA, 0x001E, 0x0000, 0x4100], 2, 0xA1B2),
    ("(d8,PC,Xn) -> (xxx).L, word", [0x33FB, 0x001E, 0x0000, 0x4100], 2, 0xA1B2),
    ("#<data> -> (xxx).L, word", [0x33FC, 0x1234, 0x0000, 0x4100], 2, 0x1234),
    ("(xxx).W -> (xxx).L, long", [0x23F8, 0x4000, 0x0000, 0x4100], 4, 0xA1B2C3D4),
    ("(xxx).L -> (xxx).W, long", [0x21F9, 0x0000, 0x4000, 0x4100], 4, 0xA1B2C3D4),
    ("(xxx).L -> (xxx).L, long", [0x23F9, 0x0000, 0x4000, 0x0000, 0x4100], 4, 0xA1B2C3D4),
    ("(d8,PC,Xn) -> (xxx).L, long", [0x23FB, 0x001E, 0x0000, 0x4100], 4, 0xA1B2C3D4),
    ("#<data> -> (xxx).W, long", [0x21FC, 0x1234, 0x5678, 0x4100], 4, 0x12345678),
)


@pytest.mark.parametrize(("name", "program", "size", "value"), MOVE_GAPS)
def test_move_combinations_the_gate_never_runs(name, program, size, value):
    """MOVE -- destination <- source; N Z from the value, V C cleared, X kept (PRM 4-116).

    The seventeen (source mode, destination mode, size) triples the gate
    corpus leaves unrun, listed in docs/coverage.md.  The PC-relative forms
    reach $1020: the displacement is measured from the extension word at
    $1002 (PRM 2.2.11, 2.2.12), and the index register D0 is zero.
    """
    cpu, bus = with_vectors()
    restart(cpu, bus, program, sr=0x2710)  # X set, to see it kept
    cpu.R[0] = 0
    for address in (0x4000, 0x1020):
        bus.set_long(address, 0xA1B2C3D4)
    bus.set_long(0x4100, 0)
    cpu.step()
    if "Dn" in name:
        assert cpu.R[0] & 0xFFFF == value, name
    else:
        written = {1: bus.memory[0x4100], 2: bus.word(0x4100), 4: bus.long(0x4100)}[size]
        assert written == value, name
    msb = 1 << (8 * size - 1)
    assert_flags(cpu, bool(value & msb), value == 0, False, False, name)
    assert cpu.SR & 0x10, f"{name}: X unaffected"


def test_addi_word_to_absolute_short():
    """ADDI.W #d,(xxx).W -- the one (size, mode) pair of ADDI the gate never runs.

    PRM 4-9: destination <- destination + immediate data.  UM Table 8-5: 12
    clocks plus UM Table 8-1's 8 for a (xxx).W word operand, 20 in all.
    """
    cpu, bus = with_vectors()
    restart(cpu, bus, [0x0678, 0x1111, 0x4000])
    bus.set_word(0x4000, 0x2222)
    assert cpu.step() == 20
    assert bus.word(0x4000) == 0x3333
    assert not cpu.SR & 0x1F


# -- behavioural paths no corpus case reaches ---------------------------------


def test_the_illegal_instruction_takes_vector_four():
    """ILLEGAL and undefined words -- vector 4 (PRM 4-107; UM 6.3.6, 6.2.5).

    The gate corpus has ILLEGAL_LINEA and ILLEGAL_LINEF files but not one case
    that takes vector 4.  Asserted: the vector, and UM 6.2.5's sequence -- the
    status register saved in the frame, S set, T cleared.  Not asserted: the
    stacked PC, which UM 6.3.6 describes only as "similar to that for traps"
    (docs/coverage.md, "Open gaps").
    """
    cpu, bus = with_vectors(v4=0x3000)
    bus.load(0x3000, [NOP] * 4)
    for word in (ILLEGAL, 0x4AFD, 0x4E7A, 0x42C0):  # ILLEGAL; bad TAS EA; MOVEC; MOVE from CCR
        restart(cpu, bus, [word], sr=0x2000)
        cpu.step()
        assert cpu.PC == 0x3000, f"{word:04X}"
        status, _ = frame(bus, cpu)
        assert status == 0x2000, "the status register from before (UM 6.2.5)"
        assert cpu.SR & 0x2000 and not cpu.SR & 0x8000, "S set, T cleared"
        assert cpu.R[15] == STACK - 6, "a three-word frame (UM Figure 6-5)"


def test_the_illegal_instruction_is_taken_in_user_mode_on_the_supervisor_stack():
    """UM 6.2.5: exception processing enters supervisor mode and uses the SSP."""
    cpu, bus = with_vectors(v4=0x3000)
    bus.load(0x3000, [NOP] * 4)
    restart(cpu, bus, [ILLEGAL], sr=0x0000, sp=0x9000)  # user mode, USP = $9000
    cpu.ssp = STACK  # the inactive stack pointer, in user mode
    cpu.step()
    assert cpu.PC == 0x3000
    assert cpu.SR & 0x2000
    assert cpu.ssp == STACK - 6 and cpu.usp == 0x9000


def test_divide_by_zero_takes_vector_five_and_leaves_the_dividend():
    """DIVU/DIVS by zero -- vector 5, the next instruction's address stacked.

    PRM 4-96, 4-93: a zero divisor traps.  UM 6.3.5: the zero-divide, CHK and
    TRAPV exceptions stack the address of the next instruction.  The
    destination register is not written.  The flags are *not* asserted: PRM
    Table 3-18 leaves them undefined here, the pinned gate corpus has no
    divide by zero (its issue #3), and this core's values come from WinUAE
    (T2) -- docs/coverage.md, "Open gaps".
    """
    cpu, bus = with_vectors(v5=0x3000)
    bus.load(0x3000, [NOP] * 4)
    for word in (0x80C1, 0x81C1):  # DIVU.W D1,D0 and DIVS.W D1,D0
        restart(cpu, bus, [word, NOP], sr=0x2000)
        cpu.R[0], cpu.R[1] = 0x12345678, 0
        cpu.step()
        assert cpu.PC == 0x3000, f"{word:04X}"
        assert cpu.R[0] == 0x12345678
        status, stacked = frame(bus, cpu)
        # Only the system byte: the stacked CCR holds the undefined flags.
        assert status & 0xFF00 == 0x2000
        assert stacked == 0x1002, "the next instruction (UM 6.3.5)"


def test_divu_overflow_at_the_boundary_leaves_the_operands_alone():
    """DIVU -- V set and the destination unchanged on overflow (PRM 4-96).

    The boundary -- the dividend's high word exactly the divisor, the smallest
    dividend that overflows -- is an edge case the gate corpus lacks (its
    issue #3).  One below it is the largest quotient that still fits.  N, Z
    and C after an overflow are undefined in PRM 4-96 and are not asserted.
    """
    cpu, bus = with_vectors()
    for divisor in (1, 2, 0x1234, 0x7FFF, 0x8000, 0xFFFF):
        dividend = divisor << 16
        restart(cpu, bus, [0x80C1, NOP])
        cpu.R[0], cpu.R[1] = dividend, divisor
        cpu.step()
        assert cpu.SR & 2, f"divisor {divisor:#x}: V set"
        assert cpu.R[0] == dividend, "destination unchanged"
        assert cpu.PC == 0x1002, "overflow is not an exception"

        dividend = (divisor << 16) - 1
        restart(cpu, bus, [0x80C1, NOP])
        cpu.R[0], cpu.R[1] = dividend, divisor
        cpu.step()
        quotient, remainder = divmod(dividend, divisor)
        assert quotient <= 0xFFFF
        assert cpu.R[0] == (remainder << 16) | quotient
        # PRM 4-96: N and Z of the quotient, V and C cleared.
        assert_flags(cpu, bool(quotient & 0x8000), quotient == 0, False, False, divisor)


def test_divs_at_the_signed_boundaries():
    """DIVS -- quotient and remainder at the edges of the signed range (PRM 4-93).

    PRM 4-93: the quotient is the low word and the remainder the high word,
    the remainder taking the dividend's sign; a quotient outside -32768 to
    32767 sets V and leaves the destination unchanged.
    """
    cpu, bus = with_vectors()
    cases = (
        (-32768 * 1, 1, -32768),  # the most negative quotient that fits
        (32767 * 2 + 1, 2, 32767),  # the most positive, with a remainder
        (-0x80000000, -1, None),  # overflow: 2^31 does not fit
        (32768, 1, None),  # overflow by one
        (-32769, 1, None),  # overflow by one, negative
        (7, -2, -3),  # remainder 1, the dividend's sign
        (-7, 2, -3),  # remainder -1
    )
    for dividend, divisor, quotient in cases:
        restart(cpu, bus, [0x81C1, NOP])
        cpu.R[0], cpu.R[1] = dividend & 0xFFFFFFFF, divisor & 0xFFFF
        cpu.step()
        if quotient is None:
            assert cpu.SR & 2, (dividend, divisor)
            assert cpu.R[0] == dividend & 0xFFFFFFFF
            continue
        remainder = dividend - quotient * divisor
        expected = ((remainder & 0xFFFF) << 16) | (quotient & 0xFFFF)
        assert cpu.R[0] == expected, (dividend, divisor)
        assert_flags(cpu, quotient < 0, quotient == 0, False, False, (dividend, divisor))


def test_multiply_at_the_operand_boundaries():
    """MULU/MULS -- the 32-bit product of two words (PRM 4-141, 4-139).

    The gate never multiplies by 0, by $FFFF or by $8000.  PRM: N and Z from
    the 32-bit result, V and C cleared.
    """
    cpu, bus = with_vectors()
    unsigned = ((0, 0), (0, 0xFFFF), (0xFFFF, 0), (0xFFFF, 0xFFFF), (1, 0x8000))
    for destination, source in unsigned:
        restart(cpu, bus, [0xC0C1, NOP])  # MULU.W D1,D0
        cpu.R[0], cpu.R[1] = 0xABCD0000 | destination, source
        cpu.step()
        product = destination * source
        assert cpu.R[0] == product, (destination, source)
        assert_flags(cpu, bool(product & 0x80000000), product == 0, False, False)

    signed = ((0x8000, 0x8000), (0xFFFF, 0xFFFF), (0x8000, 0xFFFF), (0, 0x8000), (0x7FFF, 0x8000))
    for destination, source in signed:
        restart(cpu, bus, [0xC1C1, NOP])  # MULS.W D1,D0
        cpu.R[0], cpu.R[1] = 0xABCD0000 | destination, source
        cpu.step()
        product = (sign_extend_16(destination) * sign_extend_16(source)) & 0xFFFFFFFF
        assert cpu.R[0] == product, (destination, source)
        assert_flags(cpu, bool(product & 0x80000000), product == 0, False, False)


def test_dbcc_falls_through_when_the_count_expires():
    """DBcc -- the loop ends when the counter passes -1 (PRM 4-91).

    PRM 4-91: with the condition false, the low word of Dn is decremented;
    at -1 execution continues with the next instruction, otherwise it
    branches.  UM Table 8-9: 14 clocks expired, 10 branching.  Neither corpus
    decrements a counter to -1 (their registers are random), so the path that
    ends every real DBcc loop is otherwise untested below the MAME lockstep.
    """
    cpu, bus = with_vectors()
    restart(cpu, bus, [0x51C8, 0xFFFE, NOP], sr=0x2700)  # DBF D0,$1000
    cpu.R[0] = 0xABCD0000
    assert cpu.step() == 14
    assert cpu.R[0] == 0xABCDFFFF, "the low word is -1, the high word untouched"
    assert cpu.PC == 0x1004, "the next instruction"

    restart(cpu, bus, [0x51C8, 0xFFFE, NOP], sr=0x2700)
    cpu.R[0] = 0xABCD0001
    assert cpu.step() == 10
    assert cpu.R[0] == 0xABCD0000
    assert cpu.PC == 0x1000, "the branch target"


def test_dbcc_runs_a_loop_body_count_plus_one_times():
    """A DBF loop runs its body Dn + 1 times, then falls through (PRM 4-91)."""
    cpu, bus = with_vectors()
    restart(cpu, bus, [NOP, 0x51C8, 0xFFFC, NOP], sr=0x2700)  # NOP; DBF D0,$1000
    cpu.R[0] = 4
    bodies = 0
    for _ in range(40):
        if cpu.PC == 0x1006:
            break
        if cpu.PC == 0x1000:
            bodies += 1
        cpu.step()
    assert bodies == 5
    assert cpu.R[0] == 0x0000FFFF


def test_movem_with_an_empty_and_a_full_register_list():
    """MOVEM -- a mask may name no register or all sixteen (PRM 4-128).

    UM Table 8-10: registers to memory, word, 8 + 4n clocks; memory to
    registers, word, (An) 12 + 4n; n the number of registers.  Word loads are
    sign-extended to 32 bits (PRM 4-128).  Neither corpus has an empty mask
    or a full one.
    """
    cpu, bus = with_vectors()
    restart(cpu, bus, [0x48A0, 0x0000, NOP])  # MOVEM.W <none>,-(A0)
    cpu.R[8] = 0x5000
    assert cpu.step() == 8
    assert cpu.R[8] == 0x5000, "no register moved, so A0 did not move"
    assert not [entry for entry in bus.log if entry[0] in ("ww", "wb")]

    restart(cpu, bus, [0x4890, 0xFFFF, NOP])  # MOVEM.W D0-D7/A0-A7,(A0)
    for index in range(16):
        cpu.R[index] = 0x11110000 + index
    cpu.R[8] = 0x5000
    assert cpu.step() == 8 + 4 * 16
    for index in range(16):
        assert bus.word(0x5000 + 2 * index) == cpu.R[index] & 0xFFFF, index

    restart(cpu, bus, [0x4C90, 0xFFFF, NOP])  # MOVEM.W (A0),D0-D7/A0-A7
    for index in range(16):
        bus.set_word(0x5000 + 2 * index, 0x8000 + index)
    cpu.R[8] = 0x5000
    assert cpu.step() == 12 + 4 * 16
    for index in range(16):
        assert cpu.R[index] == 0xFFFF8000 + index, index


def test_the_trace_exception_is_taken_after_the_instruction():
    """Trace -- vector 9 after an instruction that began with T set (UM 6.3.8).

    UM 6.3.8 and 6.2.5: the saved status register still has T; the handler
    runs with T cleared and S set; the stacked PC is the next instruction.
    UM Table 8-14: 34 clocks.  The gate corpus captures its final state before
    the trace exception (its issue #2), so no case takes vector 9.
    """
    cpu, bus = with_vectors(v9=0x3000)
    bus.load(0x3000, [NOP] * 4)
    restart(cpu, bus, [NOP, NOP], sr=0xA700)
    cpu.step()
    assert cpu.PC == 0x1002
    assert cpu.step() == 34
    assert cpu.PC == 0x3000
    status, stacked = frame(bus, cpu)
    assert status == 0xA700
    assert stacked == 0x1002
    assert cpu.SR & 0xA000 == 0x2000


def test_a_traced_trap_takes_the_trap_then_the_trace():
    """UM 6.3.8: an exception the instruction forces is processed before trace.

    TRAP with T set enters the trap, and the trace exception follows, taken
    from the first instruction of the trap handler.
    """
    cpu, bus = with_vectors(v32=0x3000, v9=0x3100)
    bus.load(0x3000, [NOP] * 4)
    bus.load(0x3100, [NOP] * 4)
    restart(cpu, bus, [0x4E40, NOP], sr=0xA700)  # TRAP #0
    cpu.step()
    assert cpu.PC == 0x3000
    cpu.step()
    assert cpu.PC == 0x3100, "then the trace exception"
    _, stacked = frame(bus, cpu)
    assert stacked == 0x3000, "stacked from the trap handler's first instruction"


def test_an_address_error_inside_exception_processing_sets_i_slash_n():
    """A fault while taking an exception marks the frame not-an-instruction.

    UM Figure 6-7 and 6.3.9.1: in the group 0 frame's special status word,
    bit 4 is R/W (1 = read), bit 3 is I/N (1 = the cycle was not part of an
    instruction), bits 2-0 the function code; the access address follows.
    Here TRAP #0's vector points at an odd address, so the first fetch of the
    handler faults while the trap is still being processed.  Neither corpus
    reaches it: their vectors are always even.  The stacked PC and IR are not
    asserted (UM 6.2.5: unpredictable).
    """
    cpu, bus = with_vectors(v3=0x3000)
    bus.load(0x3000, [NOP] * 4)
    bus.set_long(32 * 4, 0x00004001)
    restart(cpu, bus, [0x4E40, NOP], sr=0x2000)
    cpu.step()
    assert cpu.PC == 0x3000, "the address-error handler runs"
    information = bus.word(cpu.R[15])
    assert information & 0x10, "R/W: a read"
    assert information & 0x08, "I/N: not part of an instruction"
    assert information & 0x07 == 6, "supervisor program space (UM Table 3-2)"
    assert bus.long(cpu.R[15] + 2) == 0x00004001, "the access address"


def test_a_fault_while_taking_an_address_error_halts_the_processor():
    """The double bus fault halts the processor until reset (UM 5.4.4, 6.3.9.1).

    An odd supervisor stack pointer makes every frame write fault, so the
    address error taken for the first fault cannot write its own frame.  No
    corpus case has an odd stack pointer.
    """
    cpu, bus = with_vectors()
    restart(cpu, bus, [0x4E40], sr=0x2000, sp=0x8001)
    cpu.step()
    assert cpu.halted
    registers = (list(cpu.R), cpu.SR, cpu.PC)
    cpu.step()
    assert cpu.halted and (list(cpu.R), cpu.SR, cpu.PC) == registers, "halted does nothing"
    cpu.reset()
    assert not cpu.halted, "only a reset restarts it"


def test_a_bus_error_takes_vector_two_with_the_group_zero_frame():
    """BERR -- vector 2 and the seven-word frame (UM 6.3.9.1, Figure 6-7).

    The host raises :class:`BusError` from a bus callable to assert BERR.
    Asserted: the vector, R/W, I/N, the function code, the access address,
    and the saved status register.  The stacked PC and IR are unpredictable
    (UM 6.2.5) and not asserted.  No corpus models BERR.
    """
    bus = Bus()
    bad = 0x900000

    def read_word(address):
        if address & 0xFF0000 == bad:
            raise BusError(address)
        return bus.read_word(address)

    bus.set_long(0, STACK)
    bus.set_long(4, START)
    bus.set_long(2 * 4, 0x3000)
    bus.load(0x3000, [NOP] * 4)
    bus.load(START, [0x3039, 0x0090, 0x0000, NOP])  # MOVE.W $900000.L,D0
    cpu = M68000CPU(bus.read_byte, read_word, bus.write_byte, bus.write_word)
    cpu.reset()
    cpu.step()
    assert cpu.PC == 0x3000, "the bus-error handler runs"
    sp = cpu.R[15]
    assert sp == STACK - 14, "a seven-word frame"
    information = bus.word(sp)
    assert information & 0x10, "R/W: a read"
    assert not information & 0x08, "I/N: part of an instruction"
    assert information & 0x07 == 5, "supervisor data space (UM Table 3-2)"
    assert bus.long(sp + 2) == bad, "the access address"
    assert bus.word(sp + 8) == 0x2700, "the status register from before"


def test_reset_loads_the_stack_pointer_and_program_counter_from_the_vectors():
    """Reset -- SSP from $000000, PC from $000004, S set, T clear, mask 7 (UM 6.3.1).

    Nothing is stacked.
    """
    bus = Bus()
    bus.set_long(0, 0x00012340)
    bus.set_long(4, 0x00005000)
    bus.load(0x5000, [NOP] * 4)
    cpu = M68000CPU(bus.read_byte, bus.read_word, bus.write_byte, bus.write_word)
    cpu.SR = 0x8004  # T set, user mode, mask 0
    cpu.reset()
    assert cpu.ssp == cpu.R[15] == 0x00012340
    assert cpu.PC == 0x00005000
    assert cpu.SR & 0xA700 == 0x2700, "S set, T cleared, mask 7"
    assert not [entry for entry in bus.log if entry[0] in ("ww", "wb")], "nothing stacked"


def test_the_stack_pointers_can_be_read_and_written_in_either_mode():
    """``usp`` and ``ssp`` name the two stack pointers; A7 is the current one (PRM 1.3).

    The corpus harness loads the registers directly, so neither property's
    setter is reached by any corpus case.
    """
    cpu, _bus = with_vectors()
    cpu.set_sr(0x2000)
    cpu.R[15] = 0x1111
    cpu.usp = 0x2222
    assert cpu.ssp == 0x1111 and cpu.usp == 0x2222
    cpu.ssp = 0x3333
    assert cpu.R[15] == 0x3333
    cpu.set_sr(0x0000)
    assert cpu.R[15] == 0x2222
    cpu.usp = 0x4444
    assert cpu.R[15] == 0x4444
    cpu.ssp = 0x5555
    assert cpu.ssp == 0x5555 and cpu.R[15] == 0x4444


def test_chk_with_a_zero_register_does_not_trap():
    """CHK -- no trap while 0 <= Dn <= bound (PRM 4-69).

    Dn = 0 is the one CHK input no corpus case has.  PRM 4-69 defines N only
    for the trapping cases and calls Z, V and C undefined, so no flag is
    asserted here (docs/coverage.md, "Open gaps").
    """
    cpu, bus = with_vectors(v6=0x3000)
    bus.load(0x3000, [NOP] * 4)
    for bound in (0, 1, 0x7FFF):
        restart(cpu, bus, [0x4181, NOP])  # CHK.W D1,D0
        cpu.R[0], cpu.R[1] = 0, bound
        cpu.step()
        assert cpu.PC == 0x1002, f"bound {bound:#x}: no trap"


def test_the_reset_instruction_calls_the_host_hook_and_changes_nothing_else():
    """RESET -- the RESET line is pulsed; the processor state is unaffected (PRM 6-83).

    UM Table 8-12: 132 clocks.  The host sees the pulse through
    ``reset_devices``; no corpus case sets it.
    """
    cpu, bus = with_vectors()
    pulses = []
    cpu.reset_devices = lambda: pulses.append(True)
    restart(cpu, bus, [0x4E70, NOP], sr=0x2000)
    registers = list(cpu.R)
    assert cpu.step() == 132
    assert pulses == [True]
    assert cpu.PC == 0x1002
    assert cpu.R == registers and cpu.SR == 0x2000


# -- boundary operands, where the corpus's random values never land -----------
# The gate reaches 3 of 36 (destination class x source class) pairs of ADD at
# word size and 2 at long size: its operands are random, so 0, 1, all ones,
# the largest positive and the most negative value almost never occur.  The
# expected flags are PRM Table 3-18's formulas (add_flags, sub_flags above).

BOUNDARY_VALUES = {
    2: (0x0000, 0x0001, 0x7FFF, 0x8000, 0xFFFF),
    4: (0x00000000, 0x00000001, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF),
}


@pytest.mark.parametrize("size", [2, 4])
def test_add_sub_and_cmp_at_every_pair_of_boundary_operands(size):
    """ADD, SUB, CMP on every pair of 0, 1, max positive, min negative, all ones.

    PRM 4-4 (ADD), 4-174 (SUB), 4-75 (CMP); flags PRM Table 3-18: X takes C
    for ADD and SUB, and CMP leaves X alone and does not write the
    destination.
    """
    cpu, bus = with_vectors()
    long_bits = 0x0080 if size == 4 else 0x0040
    for destination in BOUNDARY_VALUES[size]:
        for source in BOUNDARY_VALUES[size]:
            for base, flags, writes, keeps_x in (
                (0xD001, add_flags, True, False),  # ADD D1,D0
                (0x9001, sub_flags, True, False),  # SUB D1,D0
                (0xB001, sub_flags, False, True),  # CMP D1,D0
            ):
                for extend in (0x00, 0x10):
                    restart(cpu, bus, [base | long_bits, NOP], sr=0x2700 | extend)
                    cpu.R[0], cpu.R[1] = destination, source
                    cpu.step()
                    result, n, z, v, c = flags(destination, source, size)
                    what = (f"{base | long_bits:04X}", f"{destination:#x}", f"{source:#x}")
                    assert cpu.R[0] == (result if writes else destination), what
                    assert_flags(cpu, n, z, v, c, what)
                    x = extend if keeps_x else (0x10 if c else 0)
                    assert cpu.SR & 0x10 == x, f"{what}: X"


@pytest.mark.parametrize("size", [2, 4])
def test_addx_subx_and_negx_at_the_boundaries(size):
    """ADDX, SUBX, NEGX -- X joins the operation and Z is only ever cleared.

    PRM 4-14 (ADDX): destination + source + X; 4-184 (SUBX): destination -
    source - X; 4-146 (NEGX): 0 - destination - X.  PRM Table 3-18: Z is
    cleared by a nonzero result and otherwise unchanged; X takes C.  V and C
    follow the ADD and SUB formulas applied to the whole operation.
    """
    cpu, bus = with_vectors()
    long_bits = 0x0080 if size == 4 else 0x0040
    mask = (1 << (8 * size)) - 1
    for destination in BOUNDARY_VALUES[size]:
        for source in BOUNDARY_VALUES[size]:
            for extend in (0, 1):
                for z_before in (0x00, 0x04):
                    sr = 0x2700 | (0x10 if extend else 0) | z_before
                    for name, word, operation in (
                        ("ADDX", 0xD101, lambda d, s, x: d + s + x),
                        ("SUBX", 0x9101, lambda d, s, x: d - s - x),
                    ):
                        restart(cpu, bus, [word | long_bits, NOP], sr=sr)
                        cpu.R[0], cpu.R[1] = destination, source
                        cpu.step()
                        exact = operation(destination, source, extend)
                        result = exact & mask
                        what = (name, size, destination, source, extend, z_before)
                        assert cpu.R[0] == result, what
                        assert_extended_flags(
                            cpu, name, destination, source, extend, size, z_before, what
                        )
                restart(cpu, bus, [0x4000 | long_bits, NOP], sr=sr)  # NEGX D0
                cpu.R[0] = destination
                cpu.step()
                assert cpu.R[0] == (0 - destination - extend) & mask
                assert_extended_flags(
                    cpu,
                    "SUBX",
                    0,
                    destination,
                    extend,
                    size,
                    z_before,
                    ("NEGX", destination, extend),
                )


def assert_extended_flags(cpu, name, destination, source, extend, size, z_before, what):
    """PRM Table 3-18 for ADDX/SUBX/NEGX, from the formulas, not from the core.

    The operation with X is one addition (or subtraction) of source + X, so
    the result's sign bit is the one the formulas use; V and C are those of
    the whole operation.
    """
    bits = 8 * size
    mask = (1 << bits) - 1
    if name == "ADDX":
        result = (destination + source + extend) & mask
    else:
        result = (destination - source - extend) & mask
    sm, dm, rm = source >> (bits - 1) & 1, destination >> (bits - 1) & 1, result >> (bits - 1) & 1
    if name == "ADDX":
        v = (sm and dm and not rm) or (not sm and not dm and rm)
        c = (sm and dm) or (not rm and dm) or (sm and not rm)
    else:
        v = (not sm and dm and not rm) or (sm and not dm and rm)
        c = (sm and not dm) or (rm and not dm) or (sm and rm)
    z = bool(z_before) if result == 0 else False
    assert_flags(cpu, bool(rm), z, bool(v), bool(c), what)
    assert bool(cpu.SR & 0x10) is bool(c), f"{what}: X"
