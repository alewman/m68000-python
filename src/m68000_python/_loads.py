"""Data movement: MOVE, MOVEA, MOVEQ, MOVEM, MOVEP, LEA, PEA, LINK, UNLK, EXG, SWAP, EXT.

PRM Table 3-2.  MOVE's destination has its own sequence, not the source's:
no extension word is taken from the queue before the source operand is read,
``-(An)`` costs no internal clocks and is written after the closing prefetch,
and ``(xxx).L`` writes between its two extension-word refills (UM Tables 8-2
and 8-3; the order is the corpus's, T3).
"""

from m68000_python._core import MASK, MSB
from m68000_python._ea import (
    ABSL,
    ABSW,
    AN,
    DISP,
    DN,
    EA_KIND,
    IMM,
    IND,
    INDEX,
    PCDISP,
    PCINDEX,
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


class MultipleMixin:
    """Private MOVEM, MOVEP, LEA, PEA, LINK, UNLK, EXG, SWAP, EXT implementation."""

    # -- MOVEM (PRM 4-128; UM Table 8-10) ---------------------------------------

    def _op_movem(self, opcode: int) -> None:
        """MOVEM -- move a list of registers to or from memory (PRM 4-128; UM Table 8-10).

        The mask word follows the opcode; bit 0 is D0 and bit 15 A7, except
        for -(An), where the order is reversed so that the registers still
        land in memory D0 lowest (PRM 4, MOVEM).  Memory-to-register reads
        one word past the last register (the extra read of UM Table 8-10's
        ``3+n``; corpus, T3); word loads are sign-extended into the whole
        register.  With -(An) the 68000 stores An's initial value if An is
        in the list; with (An)+ the loaded value is replaced by the final
        address (PRM 4, MOVEM).
        """
        size = 4 if opcode & 0x40 else 2
        kind = EA_KIND[opcode & 0x3F]
        register = opcode & 7
        mask = self._extension()
        R = self.R
        if opcode & 0x0400:
            program = kind in (PCDISP, PCINDEX)
            address = R[8 + register] if kind == POSTINC else self._ea_address(kind, register, 2)
            self._commit_pc()
            read = self._read_program_word if program else self._read_word
            for index in range(16):
                if mask & (1 << index):
                    if size == 4:
                        high = read(address)
                        R[index] = (high << 16) | read(address + 2)
                    else:
                        R[index] = sign_extend_16(read(address)) & 0xFFFFFFFF
                    address = (address + size) & 0xFFFFFFFF
            read(address)  # one word past the last register (T3)
            if kind == POSTINC:
                R[8 + register] = address
            self._prefetch()
            return
        if kind == PREDEC:
            address = R[8 + register]
            self._commit_pc()
            for bit in range(16):
                if mask & (1 << bit):
                    value = R[15 - bit]
                    address = (address - size) & 0xFFFFFFFF
                    if size == 4:
                        self._write_long_low_first(address, value)
                    else:
                        self._write_word(address, value)
            R[8 + register] = address
            self._prefetch()
            return
        address = self._ea_address(kind, register, 2)
        self._commit_pc()
        for index in range(16):
            if mask & (1 << index):
                if size == 4:
                    self._write_long(address, R[index])
                else:
                    self._write_word(address, R[index])
                address = (address + size) & 0xFFFFFFFF
        self._prefetch()

    # -- MOVEP (PRM 4-133; UM Table 8-13) --------------------------------------

    def _op_movep(self, opcode: int) -> None:
        """MOVEP -- move Dn to or from alternate bytes at (d16,Ay) (PRM 4-133).

        Byte accesses, high-order byte first, so never an address error at an
        odd address (docs/undocumented-behavior.md, "Odd addresses").
        """
        dn = (opcode >> 9) & 7
        address = (self.R[8 + (opcode & 7)] + sign_extend_16(self._extension())) & 0xFFFFFFFF
        count = 4 if opcode & 0x40 else 2
        if opcode & 0x80:
            value = self.R[dn]
            for shift in range(8 * (count - 1), -1, -8):
                self._write_byte(address, value >> shift)
                address += 2
        else:
            value = 0
            for _ in range(count):
                value = (value << 8) | self._read_byte(address)
                address += 2
            self._write_register(dn, count, value)
        self._prefetch()

    # -- effective addresses as values (PRM 4-110, 4-159) ----------------------

    def _op_lea(self, opcode: int) -> None:
        """LEA -- An <- effective address (PRM 4-110; UM Table 8-10)."""
        kind = EA_KIND[opcode & 0x3F]
        address = self._control_ea(kind, opcode & 7)
        self.R[8 + ((opcode >> 9) & 7)] = address
        if kind in (INDEX, PCINDEX):
            self._cycles += 2
        self._prefetch()

    def _control_ea(self, kind: int, register: int) -> int:
        """A control-mode address, taking the extension words from the queue."""
        if kind == IND:
            return self.R[8 + register]
        return self._ea_address(kind, register, 4)

    def _op_pea(self, opcode: int) -> None:
        """PEA -- push the effective address (PRM 4-159; UM Table 8-10)."""
        kind = EA_KIND[opcode & 0x3F]
        address = self._control_ea(kind, opcode & 7)
        if kind in (INDEX, PCINDEX):
            self._cycles += 2
        if kind in (ABSW, ABSL):
            self._push_long(address)
            self._prefetch()
            return
        self._prefetch_before_write()
        self._push_long(address)
        self._opcode = self.ir

    # -- stack frames (PRM 4-111, 4-194) -----------------------------------------

    def _op_link(self, opcode: int) -> None:
        """LINK -- push An, An <- SP, SP <- SP + d16 (PRM 4-111; UM Table 8-12: 16 clocks)."""
        an = 8 + (opcode & 7)
        displacement = sign_extend_16(self._extension())
        value = self.R[an]  # LINK A7 pushes A7 as it was before the push (T3)
        sp = (self.R[15] - 4) & 0xFFFFFFFF
        self.R[an] = sp
        self._write_long(sp, value)
        self.R[15] = (sp + displacement) & 0xFFFFFFFF
        self._prefetch()

    def _op_unlk(self, opcode: int) -> None:
        """UNLK -- SP <- An, An <- (SP)+ (PRM 4-194; UM Table 8-12: 12 clocks)."""
        an = 8 + (opcode & 7)
        address = self.R[an]
        self._commit_pc()
        value = self._read_long(address)  # SP moves only once both words are in (T3)
        self.R[15] = (address + 4) & 0xFFFFFFFF
        self.R[an] = value
        self._prefetch()

    # -- register shuffles (PRM 4-105, 4-187, 4-106) ------------------------------

    def _op_exg(self, opcode: int) -> None:
        """EXG -- exchange two registers (PRM 4-105; UM Table 8-12: 6 clocks)."""
        mode = (opcode >> 3) & 0x1F
        rx = (opcode >> 9) & 7
        ry = opcode & 7
        if mode == 0x08:
            x, y = rx, ry
        elif mode == 0x09:
            x, y = 8 + rx, 8 + ry
        else:
            x, y = rx, 8 + ry
        R = self.R
        R[x], R[y] = R[y], R[x]
        self._prefetch()
        self._cycles += 2

    def _op_swap(self, opcode: int) -> None:
        """SWAP -- exchange the halves of Dn; N Z of the long, V C cleared (PRM 4-187)."""
        register = opcode & 7
        value = self.R[register]
        value = ((value << 16) | (value >> 16)) & 0xFFFFFFFF
        self._flags_logic(value, 4)
        self.R[register] = value
        self._prefetch()

    def _op_ext(self, opcode: int) -> None:
        """EXT -- sign-extend byte to word (EXT.W) or word to long (EXT.L) (PRM 4-106)."""
        register = opcode & 7
        if opcode & 0x40:
            value = sign_extend_16(self.R[register]) & 0xFFFFFFFF
            self._flags_logic(value, 4)
            self.R[register] = value
        else:
            value = sign_extend_8(self.R[register]) & 0xFFFF
            self._flags_logic(value, 2)
            self._write_register(register, 2, value)
        self._prefetch()
