"""Data movement: MOVE, MOVEA, MOVEQ, MOVEM, MOVEP, LEA, PEA, LINK, UNLK, EXG, SWAP, EXT.

PRM Table 3-2.  MOVE's destination has its own sequence, not the source's:
no extension word is taken from the queue before the source operand is read,
``-(An)`` costs no internal clocks and is written after the closing prefetch,
and ``(xxx).L`` writes between its two extension-word refills (UM Tables 8-2
and 8-3; the order is the corpus's, T3).
"""

from m68000_python._core import MASK, MSB
from m68000_python._ea import (
    ABSW,
    AN,
    DISP,
    DN,
    EA_KIND,
    IMM,
    IND,
    INDEX,
    POSTINC,
    PREDEC,
    sign_extend_8,
    sign_extend_16,
)

#: MOVE's size field, bits 13-12 (PRM 4, MOVE): 01 byte, 11 word, 10 long.
MOVE_SIZE = {1: 1, 3: 2, 2: 4}


class LoadsMixin:
    """Private data-movement implementation."""

    def _op_move(self, opcode: int) -> None:
        """MOVE -- destination <- source; N Z set, V C cleared (PRM 4-116; UM Tables 8-2, 8-3)."""
        size = MOVE_SIZE[opcode >> 12]
        source = EA_KIND[opcode & 0x3F]
        value = self._ea_read(source, opcode & 7, size)
        kind = EA_KIND[(opcode >> 3) & 0x38 | (opcode >> 9) & 7]
        register = (opcode >> 9) & 7
        if size == 4:
            self._move_long_to(kind, register, value, source in (DN, AN, IMM))
            return
        R = self.R
        if kind == DN:
            self._flags_logic(value, size)
            self._write_register(register, size, value)
            self._prefetch()
            return
        if kind == IND or kind == POSTINC:
            address = R[8 + register]
            self._flags_logic(value, size)
            self._commit_pc()
            self._write(size, address, value)
            if kind == POSTINC:  # after the write: a faulting write leaves An alone (T3)
                R[8 + register] = (address + self._step_size(register, size)) & 0xFFFFFFFF
            self._prefetch()
            return
        if kind == PREDEC:
            address = (R[8 + register] - self._step_size(register, size)) & 0xFFFFFFFF
            R[8 + register] = address
            self._flags_logic(value, size)
            self._prefetch()
            self._write(size, address, value)
            return
        if kind == DISP:
            self._commit_pc()
            address = (R[8 + register] + sign_extend_16(self._extension())) & 0xFFFFFFFF
        elif kind == INDEX:
            self._cycles += 2
            self._commit_pc()
            address = self._index(R[8 + register])
        elif kind == ABSW:
            self._commit_pc()
            address = sign_extend_16(self._extension()) & 0xFFFFFFFF
        elif source in (DN, AN, IMM):
            # (xxx).L from a register or immediate: both refills, then the write (T3).
            high = self._extension()
            self._commit_pc()
            address = ((high << 16) | self._extension()) & 0xFFFFFFFF
        else:
            # (xxx).L from memory: the write comes between the two refills (T3).
            self._commit_pc()
            high = self._extension()
            address = ((high << 16) | self.irc) & 0xFFFFFFFF
            self._flags_logic(value, size)
            self._write(size, address, value)
            self._extension()
            self._prefetch()
            return
        self._flags_logic(value, size)
        self._write(size, address, value)
        self._prefetch()

    def _move_long_to(self, kind: int, register: int, value: int, from_register: bool) -> None:
        """The destination half of MOVE.L.

        The long is written as two words and its flags are set as two
        halves, low word then high word (_flags.py), interleaved with the
        writes in an order that depends on where the value came from: the
        stacked SR of an address error on the first write shows it (T3).
        """
        R = self.R
        high, low = value >> 16, value & 0xFFFF
        if kind == DN:
            self._flags_logic(value, 4)
            R[register] = value
            self._prefetch()
            return
        if kind == IND or kind == POSTINC:
            address = R[8 + register]
            self._commit_pc()
            if from_register:
                self._write_word(address, high)  # flags not yet touched
                self._flags_low_word(value)
            else:
                self._flags_low_word(value)
                self._write_word(address, high)
            self._write_word(address + 2, low)
            if kind == POSTINC:
                R[8 + register] = (address + 4) & 0xFFFFFFFF
            self._flags_high_word(value)
            self._prefetch()
            return
        if kind == PREDEC:
            address = (R[8 + register] - 4) & 0xFFFFFFFF
            self._flags_logic(value, 4)
            self._prefetch_before_write()
            self._write_word(address + 2, low)  # low word first, An not yet moved
            self._opcode = self.ir
            R[8 + register] = address
            self._write_word(address, high)
            return
        if kind == DISP or kind == INDEX:
            if kind == INDEX:
                self._cycles += 2
            self._commit_pc()
            if kind == DISP:
                address = (R[8 + register] + sign_extend_16(self._extension())) & 0xFFFFFFFF
            else:
                address = self._index(R[8 + register])
            if from_register:
                self._flags_high_word(value)  # the high word's half first
                self._write_word(address, high)
                self._flags_low_word(value)
            else:
                self._flags_low_word(value)
                self._flags_high_word(value)
                self._write_word(address, high)
            self._write_word(address + 2, low)
            self._flags_high_word(value)
            self._prefetch()
            return
        if kind == ABSW:
            self._commit_pc()
            address = sign_extend_16(self._extension()) & 0xFFFFFFFF
        elif from_register:
            high_address = self._extension()
            self._commit_pc()
            address = ((high_address << 16) | self._extension()) & 0xFFFFFFFF
        else:
            # (xxx).L from memory: the writes come between the two refills (T3).
            self._commit_pc()
            high_address = self._extension()
            address = ((high_address << 16) | self.irc) & 0xFFFFFFFF
            self._flags_low_word(value)
            self._write_word(address, high)
            self._flags_high_word(value)
            self._write_word(address + 2, low)
            self._extension()
            self._prefetch()
            return
        self._flags_logic(value, 4)
        self._write_word(address, high)
        self._write_word(address + 2, low)
        self._prefetch()

    def _op_movea(self, opcode: int) -> None:
        """MOVEA -- An <- source, a word sign-extended; flags unchanged (PRM 4-119)."""
        size = 2 if opcode >> 12 == 3 else 4
        value = self._ea_read(EA_KIND[opcode & 0x3F], opcode & 7, size)
        if size == 2:
            value = sign_extend_16(value) & 0xFFFFFFFF
        self.R[8 + ((opcode >> 9) & 7)] = value
        self._prefetch()

    def _op_moveq(self, opcode: int) -> None:
        """MOVEQ -- Dn <- sign-extended 8-bit data; N Z set, V C cleared (PRM 4-134; 4 clocks)."""
        value = sign_extend_8(opcode) & 0xFFFFFFFF
        self._flags_logic(value, 4)
        self.R[(opcode >> 9) & 7] = value
        self._prefetch()


__all__ = ["AN", "MASK", "MSB"]
