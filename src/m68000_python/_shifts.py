"""Shifts and rotates: ASL/ASR, LSL/LSR, ROXL/ROXR, ROL/ROR (PRM Table 3-5).

Register forms shift Dn by 1-8 (an immediate count, 0 meaning 8) or by Dx
mod 64, at any size, in 6 + 2n clocks for a byte or word and 8 + 2n for a
long (UM Table 8-7): the queue is refilled first, then the shifter runs.
Memory forms shift a word by one: read, refill, write.

Flags (PRM Table 3-18): N and Z from the result; C is the last bit shifted
out; X takes C for the shifts and ROXL/ROXR and is untouched by ROL/ROR.  V
is cleared except by ASL, which sets it if the sign bit changed at any point
of the shift.  A count of 0 shifts nothing and clears C, except ROXL/ROXR,
which copy X into C (docs/undocumented-behavior.md, "Shift counts").
"""

from m68000_python._core import MASK, MSB, C, N, V, X, Z
from m68000_python._ea import EA_KIND

SIZE = (1, 2, 4, 0)
QUICK = (8, 1, 2, 3, 4, 5, 6, 7)


def _nz(result: int, size: int) -> int:
    flags = 0
    if result & MSB[size]:
        flags |= N
    if not result & MASK[size]:
        flags |= Z
    return flags


def shift(kind: str, left: bool, value: int, count: int, size: int, x: int) -> tuple[int, int]:
    """Shift ``value`` (``size`` bytes) ``count`` places; return (result, X N Z V C bits).

    The returned flags include X only where the operation defines it; the
    caller keeps the old X for ROL/ROR and for a count of 0.
    """
    bits = 8 * size
    mask = MASK[size]
    msb = MSB[size]
    if count == 0:
        carry = C if (kind == "rox" and x) else 0
        return value, _nz(value, size) | carry | (X if kind == "rox" and x else 0)
    if kind == "as" and left:
        result = value
        overflow = False
        carry = 0
        for _ in range(count):
            carry = 1 if result & msb else 0
            shifted = (result << 1) & mask
            if (shifted ^ result) & msb:
                overflow = True  # the sign bit changed at some point (PRM 4-22)
            result = shifted
        flags = _nz(result, size) | (V if overflow else 0)
        return result, flags | ((X | C) if carry else 0)
    if kind == "as":
        signed = value - (1 << bits) if value & msb else value
        if count >= bits:
            result = mask if signed < 0 else 0
            carry = 1 if signed < 0 else 0
        else:
            carry = (signed >> (count - 1)) & 1
            result = (signed >> count) & mask
        return result, _nz(result, size) | ((X | C) if carry else 0)
    if kind == "ls":
        if left:
            carry = (value >> (bits - count)) & 1 if count <= bits else 0
            result = (value << count) & mask
        else:
            carry = (value >> (count - 1)) & 1 if count <= bits else 0
            result = value >> count if count < bits else 0
        return result, _nz(result, size) | ((X | C) if carry else 0)
    if kind == "ro":
        steps = count % bits
        if left:
            result = ((value << steps) | (value >> (bits - steps))) & mask
            carry = result & 1
        else:
            result = ((value >> steps) | (value << (bits - steps))) & mask
            carry = 1 if result & msb else 0
        return result, _nz(result, size) | (C if carry else 0)
    # rox: rotate through X, a (bits + 1)-bit rotation
    steps = count % (bits + 1)
    wide = (x << bits) | value
    if left:
        wide = ((wide << steps) | (wide >> (bits + 1 - steps))) & ((mask << 1) | 1)
    else:
        wide = ((wide >> steps) | (wide << (bits + 1 - steps))) & ((mask << 1) | 1)
    extend = (wide >> bits) & 1
    result = wide & mask
    return result, _nz(result, size) | ((X | C) if extend else 0)


class ShiftsMixin:
    """Private shift and rotate implementation."""

    def _shift_register(self, opcode: int, kind: str) -> None:
        size = SIZE[(opcode >> 6) & 3]
        if opcode & 0x20:
            count = self.R[(opcode >> 9) & 7] & 63
        else:
            count = QUICK[(opcode >> 9) & 7]
        register = opcode & 7
        x = (self.SR >> 4) & 1
        result, flags = shift(
            kind, bool(opcode & 0x0100), self.R[register] & MASK[size], count, size, x
        )
        self._set_shift_flags(kind, flags, count)
        self._prefetch()
        self._cycles += (4 if size == 4 else 2) + 2 * count
        self._write_register(register, size, result)

    def _set_shift_flags(self, kind: str, flags: int, count: int) -> None:
        keep = 0xFF00
        if kind == "ro" or (count == 0 and kind != "rox"):
            keep |= X  # ROL/ROR never touch X; a zero count leaves X alone
        self.SR = (self.SR & keep) | (flags & ~keep & 0xFF)

    def _shift_memory(self, opcode: int, kind: str) -> None:
        address, value = self._ea_fetch(EA_KIND[opcode & 0x3F], opcode & 7, 2)
        x = (self.SR >> 4) & 1
        result, flags = shift(kind, bool(opcode & 0x0100), value, 1, 2, x)
        self._set_shift_flags(kind, flags, 1)
        self._prefetch()
        self._write_word(address, result)

    def _op_asd(self, opcode: int) -> None:
        """ASd -- arithmetic shift Dn left or right (PRM 4-22; UM Table 8-7)."""
        self._shift_register(opcode, "as")

    def _op_lsd(self, opcode: int) -> None:
        """LSd -- logical shift Dn left or right (PRM 4-113; UM Table 8-7)."""
        self._shift_register(opcode, "ls")

    def _op_roxd(self, opcode: int) -> None:
        """ROXd -- rotate Dn through X, left or right (PRM 4-163; UM Table 8-7)."""
        self._shift_register(opcode, "rox")

    def _op_rod(self, opcode: int) -> None:
        """ROd -- rotate Dn left or right, X untouched (PRM 4-160; UM Table 8-7)."""
        self._shift_register(opcode, "ro")

    def _op_asd_memory(self, opcode: int) -> None:
        """ASd -- arithmetic shift a memory word by one (PRM 4-22; UM Table 8-7).

        Read, refill, write, and the PC an address error stacks: SST ASL.w, ASR.w.
        """
        self._shift_memory(opcode, "as")

    def _op_lsd_memory(self, opcode: int) -> None:
        """LSd -- logical shift a memory word by one (PRM 4-113; UM Table 8-7).

        Read, refill, write, and the PC an address error stacks: SST LSL.w, LSR.w.
        """
        self._shift_memory(opcode, "ls")

    def _op_roxd_memory(self, opcode: int) -> None:
        """ROXd -- rotate a memory word through X by one (PRM 4-163; UM Table 8-7).

        Read, refill, write, and the PC an address error stacks: SST ROXL.w, ROXR.w.
        """
        self._shift_memory(opcode, "rox")

    def _op_rod_memory(self, opcode: int) -> None:
        """ROd -- rotate a memory word by one (PRM 4-160; UM Table 8-7).

        Read, refill, write, and the PC an address error stacks: SST ROL.w, ROR.w.
        """
        self._shift_memory(opcode, "ro")
