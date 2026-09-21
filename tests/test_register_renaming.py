"""Every defined first word behaves as its register-renamed twin (a metamorphic test).

The gate corpus executes 38,019 of the 45,815 defined first words and the
rest of the suite brings that to 38,942 (docs/coverage.md).  Every word left
over differs from executed words of its own rule only in its register fields:
``ADD.W D5,D6`` where the corpus ran ``ADD.W D1,D2``.  The manuals decide what
such a word does without an oracle, because they define every instruction on
a generic Dn and An: PRM 2.2 gives each addressing mode for register number
n, 0 to 7, the same way, and PRM Section 4 each instruction in terms of those
modes.  The only register the manuals single out is A7, the stack pointer
(PRM 2.2.4-2.2.5: a byte through (A7)+ or -(A7) moves it by two; PRM 1.3:
exceptions and the stack instructions use it).

So renaming registers is a symmetry of the instruction set.  For each defined
word W this test builds its *canonical twin* C(W): the register numbers of
W's register fields renamed, in order of first appearance, to 0, 1, 2 ...,
with 7 never renamed (in either bank, so A7 keeps its role; D7 is merely
kept too).  The renaming is one permutation p of 0-6 applied to the D and the
A bank alike, so a field naming Dn and one naming An in the same word stay
consistent, and two fields naming the same register still do.  W runs from a
random state S and C(W) from p(S), the state with register n's value moved to
register p(n) in each bank; afterwards the two register files must be p of
each other, and SR, both stack pointers, the PC, the clocks, and every bus
access (address, value, order) must be identical.

Extension words are chosen so the renaming cannot reach them: every word
after the opcode is $F8xx, which as a brief extension word names A7.L as the
index (never renamed), and as a displacement, an address or an immediate is
the same value in both programs.  MOVEM is left out: its mask names
registers by bit, and all 140 MOVEM words are executed by the gate.

The field positions come from ``_dispatch.RULES``, the core's transcription
of PRM Section 8's encodings (checked word for word against MAME 0.285's
decoder, docs/worklog.md); which fields name registers is stated here, from
the manual.  Nothing here says what an instruction should do -- only that
the answer does not depend on which register holds the operand.  A word the
gate executes is evidence for all of its renamings.
"""

from __future__ import annotations

import random

from conftest import Bus

from m68000_python import M68000CPU
from m68000_python._dispatch import COMPILED, NAMES, RULES

PROGRAM = 0x010000
HANDLER = 0x002000
EXTENSION = [0xF804, 0xF808, 0xF80C, 0xF810, 0xF814]  # index A7.L, even, as any operand
UNDEFINED = ("illegal", "line_a", "line_f")


def _rule_of(opcode: int) -> int:
    for index, (mask, value, _name, check) in enumerate(COMPILED):
        if opcode & mask == value and check(opcode):
            return index
    raise AssertionError(f"{opcode:04X} is not defined")


def _positions(pattern: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for position, character in enumerate(pattern.replace(" ", "")):
        if character not in "01":
            found.setdefault(character, []).append(15 - position)
    return found


def register_fields(opcode: int) -> list[list[int]]:
    """The bit positions (high to low) of each field of ``opcode`` that names a register.

    From PRM Section 8's encodings: the 3-bit fields r, a, x, y name data or
    address registers; an effective-address field names one in modes 0-6
    (mode 7 uses the field to select an addressing form); MOVE's destination
    likewise; a shift's count field names Dx when bit 5 (i/r) is 1.
    """
    pattern = RULES[_rule_of(opcode)][0]
    positions = _positions(pattern)
    fields = [positions[letter] for letter in "raxy" if letter in positions]
    if "e" in positions and (opcode >> 3) & 7 != 7:
        fields.append(positions["e"][3:])  # the register half of mode:register
    if "R" in positions and "M" in positions and (opcode >> 6) & 7 != 7:
        fields.append(positions["R"])  # MOVE's destination register, modes 0-6
    if "c" in positions and len(positions["c"]) == 3 and "i" in positions and opcode & 0x20:
        fields.append(positions["c"])  # the shift count register, Dx
    return fields


def _get(opcode: int, bits: list[int]) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | ((opcode >> bit) & 1)
    return value


def _put(opcode: int, bits: list[int], value: int) -> int:
    for offset, bit in enumerate(reversed(bits)):
        opcode = (opcode & ~(1 << bit)) | (((value >> offset) & 1) << bit)
    return opcode


def canonical_twin(opcode: int) -> tuple[int, list[int]]:
    """C(W) and the permutation p (a list, p[n] for n in 0-7, p[7] = 7)."""
    fields = register_fields(opcode)
    mapping: dict[int, int] = {7: 7}
    free = iter(range(7))
    for bits in fields:
        number = _get(opcode, bits)
        if number not in mapping:
            mapping[number] = next(free)
    remaining = [n for n in range(7) if n not in mapping.values()]
    for number in range(7):
        if number not in mapping:
            mapping[number] = remaining.pop(0)
    twin = opcode
    for bits in fields:
        twin = _put(twin, bits, mapping[_get(opcode, bits)])
    return twin, [mapping[n] for n in range(8)]


class JournalBus(Bus):
    """The shared test bus, filled with random bytes, that can undo its writes."""

    def __init__(self, seed: int) -> None:
        super().__init__()
        self.memory = bytearray(random.Random(seed).randbytes(1 << 24))
        self.journal: dict[int, int] = {}

    def write_byte(self, address: int, value: int) -> None:
        self.journal.setdefault(address, self.memory[address])
        super().write_byte(address, value)

    def write_word(self, address: int, value: int) -> None:
        self.journal.setdefault(address, self.memory[address])
        self.journal.setdefault(address + 1, self.memory[address + 1])
        super().write_word(address, value)

    def rollback(self) -> None:
        for address, value in self.journal.items():
            self.memory[address] = value
        self.journal.clear()


def _state(rng: random.Random) -> dict:
    return {
        "d": [rng.getrandbits(32) for _ in range(8)],
        "a": [rng.randrange(0x100000, 0x700000, 2) for _ in range(7)],
        "ssp": 0x800000,
        "usp": 0x780000,
        "sr": rng.choice((0x2700, 0x0000)) | rng.randrange(32),
    }


def _run(cpu: M68000CPU, bus: JournalBus, opcode: int, state: dict, p: list[int]):
    """Run ``opcode`` from ``state`` renamed by ``p``; return what it did, renamed back."""
    bus.load(PROGRAM, [opcode, *EXTENSION, 0x4E71, 0x4E71])
    d, a = [0] * 8, [0] * 8
    for n in range(8):
        d[p[n]] = state["d"][n]
    for n in range(7):
        a[p[n]] = state["a"][n]
    cpu.R[0:8] = d
    cpu.R[8:15] = a[:7]
    cpu.SR = state["sr"]
    if cpu.SR & 0x2000:
        cpu.R[15], cpu._other_sp = state["ssp"], state["usp"]
    else:
        cpu.R[15], cpu._other_sp = state["usp"], state["ssp"]
    cpu.halted = cpu.stopped = cpu._trace_pending = False
    cpu.set_pc(PROGRAM)
    bus.log.clear()
    clocks = cpu.step()
    registers = ([cpu.R[p[n]] for n in range(8)], [cpu.R[8 + p[n]] for n in range(7)])
    outcome = (registers, cpu.SR, cpu.usp, cpu.ssp, cpu.PC, clocks, cpu.halted, cpu.stopped)
    log = list(bus.log)
    bus.rollback()
    return outcome, log


def test_the_canonical_twin_is_a_renaming():
    """C(W) is a word of the same rule, and C(C(W)) = C(W)."""
    for opcode in (0xD245, 0x3A3C, 0xC54B, 0xE66B, 0x2E8F):  # ADD, MOVE, EXG, LSR, MOVE (A7)
        twin, p = canonical_twin(opcode)
        assert NAMES[twin] == NAMES[opcode]
        assert canonical_twin(twin)[0] == twin
        assert sorted(p) == list(range(8)) and p[7] == 7
    assert canonical_twin(0xD245)[0] == 0xD041  # ADD.W D5,D1 -> ADD.W D1,D0 (field order r, e)


def test_every_defined_word_behaves_as_its_canonical_twin():
    """Register renaming is a symmetry of every defined word (PRM 2.2, Section 4).

    45,815 defined words; the ones that are their own canonical twin, and
    MOVEM, are skipped.  Two random states per word: one in supervisor mode,
    one drawn at random, so user-mode privilege paths are renamed too.
    """
    bus = JournalBus(seed=68000)
    for vector in range(256):
        bus.set_long(vector * 4, HANDLER)
    bus.load(HANDLER, [0x4E71] * 8)
    cpu = M68000CPU(bus.read_byte, bus.read_word, bus.write_byte, bus.write_word)
    rng = random.Random(1979)
    identity = list(range(8))
    compared = 0
    failures = []
    for opcode in range(0x10000):
        if NAMES[opcode] in UNDEFINED or NAMES[opcode] == "movem":
            continue
        twin, p = canonical_twin(opcode)
        if twin == opcode:
            continue
        for _ in range(2):
            state = _state(rng)
            ours = _run(cpu, bus, opcode, state, identity)
            theirs = _run(cpu, bus, twin, state, p)
            if ours != theirs:
                failures.append(f"{opcode:04X} ({NAMES[opcode]}) vs twin {twin:04X}")
        compared += 1
    assert not failures, f"{len(failures)} words differ from their twins; first: {failures[:5]}"
    assert compared > 30000
