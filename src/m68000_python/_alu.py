"""Integer arithmetic and logic (PRM Tables 3-3 and 3-4).

ADD, SUB, AND, OR, EOR, CMP and their A/I/Q/X/M forms; NEG, NEGX, NOT, CLR,
TST, TAS; MULU, MULS, DIVU, DIVS.  Flag rules are _flags.py's.  The bus
sequences are three shapes, all the microcode's (corpus, T3):

* **to a data register**: the operand is read (EA timing, UM Table 8-1),
  the result written, the queue refilled; a long result then spends 2
  internal clocks after a memory operand and 4 after a register or
  immediate one (UM Table 8-4 note **);
* **to memory** (read-modify-write): the operand is read, the queue
  refilled, the result written -- a long one low word first;
* **compares** read and refill only.

Only the operand read can fault in a read-modify-write: the write goes to
the address the read already proved even.
"""

from m68000_python._core import MASK, MSB, C, N, V, X, Z
from m68000_python._ea import AN, DN, EA_KIND, IMM, sign_extend_16

#: Bits 7-6 of the common size field (PRM Section 8): 00 byte, 01 word, 10 long.
SIZE = (1, 2, 4, 0)
#: ADDQ/SUBQ data: 1-8, with 0 meaning 8 (PRM 4, ADDQ).
QUICK = (8, 1, 2, 3, 4, 5, 6, 7)


def multiply_unsigned_clocks(source: int) -> int:
    """MULU: 38 + 2n, n the number of 1 bits in the source word (UM Table 8-4, note)."""
    return 38 + 2 * bin(source & 0xFFFF).count("1")


def multiply_signed_clocks(source: int) -> int:
    """MULS: 38 + 2n, n the 01/10 transitions of the source with a 0 appended (UM Table 8-4)."""
    pattern = (source & 0xFFFF) << 1
    return 38 + 2 * bin((pattern ^ (pattern >> 1)) & 0xFFFF).count("1")


def divide_unsigned_clocks(dividend: int, divisor: int) -> int:
    """DIVU's internal clocks, from the microcode's shift-and-subtract loop.

    The manual gives only a maximum (UM Table 8-4).  The loop: overflow is
    detected first; otherwise 15 steps each shift the dividend left, and a
    step whose shifted-out bit was 0 costs 2 more clocks, less 1 if the
    trial subtraction succeeded.  Jorge Cwik's analysis (2005, carried in
    WinUAE, T2) states the same count; the corpus checks it (T3).
    """
    if dividend >> 16 >= divisor:
        return 10
    half_clocks = 38
    shifted_divisor = divisor << 16
    for _ in range(15):
        carry = dividend & 0x80000000
        dividend = (dividend << 1) & 0xFFFFFFFF
        if carry:
            dividend = (dividend - shifted_divisor) & 0xFFFFFFFF
        else:
            half_clocks += 2
            if dividend >= shifted_divisor:
                dividend -= shifted_divisor
                half_clocks -= 1
    return half_clocks * 2


def divide_signed_clocks(dividend: int, divisor: int) -> int:
    """DIVS's internal clocks: sign handling, then one step per quotient bit.

    ``dividend`` and ``divisor`` are signed.  Absolute overflow (|dividend|
    >> 16 >= |divisor|) is found early; otherwise the unsigned loop runs on
    the magnitudes and each of the 15 high quotient bits that is 0 costs 2
    clocks (Cwik 2005, T2; checked against the corpus, T3).
    """
    half_clocks = 6
    if dividend < 0:
        half_clocks += 1
    if abs(dividend) >> 16 >= abs(divisor):
        return (half_clocks + 2) * 2
    quotient = abs(dividend) // abs(divisor)
    half_clocks += 55
    if divisor >= 0:
        half_clocks += -1 if dividend >= 0 else 1
    for bit in range(15):
        if not quotient & (0x8000 >> bit):
            half_clocks += 1
    return half_clocks * 2


class ALUMixin:
    """Private arithmetic and logic implementation."""

    # -- the operations: result from destination and source, flags set --------

    def _add(self, destination: int, source: int, size: int) -> int:
        result = destination + source
        self._flags_add(destination, source, result, size)
        return result & MASK[size]

    def _sub(self, destination: int, source: int, size: int) -> int:
        result = destination - source
        self._flags_sub(destination, source, result, size)
        return result & MASK[size]

    def _and(self, destination: int, source: int, size: int) -> int:
        result = destination & source
        self._flags_logic(result, size)
        return result

    def _or(self, destination: int, source: int, size: int) -> int:
        result = destination | source
        self._flags_logic(result, size)
        return result

    def _eor(self, destination: int, source: int, size: int) -> int:
        result = destination ^ source
        self._flags_logic(result, size)
        return result

    def _addx(self, destination: int, source: int, size: int) -> int:
        result = destination + source + ((self.SR >> 4) & 1)
        self._flags_addx(destination, source, result, size)
        return result & MASK[size]

    def _subx(self, destination: int, source: int, size: int) -> int:
        result = destination - source - ((self.SR >> 4) & 1)
        self._flags_subx(destination, source, result, size)
        return result & MASK[size]

    def _cmp(self, destination: int, source: int, size: int) -> None:
        self._flags_cmp(destination, source, destination - source, size)

    # -- the shapes ------------------------------------------------------------

    def _to_data_register(self, register: int, size: int, result: int, kind: int) -> None:
        """Refill the queue and write Dn; a long spends 2 or 4 more clocks (Table 8-4)."""
        self._prefetch()
        if size == 4:
            self._cycles += 4 if kind in (DN, AN, IMM) else 2
            self.R[register] = result
        else:
            self._write_register(register, size, result)

    def _modify(self, kind: int, register: int, size: int, operation, source: int) -> None:
        """Read-modify-write ``operation(destination, source)`` on an EA operand."""
        if kind == DN:
            result = operation(self.R[register] & MASK[size], source, size)
            self._prefetch()
            if size == 4:
                self._cycles += 4
            self._write_register(register, size, result)
            return
        address, value = self._ea_fetch(kind, register, size)
        result = operation(value, source, size)
        self._prefetch()
        self._write_result(address, size, result)

    def _write_result(self, address: int, size: int, result: int) -> None:
        if size == 4:
            self._write_long_low_first(address, result)
        elif size == 2:
            self._write_word(address, result)
        else:
            self._write_byte(address, result)

    def _binary(self, opcode: int, operation) -> None:
        """ADD, SUB, AND, OR: ``<ea>,Dn`` when bit 8 is 0, ``Dn,<ea>`` when it is 1."""
        size = SIZE[(opcode >> 6) & 3]
        kind = EA_KIND[opcode & 0x3F]
        register = opcode & 7
        dn = (opcode >> 9) & 7
        if opcode & 0x0100:
            self._modify(kind, register, size, operation, self.R[dn] & MASK[size])
            return
        source = self._ea_read(kind, register, size)
        result = operation(self.R[dn] & MASK[size], source, size)
        self._to_data_register(dn, size, result, kind)

    def _op_add(self, opcode: int) -> None:
        """ADD -- destination <- destination + source; X N Z V C (PRM 4-4; UM Table 8-4)."""
        self._binary(opcode, self._add)

    def _op_sub(self, opcode: int) -> None:
        """SUB -- destination <- destination - source; X N Z V C (PRM 4-174; UM Table 8-4)."""
        self._binary(opcode, self._sub)

    def _op_and(self, opcode: int) -> None:
        """AND -- destination <- destination AND source; N Z, V C cleared (PRM 4-15)."""
        self._binary(opcode, self._and)

    def _op_or(self, opcode: int) -> None:
        """OR -- destination <- destination OR source; N Z, V C cleared (PRM 4-150)."""
        self._binary(opcode, self._or)

    def _op_eor(self, opcode: int) -> None:
        """EOR -- <ea> <- <ea> XOR Dn; N Z, V C cleared (PRM 4-100; UM Table 8-4)."""
        size = SIZE[(opcode >> 6) & 3]
        source = self.R[(opcode >> 9) & 7] & MASK[size]
        self._modify(EA_KIND[opcode & 0x3F], opcode & 7, size, self._eor, source)

    def _op_cmp(self, opcode: int) -> None:
        """CMP -- set N Z V C from Dn - source; X unchanged (PRM 4-75; UM Table 8-4)."""
        size = SIZE[(opcode >> 6) & 3]
        source = self._ea_read(EA_KIND[opcode & 0x3F], opcode & 7, size)
        self._cmp(self.R[(opcode >> 9) & 7] & MASK[size], source, size)
        self._prefetch()
        if size == 4:
            self._cycles += 2

    # -- address-register forms (PRM 4-7, 4-77, 4-178) ------------------------

    def _address_source(self, opcode: int) -> tuple[int, int]:
        """The source of ADDA/SUBA/CMPA, sign-extended to 32 bits, and its kind."""
        size = 4 if opcode & 0x0100 else 2
        kind = EA_KIND[opcode & 0x3F]
        source = self._ea_read(kind, opcode & 7, size)
        if size == 2:
            source = sign_extend_16(source) & 0xFFFFFFFF
        return source, kind

    def _address_idle(self, opcode: int, kind: int) -> None:
        # Word forms and register/immediate sources: 4 clocks; long from memory: 2.
        if not opcode & 0x0100 or kind in (DN, AN, IMM):
            self._cycles += 4
        else:
            self._cycles += 2

    def _op_adda(self, opcode: int) -> None:
        """ADDA -- An <- An + source (word sign-extended); flags unchanged (PRM 4-7)."""
        source, kind = self._address_source(opcode)
        an = 8 + ((opcode >> 9) & 7)
        self._prefetch()
        self._address_idle(opcode, kind)
        self.R[an] = (self.R[an] + source) & 0xFFFFFFFF

    def _op_suba(self, opcode: int) -> None:
        """SUBA -- An <- An - source (word sign-extended); flags unchanged (PRM 4-178)."""
        source, kind = self._address_source(opcode)
        an = 8 + ((opcode >> 9) & 7)
        self._prefetch()
        self._address_idle(opcode, kind)
        self.R[an] = (self.R[an] - source) & 0xFFFFFFFF

    def _op_cmpa(self, opcode: int) -> None:
        """CMPA -- set N Z V C from An - source, a 32-bit compare (PRM 4-77)."""
        source, _ = self._address_source(opcode)
        self._cmp(self.R[8 + ((opcode >> 9) & 7)], source, 4)
        self._prefetch()
        self._cycles += 2

    # -- immediate forms (PRM 4-9, 4-18, 4-79, 4-102, 4-153, 4-180) ----------

    def _immediate(self, size: int) -> int:
        """The immediate operand that follows the opcode word (byte in the low half)."""
        if size == 4:
            high = self._extension()
            self._commit_pc()
            return (high << 16) | self._extension()
        self._commit_pc()
        return self._extension() & MASK[size]

    def _immediate_to_ea(self, opcode: int, operation) -> None:
        size = SIZE[(opcode >> 6) & 3]
        source = self._immediate(size)
        self._modify(EA_KIND[opcode & 0x3F], opcode & 7, size, operation, source)

    def _op_addi(self, opcode: int) -> None:
        """ADDI -- destination <- destination + #data (PRM 4-9; UM Table 8-5)."""
        self._immediate_to_ea(opcode, self._add)

    def _op_subi(self, opcode: int) -> None:
        """SUBI -- destination <- destination - #data (PRM 4-180; UM Table 8-5)."""
        self._immediate_to_ea(opcode, self._sub)

    def _op_andi(self, opcode: int) -> None:
        """ANDI -- destination <- destination AND #data (PRM 4-18; UM Table 8-5)."""
        self._immediate_to_ea(opcode, self._and)

    def _op_ori(self, opcode: int) -> None:
        """ORI -- destination <- destination OR #data (PRM 4-153; UM Table 8-5)."""
        self._immediate_to_ea(opcode, self._or)

    def _op_eori(self, opcode: int) -> None:
        """EORI -- destination <- destination XOR #data (PRM 4-102; UM Table 8-5)."""
        self._immediate_to_ea(opcode, self._eor)

    def _op_cmpi(self, opcode: int) -> None:
        """CMPI -- set N Z V C from destination - #data (PRM 4-79; UM Table 8-5)."""
        size = SIZE[(opcode >> 6) & 3]
        source = self._immediate(size)
        kind = EA_KIND[opcode & 0x3F]
        destination = self._ea_read(kind, opcode & 7, size)
        self._cmp(destination, source, size)
        self._prefetch()
        if size == 4 and kind == DN:
            self._cycles += 2

    # -- quick forms (PRM 4-11, 4-182) -------------------------------------------

    def _quick(self, opcode: int, operation, sign: int) -> None:
        size = SIZE[(opcode >> 6) & 3]
        data = QUICK[(opcode >> 9) & 7]
        kind = EA_KIND[opcode & 0x3F]
        register = opcode & 7
        if kind == AN:
            # An: the whole register, no flags, any size (PRM 4-11).
            self._prefetch()
            self._cycles += 4
            an = 8 + register
            self.R[an] = (self.R[an] + sign * data) & 0xFFFFFFFF
            return
        self._modify(kind, register, size, operation, data)

    def _op_addq(self, opcode: int) -> None:
        """ADDQ -- destination <- destination + 1..8 (PRM 4-11; UM Table 8-5)."""
        self._quick(opcode, self._add, 1)

    def _op_subq(self, opcode: int) -> None:
        """SUBQ -- destination <- destination - 1..8 (PRM 4-182; UM Table 8-5)."""
        self._quick(opcode, self._sub, -1)

    # -- multiprecision (PRM 4-14, 4-184, 4-81) ------------------------------------

    def _extended(self, opcode: int, operation) -> None:
        """ADDX and SUBX: Dy,Dx or -(Ay),-(Ax) (UM Table 8-11)."""
        size = SIZE[(opcode >> 6) & 3]
        rx = (opcode >> 9) & 7
        ry = opcode & 7
        R = self.R
        if not opcode & 8:
            result = operation(R[rx] & MASK[size], R[ry] & MASK[size], size)
            self._prefetch()
            if size == 4:
                self._cycles += 4
                R[rx] = result
            else:
                self._write_register(rx, size, result)
            return
        self._cycles += 2
        self._commit_pc()
        if size == 4:
            # Low words first, each register stepping once its high word is next.
            source_address = (R[8 + ry] - 4) & 0xFFFFFFFF
            low = self._read_word(source_address + 2)
            R[8 + ry] = source_address
            source = (self._read_word(source_address) << 16) | low
            destination_address = (R[8 + rx] - 4) & 0xFFFFFFFF
            low = self._read_word(destination_address + 2)
            R[8 + rx] = destination_address
            destination = (self._read_word(destination_address) << 16) | low
            result = operation(destination, source, 4)
            self._write_word(destination_address + 2, result)
            self._prefetch()
            self._write_word(destination_address, result >> 16)
            return
        step = self._step_size
        source_address = (R[8 + ry] - step(ry, size)) & 0xFFFFFFFF
        R[8 + ry] = source_address
        source = self._read(size, source_address)
        destination_address = (R[8 + rx] - step(rx, size)) & 0xFFFFFFFF
        R[8 + rx] = destination_address
        destination = self._read(size, destination_address)
        result = operation(destination, source, size)
        self._prefetch()
        self._write(size, destination_address, result)

    def _op_addx(self, opcode: int) -> None:
        """ADDX -- destination <- destination + source + X; Z sticky (PRM 4-14)."""
        self._extended(opcode, self._addx)

    def _op_subx(self, opcode: int) -> None:
        """SUBX -- destination <- destination - source - X; Z sticky (PRM 4-184)."""
        self._extended(opcode, self._subx)

    def _op_cmpm(self, opcode: int) -> None:
        """CMPM -- set N Z V C from (Ax)+ - (Ay)+ (PRM 4-81; UM Table 8-11).

        Ay steps before each word it reads; Ax only after its operand is in
        (corpus, T3): an address error leaves Ay moved by 2 and Ax alone.
        """
        size = SIZE[(opcode >> 6) & 3]
        ay = 8 + (opcode & 7)
        ax = 8 + ((opcode >> 9) & 7)
        R = self.R
        self._commit_pc()
        address = R[ay]
        if size == 4:
            R[ay] = (address + 2) & 0xFFFFFFFF
            high = self._read_word(address)
            R[ay] = (address + 4) & 0xFFFFFFFF
            source = (high << 16) | self._read_word(address + 2)
        else:
            R[ay] = (address + self._step_size(opcode & 7, size)) & 0xFFFFFFFF
            source = self._read(size, address)
        address = R[ax]
        destination = self._read(size, address)
        R[ax] = (address + (self._step_size(ax - 8, size) if size != 4 else 4)) & 0xFFFFFFFF
        self._cmp(destination, source, size)
        self._prefetch()

    # -- single operand (PRM 4-144, 4-146, 4-148, 4-73, 4-192, 4-190) ------------

    def _unary(self, opcode: int, operation) -> None:
        size = SIZE[(opcode >> 6) & 3]
        kind = EA_KIND[opcode & 0x3F]
        register = opcode & 7
        if kind == DN:
            result = operation(self.R[register] & MASK[size], size)
            self._prefetch()
            if size == 4:
                self._cycles += 2
            self._write_register(register, size, result)
            return
        address, value = self._ea_fetch(kind, register, size)
        result = operation(value, size)
        self._prefetch()
        self._write_result(address, size, result)

    def _negate(self, value: int, size: int) -> int:
        return self._sub(0, value, size)

    def _negate_extended(self, value: int, size: int) -> int:
        return self._subx(0, value, size)

    def _complement(self, value: int, size: int) -> int:
        result = ~value & MASK[size]
        self._flags_logic(result, size)
        return result

    def _clear(self, value: int, size: int) -> int:
        self.SR = (self.SR & (0xFF00 | X)) | Z
        return 0

    def _op_neg(self, opcode: int) -> None:
        """NEG -- destination <- 0 - destination; X N Z V C (PRM 4-144; UM Table 8-6)."""
        self._unary(opcode, self._negate)

    def _op_negx(self, opcode: int) -> None:
        """NEGX -- destination <- 0 - destination - X; Z sticky (PRM 4-146; UM Table 8-6)."""
        self._unary(opcode, self._negate_extended)

    def _op_not(self, opcode: int) -> None:
        """NOT -- destination <- ones' complement; N Z, V C cleared (PRM 4-148)."""
        self._unary(opcode, self._complement)

    def _op_clr(self, opcode: int) -> None:
        """CLR -- destination <- 0, the operand read first on the 68000 (PRM 4-73; UM Table 8-6)."""
        self._unary(opcode, self._clear)

    def _op_tst(self, opcode: int) -> None:
        """TST -- set N Z from the operand; V C cleared (PRM 4-192; UM Table 8-6)."""
        size = SIZE[(opcode >> 6) & 3]
        value = self._ea_read(EA_KIND[opcode & 0x3F], opcode & 7, size)
        self._flags_logic(value, size)
        self._prefetch()

    def _op_tas(self, opcode: int) -> None:
        """TAS -- test a byte, then set its bit 7, in one indivisible bus cycle (PRM 4-190).

        The write half goes through the host's ``tas_write`` when it gave
        one: the Genesis bus drops it (docs/undocumented-behavior.md).
        """
        kind = EA_KIND[opcode & 0x3F]
        register = opcode & 7
        if kind == DN:
            value = self.R[register] & 0xFF
            self._flags_logic(value, 1)
            self._prefetch()
            self.R[register] |= 0x80
            return
        address, value = self._ea_fetch(kind, register, 1)
        self._cycles += 2
        self._flags_logic(value, 1)
        self._cycles += 4
        self._tas_write(address & 0xFFFFFF, value | 0x80)
        self._prefetch()

    # -- multiply and divide (PRM 4-139, 4-141, 4-93, 4-96; UM Table 8-4) ------

    def _op_mulu(self, opcode: int) -> None:
        """MULU -- Dn <- Dn.w * source.w, unsigned 32-bit product (PRM 4-141)."""
        source = self._ea_read(EA_KIND[opcode & 0x3F], opcode & 7, 2)
        dn = (opcode >> 9) & 7
        product = (self.R[dn] & 0xFFFF) * source
        self._flags_logic(product, 4)
        self._prefetch()
        self._cycles += multiply_unsigned_clocks(source) - 4
        self.R[dn] = product

    def _op_muls(self, opcode: int) -> None:
        """MULS -- Dn <- Dn.w * source.w, signed 32-bit product (PRM 4-139)."""
        source = self._ea_read(EA_KIND[opcode & 0x3F], opcode & 7, 2)
        dn = (opcode >> 9) & 7
        product = (sign_extend_16(self.R[dn]) * sign_extend_16(source)) & 0xFFFFFFFF
        self._flags_logic(product, 4)
        self._prefetch()
        self._cycles += multiply_signed_clocks(source) - 4
        self.R[dn] = product

    def _op_divu(self, opcode: int) -> None:
        """DIVU -- Dn <- Dn / source.w: 16-bit remainder:quotient, unsigned (PRM 4-96)."""
        source = self._ea_read(EA_KIND[opcode & 0x3F], opcode & 7, 2)
        dn = (opcode >> 9) & 7
        dividend = self.R[dn]
        if source == 0:
            self._divide_by_zero()
            return
        quotient, remainder = divmod(dividend, source)
        self._cycles += divide_unsigned_clocks(dividend, source) - 4
        if quotient > 0xFFFF:
            # Overflow: V set, Dn unchanged; N Z C as the microcode leaves them
            # (docs/undocumented-behavior.md, "Flags after DIVU overflow").
            self.SR = (self.SR & (0xFF00 | X)) | V | N
        else:
            self.R[dn] = (remainder << 16) | quotient
            self._flags_logic(quotient, 2)
        self._prefetch()

    def _op_divs(self, opcode: int) -> None:
        """DIVS -- Dn <- Dn / source.w: 16-bit remainder:quotient, signed (PRM 4-93)."""
        source = self._ea_read(EA_KIND[opcode & 0x3F], opcode & 7, 2)
        dn = (opcode >> 9) & 7
        dividend = self.R[dn] - 0x100000000 if self.R[dn] & 0x80000000 else self.R[dn]
        divisor = sign_extend_16(source)
        if divisor == 0:
            self._divide_by_zero()
            return
        quotient = abs(dividend) // abs(divisor)
        if (dividend < 0) != (divisor < 0):
            quotient = -quotient
        remainder = dividend - quotient * divisor  # takes the dividend's sign
        self._cycles += divide_signed_clocks(dividend, divisor) - 4
        if not -0x8000 <= quotient <= 0x7FFF:
            self.SR = (self.SR & (0xFF00 | X)) | V | N
        else:
            self.R[dn] = ((remainder & 0xFFFF) << 16) | (quotient & 0xFFFF)
            self._flags_logic(quotient & 0xFFFF, 2)
        self._prefetch()


__all__ = ["MSB", "C", "N", "V", "X", "Z"]
