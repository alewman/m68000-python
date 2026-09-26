"""Tests written for the mutants that survived the whole suite (docs/mutation.md).

scripts/mutate.py seeds one semantic change at a time into a copy of the
core and runs the suite against it.  A mutant that no test fails is a hole
in the evidence.  Each test below closes one such hole where the Motorola
manuals decide the answer, and names the mutant it was written for; the
mutants that survive because the manuals do not decide them (and the two
that are equivalent to the core) are listed, with what would settle them,
in docs/mutation.md -- they have no test here, by design.

One test (the E-clock wait) rests on MAME 0.285 rather than on the manual,
because the manual gives only the principle; it says so.
"""

from __future__ import annotations

from test_coverage_gaps import NOP, STACK, frame, restart, with_vectors

# -- M3: ADDQ/SUBQ #,An wrap around 32 bits -----------------------------------


def test_addq_and_subq_to_an_address_register_wrap_at_32_bits():
    """ADDQ/SUBQ #,An -- the whole 32-bit register, modulo 2^32 (PRM 4-11, 4-182).

    Mutant M3 dropped the 32-bit mask and survived: no test carried an
    address register across zero or across $FFFFFFFF.
    """
    cpu, bus = with_vectors()
    cases = (
        (0x5188, 0x00000004, 0xFFFFFFFC),  # SUBQ.L #8,A0
        (0x5148, 0x00000000, 0xFFFFFFF8),  # SUBQ.W #8,A0: still the whole register
        (0x5288, 0xFFFFFFFF, 0x00000000),  # ADDQ.L #1,A0
        (0x5048, 0xFFFFFFFA, 0x00000002),  # ADDQ.W #8,A0
    )
    for opcode, before, after in cases:
        restart(cpu, bus, [opcode, NOP])
        cpu.R[8] = before
        cpu.step()
        assert cpu.R[8] == after, f"{opcode:04X} from {before:#010x}"


# -- D7, D9: divide by zero with a zero dividend, and its clocks ---------------


def test_divide_by_zero_traps_whatever_the_dividend():
    """A zero divisor traps even when the dividend is zero too (PRM 4-96, 4-93).

    PRM: division by zero causes a trap; the dividend does not enter into
    it.  Mutant D7 let DIVU 0/0 through and survived: every divide-by-zero
    test used a nonzero dividend.
    """
    cpu, bus = with_vectors(v5=0x3000)
    bus.load(0x3000, [NOP] * 4)
    for word in (0x80C1, 0x81C1):  # DIVU.W D1,D0 and DIVS.W D1,D0
        restart(cpu, bus, [word, NOP], sr=0x2000)
        cpu.R[0], cpu.R[1] = 0, 0
        cpu.step()
        assert cpu.PC == 0x3000, f"{word:04X}: vector 5"
        assert cpu.R[0] == 0
        _, stacked = frame(bus, cpu)
        assert stacked == 0x1002


def test_exception_clocks_the_gate_never_measures():
    """UM Table 8-14: divide by zero 38 clocks plus the EA time; illegal 34.

    Table 8-1 gives the effective-address time added to the 38: none for Dn,
    4 for (An) and for a word immediate, 6 for -(An), 8 for (d16,An).  The
    gate corpus has no divide by zero and no case that takes vector 4, so
    mutant D9 (divide-by-zero entry 4 clocks short) survived it.
    """
    cpu, bus = with_vectors()
    programs = (
        ("DIVU D1,D0", [0x80C1, NOP], 38),
        ("DIVU (A1),D0", [0x80D1, NOP], 42),
        ("DIVU #0,D0", [0x80FC, 0x0000, NOP], 42),
        ("DIVS -(A1),D0", [0x81E1, NOP], 44),
        ("DIVS (d16,A1),D0", [0x81E9, 0x0010, NOP], 46),
    )
    for name, program, clocks in programs:
        restart(cpu, bus, program)
        cpu.R[0], cpu.R[1], cpu.R[9] = 0x1234, 0, 0x5000
        for address in (0x4FFC, 0x5000, 0x5010):
            bus.set_long(address, 0)
        assert cpu.step() == clocks, name
        assert cpu.PC == 0x2000 + 16 * 5, f"{name}: vector 5"

    restart(cpu, bus, [0x4AFC, NOP])
    assert cpu.step() == 34, "ILLEGAL"


# -- SP12: level 7 is taken on a transition, not while held ---------------------


def test_level_seven_held_and_reasserted_is_taken_once():
    """Level 7 interrupts on a change from a lower level to 7 (UM 6.3.2).

    A host that sets the same level again every step is common; while the
    level stays at 7 that is not a new transition.  Mutant SP12 re-armed the
    edge on every ``set_ipl(7)`` and survived: the existing scenario set the
    level once.
    """
    cpu, bus = with_vectors(v31=0x3000)
    bus.load(0x3000, [NOP] * 32)
    restart(cpu, bus, [NOP] * 8, sr=0x2700)
    entries = 0
    for _ in range(8):
        cpu.set_ipl(7)  # the host re-asserts the level it already holds
        before = cpu.R[15]
        cpu.step()
        if cpu.R[15] == before - 6:
            entries += 1
    assert entries == 1


# -- CY10: the E-clock wait of an autovectored acknowledge (MAME, T3) -----------


def test_autovector_clocks_at_each_e_clock_phase():
    """An autovectored interrupt: 44 clocks plus the E-clock wait, per phase.

    UM 5.1.4 and 6.3.2 give the principle -- a VPA acknowledge is synchronised
    to the E clock, one tenth of the CPU clock -- but not the count.  The
    count is MAME 0.285's (``vpa_sync`` then one clock after, m68000.cpp): the
    transfer waits for the next E-clock boundary, a period more if fewer than
    3 clocks remain, then one clock.  docs/validation.md (rung 6) records that
    the System 16B lockstep agrees with MAME at all ten phases.  This is T3
    evidence, not the manual's.  Mutant CY10 moved the boundary and survived:
    the existing phase test (tests/test_interrupts.py) accepts any set of
    clocks with more than one member (docs/history/worklog.md).
    """
    expected = {0: 55, 1: 54, 2: 53, 3: 52, 4: 51, 5: 50, 6: 49, 7: 58, 8: 57, 9: 56}
    for phase, clocks in expected.items():
        cpu, bus = with_vectors()
        restart(cpu, bus, [NOP] * 8, sr=0x2000)
        cpu.clock = phase  # the host's running clock count at the step
        cpu.set_ipl(1)
        assert cpu.step() == clocks, f"phase {phase}"
        assert cpu.last_acknowledge_phase == phase
        assert bus.long(STACK - 4) == 0x1000
