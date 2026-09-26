"""Behaviour pinned by running WinUAE's CPU-tester core, inside its hardware-checked scope.

validation/referees/ builds WinUAE's CPU tester (tonioni/WinUAE at
1977af501f6c, the 68000 core its generator emits with CPU_TESTER set) and
runs it one instruction at a time (docs/referees.md).  That tester is the
program Toni Wilen runs on real Amigas and corrects until the hardware
agrees, so what it says is **T2** -- a judge -- for what the tester checks on
hardware, and a detector (T3) elsewhere.  Each test below names why its case
lies inside that scope: a cputest preset (cputest/cputestgen.ini at the pin)
that generates the case with the undefined flags checked
(``feature_undefined_ccr=1``, which every 68000 preset sets), or a line of
the tester's readme or WinUAE's changelog (od-win32/winuaechangelog.txt)
reporting the behaviour verified.

The expected values are the referee's, written out here as rules; none is
taken from this core.  Where the referee and the gate corpus disagree, or
where the tester's scope does not reach, nothing is pinned here: those
questions are in docs/referees.md and docs/claims.md.
"""

from __future__ import annotations

import pytest
from conftest import Bus
from test_coverage_gaps import NOP, STACK, frame, restart, with_vectors

from m68000_python import M68000CPU
from m68000_python._core import BusError

X, N, Z, V, C = 0x10, 0x08, 0x04, 0x02, 0x01

# -- divide by zero: the flags (mutant D10) -----------------------------------


@pytest.mark.parametrize("incoming", [0x00, 0x1F])
@pytest.mark.parametrize(
    "dividend", [0x00001234, 0x00000000, 0x7FFF0000, 0x80001234, 0xFFFF0000, 0x00010000]
)
def test_divide_by_zero_flags(dividend, incoming):
    """DIVU/DIVS by zero -- the condition codes the trap stacks (T2).

    PRM Table 3-18 leaves them undefined.  WinUAE's 68000 rule
    (``divbyzero_special``, newcpu_common.cpp), run: DIVS clears N, V and C
    and sets Z; DIVU clears V and C, sets N if the dividend's upper word is
    negative and Z if it is zero.  X is kept.  In scope: the BASIC preset
    runs every DIVU/DIVS form with the undefined flags checked (an immediate
    divisor counts up from 0), and the changelog for 4.3.0 reports "DIVU and
    DIVS divide by zero condition codes are now 100% correct" for the 68000.
    Mutant D10, which changed the DIVS rule, survived every test before this.
    """
    upper = dividend >> 16
    expected = {
        0x80C1: (incoming & X) | (N if upper & 0x8000 else 0) | (Z if upper == 0 else 0),
        0x81C1: (incoming & X) | Z,
    }
    cpu, bus = with_vectors(v5=0x3000)
    bus.load(0x3000, [NOP] * 4)
    for opcode, ccr in expected.items():
        restart(cpu, bus, [opcode, NOP], sr=0x2700 | incoming)
        cpu.R[0], cpu.R[1] = dividend, 0
        cpu.step()
        status, pc = frame(bus, cpu)
        assert cpu.PC == 0x3000
        assert pc == 0x1002, "the next instruction (UM 6.3.5)"
        assert status & 0x1F == ccr, f"{opcode:04X} {dividend:08X}: {status & 0x1F:05b}"


# -- CHK with a zero register -------------------------------------------------


@pytest.mark.parametrize("incoming", [0x00, 0x1F])
@pytest.mark.parametrize(("bound", "traps"), [(5, False), (0, False), (0xFFFF, True)])
def test_chk_flags_when_the_register_is_zero(bound, traps, incoming):
    """CHK Dn = 0 -- N, V and C clear, Z set, X kept, trap or not (T2).

    PRM defines N only when CHK traps and leaves Z, V and C undefined.
    WinUAE's 68000 rule (``setchkundefinedflags``: C=V=0, Z from Dn = 0, N
    from Dn < 0), run.  In scope: the BASIC preset checks CHK's undefined
    flags, and the 4.3.0 changelog lists "CHK.W undefined flags fully
    emulated" among the differences the tester found on a 68000.  (Neither
    corpus has a case with Dn = 0: docs/coverage.md, open gap 4.)
    """
    cpu, bus = with_vectors(v6=0x3000)
    bus.load(0x3000, [NOP] * 4)
    restart(cpu, bus, [0x4181, NOP], sr=0x2700 | incoming)  # CHK D1,D0
    cpu.R[0], cpu.R[1] = 0, bound
    cpu.step()
    if traps:
        assert cpu.PC == 0x3000
        ccr = frame(bus, cpu)[0] & 0x1F
    else:
        assert cpu.PC == 0x1002
        ccr = cpu.SR & 0x1F
    assert ccr == (incoming & X) | Z


# -- illegal words: the stacked PC and the clocks ------------------------------


@pytest.mark.parametrize(
    ("word", "vector"),
    [(0x4AFC, 4), (0x4AFA, 4), (0x4AFB, 4), (0x4E7B, 4), (0xA123, 10), (0xF123, 11)],
)
def test_an_illegal_word_stacks_its_own_address(word, vector):
    """ILLEGAL and the other unexecuted words stack their own address, 34 clocks (T2).

    UM 6.3.6 says only "similar to that for traps", and no case of either
    corpus takes vector 4 (docs/coverage.md, open gap 2).  WinUAE's tester
    core, run, stacks the illegal word's own address for vectors 4, 10 and
    11 and adds 34 clocks for the exception (cputest/main.c,
    ``getexceptioncycles``).  In scope: the tester's "all" mode ends with
    every opcode the CPU does not implement ("ILLEGAL"), frames checked; the
    illegal-instruction exception is one of the instructions its cycle
    counting relies on being exact (cputest/readme.txt).
    """
    handler = 0x3000
    cpu, bus = with_vectors(**{f"v{vector}": handler})
    bus.load(handler, [NOP] * 4)
    restart(cpu, bus, [word, NOP], sr=0x2700)
    clocks = cpu.step()
    status, pc = frame(bus, cpu)
    assert cpu.PC == handler
    assert pc == 0x1000
    assert status == 0x2700
    assert clocks == 34


# -- bus errors: data reads and prefetches --------------------------------------

BERR_BASE = 0x880000


def _berr_cpu(program, *, at=0x1000, sr=0x2700):
    """A CPU whose bus raises BusError for every access to $880000-$8FFFFF."""
    bus = Bus()

    def guard(access):
        def guarded(address, *value):
            if address & 0xF80000 == BERR_BASE:
                raise BusError(address)
            return access(address, *value)

        return guarded

    bus.set_long(0, STACK)
    bus.set_long(4, at)
    bus.set_long(2 * 4, 0x3000)
    bus.load(0x3000, [NOP] * 4)
    bus.load(at, program)
    cpu = M68000CPU(
        guard(bus.read_byte), guard(bus.read_word), guard(bus.write_byte), guard(bus.write_word)
    )
    cpu.reset()
    cpu.SR = sr
    return cpu, bus


@pytest.mark.parametrize(
    ("name", "program", "a0", "pc", "a0_after"),
    [
        ("MOVE.W (A0),D0", [0x3010, NOP], BERR_BASE, 0x1002, BERR_BASE),
        ("MOVE.W (A0)+,D0", [0x3018, NOP], BERR_BASE, 0x1002, BERR_BASE + 2),
        ("MOVE.W -(A0),D0", [0x3020, NOP], BERR_BASE + 2, 0x1004, BERR_BASE),
        ("MOVE.L (A0),D0", [0x2010, NOP], BERR_BASE, 0x1002, BERR_BASE),
        ("ADD.W D0,(A0)", [0xD150, NOP], BERR_BASE, 0x1002, BERR_BASE),
    ],
)
def test_a_data_read_bus_error_frame(name, program, a0, pc, a0_after):
    """A bus error on an operand read: the stacked PC, IR, access word and An (T2).

    UM 6.2.5 calls the stacked PC unpredictable and no corpus models BERR.
    WinUAE's tester core, run with its bus-error region on the operand: the
    PC below, the instruction's own opcode in the IR slot and in bits 15-5 of
    the access word, R/W read, I/N clear, supervisor data space, and An moved
    by (An)+ and -(An) as shown.  In scope: the BESRC preset (source read
    bus errors, extra hardware) and the readme's "68000 read bus errors
    re-verified" (16.02.2020).
    """
    cpu, bus = _berr_cpu(program)
    cpu.R[8] = a0
    cpu.step()
    sp = cpu.R[15]
    assert cpu.PC == 0x3000, name
    assert sp == STACK - 14, name
    opcode = program[0]
    assert bus.word(sp) == (opcode & 0xFFE0) | 0x10 | 0x05, f"{name}: access word"
    assert bus.long(sp + 2) == BERR_BASE, f"{name}: access address"
    assert bus.word(sp + 6) == opcode, f"{name}: IR"
    assert bus.long(sp + 10) == pc, f"{name}: stacked PC"
    assert cpu.R[8] == a0_after, f"{name}: A0"


@pytest.mark.parametrize(
    ("name", "program", "at", "a0", "pc", "ir"),
    [
        ("NOP, its prefetch faults", [NOP, 0x1234], BERR_BASE - 4, 0, BERR_BASE, 0x1234),
        ("JMP (A0), the target fetch faults", [0x4ED0, NOP], 0x1000, BERR_BASE, 0x1002, 0x4ED0),
    ],
)
def test_a_prefetch_bus_error_frame(name, program, at, a0, pc, ir):
    """A bus error on an instruction fetch: the stacked PC and IR (T2).

    WinUAE's tester core, run with its bus-error region on the fetch: a NOP
    whose closing prefetch faults stacks the faulting address as its PC and
    the next opcode (already moved from IRC to IR) as IR; a JMP whose target
    fetch faults stacks the JMP's address + 2 and the JMP.  Access word: read, I/N clear, supervisor
    program space.  In scope: the BEPR and BEBR presets (prefetch and branch
    bus errors); readme 16.02.2020 "All prefetch bus error tests verified";
    changelog 5.3.0 "Bcc, BSR, DBcc, JMP, JSR, RTE, RTR, RTS confirmed having
    accurate bus error stack frame".
    """
    cpu, bus = _berr_cpu(program, at=at)
    cpu.R[8] = a0
    cpu.step()
    sp = cpu.R[15]
    assert cpu.PC == 0x3000, name
    assert bus.word(sp) == (ir & 0xFFE0) | 0x10 | 0x06, f"{name}: access word"
    assert bus.long(sp + 2) == BERR_BASE, f"{name}: access address"
    assert bus.word(sp + 6) == ir, f"{name}: IR"
    assert bus.long(sp + 10) == pc, f"{name}: stacked PC"


# -- an exception whose vector is odd ------------------------------------------


def test_trapv_with_an_odd_vector_stacks_trapv_as_the_ir():
    """TRAPV taken through an odd vector: the address error's IR is TRAPV itself (T2).

    The handler's first fetch faults while the trap is processed, and the
    group 0 frame's IR slot (and bits 15-5 of the access word) hold the
    decoder's opcode.  WinUAE's tester core, run: $4E76, the TRAPV.  MAME
    0.285's microcode agrees (T3, read: the taken path ``trpv3`` moves IRC
    into IR but never loads IRD).  In scope: the ODDEXC preset, which runs
    TRAPV, CHK, TRAP, DIVU and DIVS with odd exception vectors, and the 4.4.0
    changelog: "68000/010 odd exception vector generated address error stack
    frame is now correct.  Tester support added."  I/N is not asserted: see
    docs/history/worklog.md.
    """
    cpu, bus = with_vectors(v3=0x3000, v7=0x5001)
    bus.load(0x3000, [NOP] * 4)
    restart(cpu, bus, [0x4E76, 0x1234, NOP], sr=0x2702)  # TRAPV with V set
    cpu.step()
    sp = cpu.R[15]
    assert cpu.PC == 0x3000, "the address-error handler"
    assert bus.long(sp + 2) == 0x5001, "the access address: the odd vector"
    assert bus.word(sp + 6) == 0x4E76, "IR: TRAPV"
    assert bus.word(sp) & 0xFFE0 == 0x4E60, "access word bits 15-5: TRAPV"
    assert bus.long(sp + 10) == 0x1002, "stacked PC"
    assert bus.long(sp + 16) == 0x1002, "the TRAPV frame's PC beneath it"


# -- found by the referee sweep, decided by the manual ---------------------------


def test_a_bus_error_on_the_write_half_of_tas_is_a_bus_error():
    """TAS whose write cycle sees BERR takes the bus error exception (UM 6.3.9.1).

    The host contract (cpu.py) lets any bus callable raise BusError to
    assert BERR, and UM 6.3.9.1 makes BERR on any bus cycle a bus error
    exception.  TAS's write half went to the host's ``tas_write`` outside
    the core's bus-error handling, so the BusError escaped ``step()``.
    Found by validation/referees/bus_errors.py.  Asserted: vector 2, R/W =
    write, supervisor data space, the access address; the stacked PC and IR
    are not (UM 6.2.5: unpredictable; write bus errors lie outside what
    WinUAE's tester re-verified, docs/referees.md).
    """
    bus = Bus()

    def guard(write):
        def guarded(address, value):
            if address & 0xF80000 == BERR_BASE:
                raise BusError(address)
            write(address, value)

        return guarded

    bus.set_long(0, STACK)
    bus.set_long(4, 0x1000)
    bus.set_long(2 * 4, 0x3000)
    bus.load(0x3000, [NOP] * 4)
    bus.load(0x1000, [0x4AD0, NOP])  # TAS (A0)
    cpu = M68000CPU(bus.read_byte, bus.read_word, guard(bus.write_byte), guard(bus.write_word))
    cpu.reset()
    cpu.R[8] = BERR_BASE
    bus.log.clear()
    cpu.step()
    sp = cpu.R[15]
    assert ("rb", BERR_BASE, 0) in bus.log, "the read half completed"
    assert cpu.PC == 0x3000, "the bus-error handler"
    assert sp == STACK - 14
    information = bus.word(sp)
    assert not information & 0x10, "R/W: a write"
    assert information & 0x07 == 5, "supervisor data space"
    assert bus.long(sp + 2) == BERR_BASE
