"""Bit manipulation: BTST, BCHG, BCLR, BSET (PRM Table 3-6; UM Table 8-8).

The bit number comes from Dn (dynamic) or from the word after the opcode
(static).  On a data register the operation is on the whole long and the
number is taken mod 32; on memory it is on a byte, mod 8 (PRM 4, BTST).  Z
is set if the tested bit was 0; nothing else changes.  On a register the
changing forms cost 2 clocks more for bits 16-31 (UM Table 8-8 note), and
BCLR 2 more again (SST BCLR, T3).
"""

from m68000_python._core import Z
from m68000_python._ea import DN, EA_KIND, IMM

# The operations, by bits 7-6 of the opcode: test, change, clear, set.
TEST, CHANGE, CLEAR, SET = range(4)


class BitsMixin:
    """Private bit-manipulation implementation."""

    def _bit_operation(self, opcode: int, operation: int) -> None:
        if opcode & 0x0100:
            number = self.R[(opcode >> 9) & 7]
        else:
            self._commit_pc()
            number = self._extension() & 0xFF
        kind = EA_KIND[opcode & 0x3F]
        register = opcode & 7
        if kind == DN:
            number &= 31
            value = self.R[register]
            self._set_z(value, number)
            self._prefetch()
            if operation == TEST:
                self._cycles += 2
                return
            self._cycles += 4 if operation == CLEAR else 2
            if number >= 16:
                self._cycles += 2
            self.R[register] = self._apply_bit(value, number, operation)
            return
        number &= 7
        if kind == IMM:  # BTST Dn,#data: the operand is the byte after the opcode
            value = self._extension() & 0xFF
            self._set_z(value, number)
            self._prefetch()
            self._cycles += 2
            return
        address, value = self._ea_fetch(kind, register, 1)
        self._set_z(value, number)
        self._prefetch()
        if operation != TEST:
            self._write_byte(address, self._apply_bit(value, number, operation))

    def _set_z(self, value: int, number: int) -> None:
        if value >> number & 1:
            self.SR &= ~Z
        else:
            self.SR |= Z

    @staticmethod
    def _apply_bit(value: int, number: int, operation: int) -> int:
        bit = 1 << number
        if operation == CHANGE:
            return value ^ bit
        if operation == CLEAR:
            return value & ~bit
        return value | bit

    def _op_btst(self, opcode: int) -> None:
        """BTST -- Z <- NOT bit n of the destination (PRM 4-62; UM Table 8-8).

        Bus order, the 2 idle clocks of the register form, and the PC an address
        error stacks: SST BTST.
        """
        self._bit_operation(opcode, TEST)

    def _op_bchg(self, opcode: int) -> None:
        """BCHG -- Z <- NOT bit n, then invert bit n (PRM 4-28; UM Table 8-8).

        On a register 6 clocks, 8 for bits 16-31 (UM Table 8-8's note); bus
        order and the PC an address error stacks: SST BCHG.
        """
        self._bit_operation(opcode, CHANGE)

    def _op_bclr(self, opcode: int) -> None:
        """BCLR -- Z <- NOT bit n, then clear bit n (PRM 4-31; UM Table 8-8).

        On a register 8 clocks, 10 for bits 16-31, 2 more than BCHG and BSET at
        every bit; bus order and the PC an address error stacks: SST BCLR.
        """
        self._bit_operation(opcode, CLEAR)

    def _op_bset(self, opcode: int) -> None:
        """BSET -- Z <- NOT bit n, then set bit n (PRM 4-57; UM Table 8-8).

        On a register 6 clocks, 8 for bits 16-31; bus order and the PC an
        address error stacks: SST BSET.
        """
        self._bit_operation(opcode, SET)
