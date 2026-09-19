"""Binary-coded decimal: ABCD, SBCD, NBCD (PRM Table 3-8).

PRM Table 3-18 gives X and C (the decimal carry or borrow) and a sticky Z,
and calls N and V undefined.  They are not undefined on silicon, and the
rule below is the one flamewing's 68k-bcd-verifier checks exhaustively on a
Model 1 and a Model 3 Sega Genesis (T1; docs/undocumented-behavior.md): the
byte is first added or subtracted in binary, then corrected by 6 in each
nibble that produced a binary carry (borrow) or, for an add, a digit above 9;
N is bit 7 of the corrected byte, and V is set when the correction flipped
bit 7 -- from 0 to 1 for an add, from 1 to 0 for a subtract.  C and X are set
by a carry (borrow) out of either the binary step or the correction.

The three instructions' bus sequences are the microcode's (corpus, T3): the
register forms prefetch and then spend two internal clocks; the memory forms
read, prefetch, then write.
"""

from m68000_python._core import C, N, V, X, Z
from m68000_python._ea import DN, EA_KIND


def decimal_add(destination: int, source: int, extend: int) -> tuple[int, int]:
    """ABCD's result byte and X N Z V C bits (Z to be ANDed in: sticky)."""
    binary = destination + source + extend
    low_carry = (destination & 0xF) + (source & 0xF) + extend > 0xF
    uncorrected = binary & 0xFF
    correction = 0
    if low_carry or (uncorrected & 0xF) > 9:
        correction = 0x06
    if binary > 0xFF or uncorrected > 0x99:
        correction |= 0x60
    corrected = uncorrected + correction
    result = corrected & 0xFF
    flags = Z if result == 0 else 0
    if binary > 0xFF or corrected > 0xFF:
        flags |= X | C
    if result & 0x80:
        flags |= N
    if result & 0x80 and not uncorrected & 0x80:
        flags |= V  # the correction carried into bit 7 (T1, flamewing)
    return result, flags


def decimal_subtract(destination: int, source: int, extend: int) -> tuple[int, int]:
    """SBCD's (and NBCD's, with destination 0) result byte and X N Z V C bits."""
    binary = destination - source - extend
    low_borrow = (destination & 0xF) - (source & 0xF) - extend < 0
    uncorrected = binary & 0xFF
    correction = 0
    if low_borrow:
        correction = 0x06
    if binary < 0:
        correction |= 0x60
    corrected = uncorrected - correction
    result = corrected & 0xFF
    flags = Z if result == 0 else 0
    if binary < 0 or corrected < 0:
        flags |= X | C
    if result & 0x80:
        flags |= N
    if uncorrected & 0x80 and not result & 0x80:
        flags |= V  # the correction borrowed out of bit 7 (T1, flamewing)
    return result, flags


class BCDMixin:
    """Private BCD implementation."""

    def _set_bcd_flags(self, flags: int) -> None:
        # X N V C replaced; Z only ever cleared (PRM Table 3-18, sticky Z).
        sr = self.SR
        self.SR = (sr & 0xFF00) | (flags & (X | N | V | C)) | (sr & flags & Z)

    def _bcd_pair(self, opcode: int, operation) -> None:
        """The two forms shared by ABCD and SBCD: Dy,Dx and -(Ay),-(Ax)."""
        rx = (opcode >> 9) & 7
        ry = opcode & 7
        extend = (self.SR >> 4) & 1
        R = self.R
        if not opcode & 8:
            result, flags = operation(R[rx] & 0xFF, R[ry] & 0xFF, extend)
            self._set_bcd_flags(flags)
            self._prefetch()
            self._cycles += 2
            R[rx] = (R[rx] & 0xFFFFFF00) | result
            return
        self._cycles += 2
        self._commit_pc()
        source_address = (R[8 + ry] - self._step_size(ry, 1)) & 0xFFFFFFFF
        R[8 + ry] = source_address
        source = self._read_byte(source_address)
        destination_address = (R[8 + rx] - self._step_size(rx, 1)) & 0xFFFFFFFF
        R[8 + rx] = destination_address
        destination = self._read_byte(destination_address)
        result, flags = operation(destination, source, extend)
        self._set_bcd_flags(flags)
        self._prefetch()
        self._write_byte(destination_address, result)

    def _op_abcd(self, opcode: int) -> None:
        """ABCD -- destination <- destination + source + X, decimal (PRM 4-3; UM Table 8-11)."""
        self._bcd_pair(opcode, decimal_add)

    def _op_sbcd(self, opcode: int) -> None:
        """SBCD -- destination <- destination - source - X, decimal (PRM 4-176; UM Table 8-11)."""
        self._bcd_pair(opcode, decimal_subtract)

    def _op_nbcd(self, opcode: int) -> None:
        """NBCD -- destination <- 0 - destination - X, decimal (PRM 4-142; UM Table 8-6)."""
        kind = EA_KIND[opcode & 0x3F]
        register = opcode & 7
        extend = (self.SR >> 4) & 1
        if kind == DN:
            result, flags = decimal_subtract(0, self.R[register] & 0xFF, extend)
            self._set_bcd_flags(flags)
            self._prefetch()
            self._cycles += 2
            self.R[register] = (self.R[register] & 0xFFFFFF00) | result
            return
        address = self._ea_address(kind, register, 1)
        result, flags = decimal_subtract(0, self._read_byte(address), extend)
        self._set_bcd_flags(flags)
        self._prefetch()
        self._write_byte(address, result)
