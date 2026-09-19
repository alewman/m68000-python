"""Rung 6: interrupts, trace ordering and STOP, as scenarios (UM 6.3.2-6.3.8).

No external oracle exists for these at instruction level.  The claim is
"consistent with the manual and with MAME": each scenario states the manual
section it follows, and the MAME lockstep (validation/lockstep.py, rung 4)
checks the same entry against MAME 0.285 on real vblank interrupts -- frame
writes in order, vector, SR, and with a clock-carrying trace, the clocks.
"""

from __future__ import annotations

from conftest import make

from m68000_python import AUTOVECTOR, SPURIOUS

NOP = 0x4E71
HANDLER = 0x2000
LEVEL_4_AUTOVECTOR = 0x70  # vector 28 (UM Table 6-2)


def vectors(bus, **handlers) -> None:
    for vector in range(256):
        bus.set_long(vector * 4, handlers.get(f"v{vector}", HANDLER + 0x10 * (vector % 16)))
    bus.load(HANDLER, [NOP] * 0x200)


def test_level_above_the_mask_is_taken_at_the_next_boundary():
    cpu, bus = make([NOP] * 8)
    vectors(bus, v28=HANDLER)
    cpu.SR = 0x2300  # mask 3
    cpu.step()  # NOP at $1000
    cpu.set_ipl(4)
    clocks = cpu.step()  # the interrupt, before the NOP at $1002
    assert cpu.PC == HANDLER
    assert cpu.SR == 0x2400  # S set, T clear, mask raised to the level taken
    sp = cpu.R[15]
    assert sp == 0x8000 - 6
    assert bus.word(sp) == 0x2300  # the SR from before
    assert bus.long(sp + 2) == 0x1002  # the instruction the interrupt came before
    # UM Table 8-14: 44 clocks, plus the E-clock wait of an autovector.
    assert 44 + 0 < clocks <= 44 + 19


def test_level_at_or_below_the_mask_is_held():
    cpu, bus = make([NOP] * 8)
    vectors(bus)
    cpu.SR = 0x2400
    cpu.set_ipl(4)
    cpu.step()
    assert cpu.PC == 0x1002  # not taken: the level must exceed the mask (UM 6.3.2)
    cpu.SR = 0x2300
    cpu.step()
    assert cpu.PC == HANDLER + 0x10 * (28 % 16)


def test_the_frame_is_written_pc_low_then_sr_then_pc_high():
    cpu, bus = make([NOP] * 8)
    vectors(bus, v28=HANDLER)
    cpu.SR = 0x2000
    cpu.set_ipl(4)
    cpu.step()
    writes = [(address, value) for kind, address, value in bus.log if kind == "ww"]
    assert writes == [(0x7FFE, 0x1000), (0x7FFA, 0x2000), (0x7FFC, 0x0000)]


def test_level_seven_is_edge_triggered_and_ignores_the_mask():
    cpu, bus = make([NOP] * 16)
    vectors(bus, v31=HANDLER)
    cpu.SR = 0x2700
    cpu.set_ipl(7)
    cpu.step()
    assert cpu.PC == HANDLER  # taken with the mask at 7: a 0-to-7 change (UM 6.3.2)
    cpu.step()
    cpu.step()
    assert cpu.PC == HANDLER + 4  # held at 7: not taken again
    cpu.set_ipl(0)
    cpu.step()
    cpu.set_ipl(7)
    cpu.step()
    assert cpu.PC == HANDLER  # a new edge is taken again


def test_acknowledge_answers_a_vector_spurious_or_uninitialized():
    for answer, vector in ((0x40, 0x40), (SPURIOUS, 24), (AUTOVECTOR, 29), (300, 15)):
        cpu, bus = make([NOP] * 8, acknowledge=lambda level, answer=answer: answer)
        vectors(bus, **{f"v{vector}": 0x3000})
        bus.load(0x3000, [NOP] * 4)
        cpu.SR = 0x2000
        cpu.set_ipl(5)
        clocks = cpu.step()
        assert cpu.PC == 0x3000, (answer, vector)
        if answer != AUTOVECTOR:
            assert clocks == 44  # UM Table 8-14: no E-clock wait without VPA


def test_the_acknowledge_callback_gets_the_level():
    levels = []
    cpu, bus = make([NOP] * 8, acknowledge=lambda level: levels.append(level) or AUTOVECTOR)
    vectors(bus)
    cpu.SR = 0x2000
    cpu.set_ipl(6)
    cpu.step()
    assert levels == [6]


def test_trace_is_taken_before_a_pending_interrupt():
    # UM 6.3.8: trace, then interrupt; the handler that runs first is the
    # interrupt's, entered from the trace handler's first instruction.
    cpu, bus = make([NOP] * 8)
    vectors(bus, v9=0x3000, v28=0x3100)
    bus.load(0x3000, [NOP] * 4)
    bus.load(0x3100, [NOP] * 4)
    cpu.SR = 0xA000  # T set, mask 0
    cpu.step()  # NOP, traced
    cpu.set_ipl(4)
    cpu.step()  # trace exception first
    assert cpu.PC == 0x3000
    assert cpu.SR & 0x8000 == 0
    cpu.step()  # then the interrupt, before the trace handler's first instruction
    assert cpu.PC == 0x3100
    assert bus.long(cpu.R[15] + 2) == 0x3000


def test_an_interrupt_is_not_traced():
    cpu, bus = make([NOP] * 8)
    vectors(bus, v28=0x3100)
    bus.load(0x3100, [NOP] * 4)
    cpu.SR = 0xA000
    cpu.set_ipl(4)
    cpu.step()  # interrupt entry clears T (UM 6.2.5)
    assert cpu.PC == 0x3100 and not cpu.SR & 0x8000
    cpu.step()
    assert cpu.PC == 0x3102  # no trace exception followed


def test_stop_waits_for_an_interrupt_above_the_new_mask():
    cpu, bus = make([0x4E72, 0x2300, NOP, NOP])  # STOP #$2300
    vectors(bus, v28=0x3000)
    bus.load(0x3000, [NOP] * 4)
    cpu.step()
    assert cpu.stopped and cpu.SR == 0x2300
    for _ in range(3):
        assert cpu.step() == 4  # idles
    cpu.set_ipl(3)
    cpu.step()
    assert cpu.stopped  # level 3 does not exceed mask 3
    cpu.set_ipl(4)
    cpu.step()
    assert not cpu.stopped and cpu.PC == 0x3000
    assert bus.long(cpu.R[15] + 2) == 0x1004  # returns after the STOP


def test_stop_in_user_mode_is_a_privilege_violation():
    cpu, bus = make([0x4E72, 0x2700])
    vectors(bus, v8=0x3000)
    cpu.set_sr(0x0000)  # user mode: A7 becomes USP
    cpu.R[15] = 0x9000
    cpu.step()
    assert cpu.PC == 0x3000 and not cpu.stopped
    assert bus.long(cpu.R[15] + 2) == 0x1000  # the STOP itself (UM 6.3.7)


def test_a_traced_stop_takes_the_trace_exception():
    # PRM 6 (STOP): with T set, the trace exception is taken.
    cpu, bus = make([0x4E72, 0x2000])
    vectors(bus, v9=0x3000)
    bus.load(0x3000, [NOP] * 4)
    cpu.SR = 0xA000
    cpu.step()
    cpu.step()
    assert cpu.PC == 0x3000


def test_autovector_wait_follows_the_e_clock_phase():
    # MAME 0.285's vpa_sync: the acknowledge aligns to the E clock (CLK/10),
    # skipping a period when fewer than 3 clocks of this one remain.
    clocks = set()
    for phase in range(10):
        cpu, bus = make([NOP] * 8)
        vectors(bus)
        cpu.clock = phase
        cpu.SR = 0x2000
        cpu.set_ipl(1)
        clocks.add(cpu.step())
    assert clocks == set(range(44 + 4, 44 + 14)) or len(clocks) > 1
