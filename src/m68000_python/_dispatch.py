"""The opcode map: which handler each of the 65,536 first words runs.

``RULES`` below is the 68000 instruction set as PRM Section 8 prints it, one
line per encoding: a 16-character bit pattern, the handler, and the operand
constraint.  In a pattern ``0`` and ``1`` are fixed bits and letters are
fields: ``ss`` a size (00 byte, 01 word, 10 long; 11 is never that
instruction), ``eeeeee`` an effective address, anything else a field the
handler decodes.  The constraint names the addressing category of PRM Table
2-4 the EA field must fall in; an EA outside it makes the word something
else or illegal (UM 6.3.6, docs/undocumented-behavior.md).

:func:`build_table` walks all 65,536 words once per class, at first use, and
checks that no word matches two rules.  A word that matches none runs the
illegal-instruction exception, or the line 1010 / line 1111 emulator
exception when its top four bits say so (UM 6.3.6).  Dispatch is then one
list index and one call per instruction; handlers receive the opcode word
and never see the table.
"""

from collections.abc import Callable

from m68000_python._ea import (
    ALL,
    ALTERABLE,
    AN,
    CONTROL,
    DATA,
    DATA_ALTERABLE,
    EA_KIND,
    MEMORY_ALTERABLE,
    POSTINC,
    PREDEC,
)

Check = Callable[[int], bool]


def _ea_field(opcode: int) -> int | None:
    return EA_KIND[opcode & 0x3F]


def ea(category: frozenset) -> Check:
    """The EA in bits 5-0 must be in ``category``."""
    return lambda opcode: _ea_field(opcode) in category


def sized(category: frozenset) -> Check:
    """Size in bits 7-6 is not 11, the EA is in ``category``, and An is never a byte."""

    def check(opcode: int) -> bool:
        size_bits = (opcode >> 6) & 3
        kind = _ea_field(opcode)
        if size_bits == 3 or kind not in category:
            return False
        return not (size_bits == 0 and kind == AN)

    return check


def any_size_register(opcode: int) -> bool:
    """Register forms with a size field (ADDX, SUBX, CMPM, shifts): not 11."""
    return (opcode >> 6) & 3 != 3


def move(opcode: int) -> bool:
    """MOVE: source any mode (no An for a byte), destination data alterable (PRM 4, MOVE)."""
    source = _ea_field(opcode)
    destination = EA_KIND[((opcode >> 3) & 0x38) | ((opcode >> 9) & 7)]
    if source is None or destination not in DATA_ALTERABLE:
        return False
    return not ((opcode >> 12) == 1 and source == AN)


def movea(opcode: int) -> bool:
    """MOVEA: any source mode, word or long only (PRM 4, MOVEA)."""
    return _ea_field(opcode) is not None


def always(opcode: int) -> bool:
    return True


CONTROL_ALTERABLE = CONTROL & ALTERABLE

#: (bit pattern, handler, constraint) -- PRM Section 8, in opcode-map order.
RULES: tuple[tuple[str, str, Check], ...] = (
    # 0000: bit manipulation, MOVEP, immediate
    ("0000 0000 0011 1100", "ori_to_ccr", always),
    ("0000 0000 0111 1100", "ori_to_sr", always),
    ("0000 0000 ssee eeee", "ori", sized(DATA_ALTERABLE)),
    ("0000 0010 0011 1100", "andi_to_ccr", always),
    ("0000 0010 0111 1100", "andi_to_sr", always),
    ("0000 0010 ssee eeee", "andi", sized(DATA_ALTERABLE)),
    ("0000 0100 ssee eeee", "subi", sized(DATA_ALTERABLE)),
    ("0000 0110 ssee eeee", "addi", sized(DATA_ALTERABLE)),
    ("0000 1010 0011 1100", "eori_to_ccr", always),
    ("0000 1010 0111 1100", "eori_to_sr", always),
    ("0000 1010 ssee eeee", "eori", sized(DATA_ALTERABLE)),
    ("0000 1100 ssee eeee", "cmpi", sized(DATA_ALTERABLE)),
    ("0000 1000 00ee eeee", "btst", ea(DATA - {11})),
    ("0000 1000 01ee eeee", "bchg", ea(DATA_ALTERABLE)),
    ("0000 1000 10ee eeee", "bclr", ea(DATA_ALTERABLE)),
    ("0000 1000 11ee eeee", "bset", ea(DATA_ALTERABLE)),
    ("0000 rrr1 00ee eeee", "btst", ea(DATA)),
    ("0000 rrr1 01ee eeee", "bchg", ea(DATA_ALTERABLE)),
    ("0000 rrr1 10ee eeee", "bclr", ea(DATA_ALTERABLE)),
    ("0000 rrr1 11ee eeee", "bset", ea(DATA_ALTERABLE)),
    ("0000 rrr1 oo00 1aaa", "movep", always),
    # 0001, 0010, 0011: MOVE and MOVEA
    ("0001 RRRM MMee eeee", "move", move),
    ("0011 RRRM MMee eeee", "move", move),
    ("0010 RRRM MMee eeee", "move", move),
    ("0011 aaa0 01ee eeee", "movea", movea),
    ("0010 aaa0 01ee eeee", "movea", movea),
    # 0100: miscellaneous
    ("0100 0000 11ee eeee", "move_from_sr", ea(DATA_ALTERABLE)),
    ("0100 0000 ssee eeee", "negx", sized(DATA_ALTERABLE)),
    ("0100 0010 ssee eeee", "clr", sized(DATA_ALTERABLE)),
    ("0100 0100 11ee eeee", "move_to_ccr", ea(DATA)),
    ("0100 0100 ssee eeee", "neg", sized(DATA_ALTERABLE)),
    ("0100 0110 11ee eeee", "move_to_sr", ea(DATA)),
    ("0100 0110 ssee eeee", "not", sized(DATA_ALTERABLE)),
    ("0100 1000 00ee eeee", "nbcd", ea(DATA_ALTERABLE)),
    ("0100 1000 0100 0rrr", "swap", always),
    ("0100 1000 01ee eeee", "pea", ea(CONTROL)),
    ("0100 1000 1000 0rrr", "ext", always),
    ("0100 1000 1100 0rrr", "ext", always),
    ("0100 1000 1see eeee", "movem", ea(CONTROL_ALTERABLE | {PREDEC})),
    ("0100 1010 1111 1100", "illegal", always),
    ("0100 1010 11ee eeee", "tas", ea(DATA_ALTERABLE)),
    ("0100 1010 ssee eeee", "tst", sized(DATA_ALTERABLE)),
    ("0100 1100 1see eeee", "movem", ea(CONTROL | {POSTINC})),
    ("0100 1110 0100 vvvv", "trap", always),
    ("0100 1110 0101 0rrr", "link", always),
    ("0100 1110 0101 1rrr", "unlk", always),
    ("0100 1110 0110 drrr", "move_usp", always),
    ("0100 1110 0111 0000", "reset", always),
    ("0100 1110 0111 0001", "nop", always),
    ("0100 1110 0111 0010", "stop", always),
    ("0100 1110 0111 0011", "rte", always),
    ("0100 1110 0111 0101", "rts", always),
    ("0100 1110 0111 0110", "trapv", always),
    ("0100 1110 0111 0111", "rtr", always),
    ("0100 1110 10ee eeee", "jsr", ea(CONTROL)),
    ("0100 1110 11ee eeee", "jmp", ea(CONTROL)),
    ("0100 rrr1 10ee eeee", "chk", ea(DATA)),
    ("0100 rrr1 11ee eeee", "lea", ea(CONTROL)),
    # 0101: ADDQ, SUBQ, Scc, DBcc
    ("0101 qqq0 ssee eeee", "addq", sized(ALTERABLE)),
    ("0101 qqq1 ssee eeee", "subq", sized(ALTERABLE)),
    ("0101 cccc 1100 1rrr", "dbcc", always),
    ("0101 cccc 11ee eeee", "scc", ea(DATA_ALTERABLE)),
    # 0110: Bcc, BRA, BSR; 0111: MOVEQ
    ("0110 0000 dddd dddd", "bra", always),
    ("0110 0001 dddd dddd", "bsr", always),
    ("0110 cccc dddd dddd", "bcc", lambda opcode: ((opcode >> 8) & 0xF) >= 2),
    ("0111 rrr0 dddd dddd", "moveq", always),
    # 1000: OR, DIVU, DIVS, SBCD
    ("1000 rrr0 11ee eeee", "divu", ea(DATA)),
    ("1000 rrr1 11ee eeee", "divs", ea(DATA)),
    ("1000 yyy1 0000 mxxx", "sbcd", always),
    ("1000 rrr0 ssee eeee", "or", sized(DATA)),
    ("1000 rrr1 ssee eeee", "or", sized(MEMORY_ALTERABLE)),
    # 1001: SUB, SUBA, SUBX
    ("1001 aaas 11ee eeee", "suba", ea(ALL)),
    ("1001 yyy1 ss00 mxxx", "subx", any_size_register),
    ("1001 rrr0 ssee eeee", "sub", sized(ALL)),
    ("1001 rrr1 ssee eeee", "sub", sized(MEMORY_ALTERABLE)),
    # 1011: CMP, CMPA, CMPM, EOR
    ("1011 aaas 11ee eeee", "cmpa", ea(ALL)),
    ("1011 yyy1 ss00 1xxx", "cmpm", any_size_register),
    ("1011 rrr0 ssee eeee", "cmp", sized(ALL)),
    ("1011 rrr1 ssee eeee", "eor", sized(DATA_ALTERABLE)),
    # 1100: AND, MULU, MULS, ABCD, EXG
    ("1100 rrr0 11ee eeee", "mulu", ea(DATA)),
    ("1100 rrr1 11ee eeee", "muls", ea(DATA)),
    ("1100 yyy1 0000 mxxx", "abcd", always),
    ("1100 xxx1 0100 0yyy", "exg", always),
    ("1100 xxx1 0100 1yyy", "exg", always),
    ("1100 xxx1 1000 1yyy", "exg", always),
    ("1100 rrr0 ssee eeee", "and", sized(DATA)),
    ("1100 rrr1 ssee eeee", "and", sized(MEMORY_ALTERABLE)),
    # 1101: ADD, ADDA, ADDX
    ("1101 aaas 11ee eeee", "adda", ea(ALL)),
    ("1101 yyy1 ss00 mxxx", "addx", any_size_register),
    ("1101 rrr0 ssee eeee", "add", sized(ALL)),
    ("1101 rrr1 ssee eeee", "add", sized(MEMORY_ALTERABLE)),
    # 1110: shifts and rotates, memory (word, by one) then register forms
    ("1110 000d 11ee eeee", "asd_memory", ea(MEMORY_ALTERABLE)),
    ("1110 001d 11ee eeee", "lsd_memory", ea(MEMORY_ALTERABLE)),
    ("1110 010d 11ee eeee", "roxd_memory", ea(MEMORY_ALTERABLE)),
    ("1110 011d 11ee eeee", "rod_memory", ea(MEMORY_ALTERABLE)),
    ("1110 cccd ssi0 0rrr", "asd", any_size_register),
    ("1110 cccd ssi0 1rrr", "lsd", any_size_register),
    ("1110 cccd ssi1 0rrr", "roxd", any_size_register),
    ("1110 cccd ssi1 1rrr", "rod", any_size_register),
)


def _mask_and_value(pattern: str) -> tuple[int, int]:
    bits = pattern.replace(" ", "")
    assert len(bits) == 16, pattern
    mask = value = 0
    for bit in bits:
        mask <<= 1
        value <<= 1
        if bit in "01":
            mask |= 1
            value |= bit == "1"
    return mask, value


#: RULES with each pattern turned into (mask, value), in the same order.
COMPILED = tuple((*_mask_and_value(pattern), name, check) for pattern, name, check in RULES)


def decode(opcode: int) -> str:
    """The handler name for ``opcode``: a rule's, or illegal / line_a / line_f."""
    found = [
        name for mask, value, name, check in COMPILED if opcode & mask == value and check(opcode)
    ]
    if len(found) > 1:
        raise AssertionError(f"{opcode:04X} matches {found}")
    if found:
        return found[0]
    family = opcode >> 12
    if family == 0xA:
        return "line_a"
    if family == 0xF:
        return "line_f"
    return "illegal"


#: The handler name of every first word, computed once at import.
NAMES: tuple[str, ...] = tuple(decode(opcode) for opcode in range(0x10000))

Handler = Callable[..., None]


def build_table(cls: type) -> list[Handler]:
    """Return the 65,536 dispatch entries of ``cls``: ``table[opcode](cpu, opcode)``."""
    handlers = {name: getattr(cls, "_op_" + name) for name in set(NAMES)}
    return [handlers[name] for name in NAMES]
