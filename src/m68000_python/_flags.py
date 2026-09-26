"""Condition codes: the flag rules of PRM Table 3-18 and the tests of Table 3-19.

Every rule is written once here and used by every family that shares it:
``_flags_logic`` for the moves, logic and tests (N, Z from the result, V and C
cleared, X untouched), ``_flags_add``/``_flags_sub`` for binary arithmetic,
``_flags_cmp`` for the compares (X untouched), and the ``x`` variants for
ADDX/SUBX/NEGX, whose Z is sticky: cleared by a nonzero result, otherwise
unchanged (PRM Table 3-18).
"""

from m68000_python._core import MASK, MSB, C, N, V, X, Z

CONDITION_NAMES = (
    "T", "F", "HI", "LS", "CC", "CS", "NE", "EQ",
    "VC", "VS", "PL", "MI", "GE", "LT", "GT", "LE",
)  # fmt: skip


def _test(cc: int, ccr: int) -> bool:
    """PRM Table 3-19, evaluated for one condition and one N/Z/V/C value."""
    n, z, v, c = bool(ccr & N), bool(ccr & Z), bool(ccr & V), bool(ccr & C)
    return (
        True,  # T
        False,  # F
        not c and not z,  # HI
        c or z,  # LS
        not c,  # CC (HS)
        c,  # CS (LO)
        not z,  # NE
        z,  # EQ
        not v,  # VC
        v,  # VS
        not n,  # PL
        n,  # MI
        n == v,  # GE
        n != v,  # LT
        not z and n == v,  # GT
        z or n != v,  # LE
    )[cc]


#: CONDITION[cc][SR & 0xF] is the truth of condition ``cc``; built at import.
CONDITION: tuple[tuple[bool, ...], ...] = tuple(
    tuple(_test(cc, ccr) for ccr in range(16)) for cc in range(16)
)


class FlagsMixin:
    """Private condition-code helpers."""

    def _flags_logic(self, result: int, size: int) -> None:
        """N and Z from ``result``; V and C cleared; X unchanged."""
        ccr = self.SR & (0xFF00 | X)
        if result & MSB[size]:
            ccr |= N
        if not result & MASK[size]:
            ccr |= Z
        self.SR = ccr

    # A long result leaves the ALU as two words, and the microcode updates the
    # flags once per word: N Z V C from the low word, then N from the high
    # word with Z kept only if the high word is zero too.  Only an address
    # error between the two can see the halfway state; the stacked SR does
    # (SST MOVE.l, T3).  _flags_logic is the two applied in order.

    def _flags_low_word(self, value: int) -> None:
        """N Z from the low word; V C cleared (the first half of a long's flags)."""
        ccr = self.SR & (0xFF00 | X)
        if value & 0x8000:
            ccr |= N
        if not value & 0xFFFF:
            ccr |= Z
        self.SR = ccr

    def _flags_high_word(self, value: int) -> None:
        """N from bit 31; Z kept only if the high word is also zero (the second half)."""
        ccr = self.SR & ~N
        if value & 0x80000000:
            ccr |= N
        if value & 0xFFFF0000:
            ccr &= ~Z
        self.SR = ccr

    def _flags_add(self, destination: int, source: int, result: int, size: int) -> None:
        """X N Z V C of ``destination + source`` (``result`` unmasked)."""
        msb = MSB[size]
        ccr = self.SR & 0xFF00
        if result & msb:
            ccr |= N
        if not result & MASK[size]:
            ccr |= Z
        if (source ^ result) & (destination ^ result) & msb:
            ccr |= V
        if result > MASK[size]:
            ccr |= X | C
        self.SR = ccr

    def _flags_sub(self, destination: int, source: int, result: int, size: int) -> None:
        """X N Z V C of ``destination - source`` (``result`` unmasked, may be negative)."""
        msb = MSB[size]
        ccr = self.SR & 0xFF00
        if result & msb:
            ccr |= N
        if not result & MASK[size]:
            ccr |= Z
        if (source ^ destination) & (result ^ destination) & msb:
            ccr |= V
        if result < 0:
            ccr |= X | C
        self.SR = ccr

    def _flags_cmp(self, destination: int, source: int, result: int, size: int) -> None:
        """N Z V C of ``destination - source``; X unchanged (PRM Table 3-18, CMP)."""
        msb = MSB[size]
        ccr = self.SR & (0xFF00 | X)
        if result & msb:
            ccr |= N
        if not result & MASK[size]:
            ccr |= Z
        if (source ^ destination) & (result ^ destination) & msb:
            ccr |= V
        if result < 0:
            ccr |= C
        self.SR = ccr

    def _flags_addx(self, destination: int, source: int, result: int, size: int) -> None:
        """ADDX: as ADD, but Z is only ever cleared (PRM Table 3-18)."""
        msb = MSB[size]
        ccr = self.SR & (0xFF00 | Z)
        if result & msb:
            ccr |= N
        if result & MASK[size]:
            ccr &= ~Z
        if (source ^ result) & (destination ^ result) & msb:
            ccr |= V
        if result > MASK[size]:
            ccr |= X | C
        self.SR = ccr

    def _flags_subx(self, destination: int, source: int, result: int, size: int) -> None:
        """SUBX and NEGX: as SUB, but Z is only ever cleared (PRM Table 3-18)."""
        msb = MSB[size]
        ccr = self.SR & (0xFF00 | Z)
        if result & msb:
            ccr |= N
        if result & MASK[size]:
            ccr &= ~Z
        if (source ^ destination) & (result ^ destination) & msb:
            ccr |= V
        if result < 0:
            ccr |= X | C
        self.SR = ccr
