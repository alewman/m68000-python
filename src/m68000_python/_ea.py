"""Effective addresses: the twelve modes of the 68000 (PRM 2.2).

The 6-bit EA field is ``mode:register``; mode 7 uses the register field to
select five more forms.  :data:`EA_KIND` maps the field to one of the twelve
kinds below once, at import, and handlers carry the kind, not the field.

Timing is Table 8-1 of the UM, spent in the order the microcode spends it:
``-(An)`` and ``(d8,An,Xn)`` start with two internal clocks, extension words
are taken from the prefetch queue (each one refills it with a program read),
and the operand access comes last.  The steps that bring the microcode's PC
register up to the fetch address (what an address error stacks) are the
corpus's, T3.
"""

from m68000_python._core import MASK

# The twelve kinds, in PRM 2.2 order.
DN = 0  # Dn                data register direct
AN = 1  # An                address register direct
IND = 2  # (An)              address register indirect
POSTINC = 3  # (An)+        indirect with postincrement
PREDEC = 4  # -(An)         indirect with predecrement
DISP = 5  # (d16,An)        indirect with displacement
INDEX = 6  # (d8,An,Xn)     indirect with index
ABSW = 7  # (xxx).W        absolute short
ABSL = 8  # (xxx).L        absolute long
PCDISP = 9  # (d16,PC)      program counter with displacement
PCINDEX = 10  # (d8,PC,Xn)  program counter with index
IMM = 11  # #<data>         immediate

KIND_NAMES = (
    "Dn", "An", "(An)", "(An)+", "-(An)", "(d16,An)", "(d8,An,Xn)",
    "(xxx).W", "(xxx).L", "(d16,PC)", "(d8,PC,Xn)", "#<data>",
)  # fmt: skip


def _kind(field: int) -> int | None:
    mode, register = field >> 3, field & 7
    if mode < 7:
        return mode
    return (ABSW, ABSL, PCDISP, PCINDEX, IMM, None, None, None)[register]


#: EA field (bits 5-0) -> kind, or None for mode 7 registers 5-7 (illegal).
EA_KIND: tuple[int | None, ...] = tuple(_kind(field) for field in range(64))

# The addressing categories of PRM Table 2-4, as sets of kinds.
ALL = frozenset(range(12))
DATA = ALL - {AN}
MEMORY = ALL - {DN, AN}
CONTROL = frozenset({IND, DISP, INDEX, ABSW, ABSL, PCDISP, PCINDEX})
ALTERABLE = frozenset({DN, AN, IND, POSTINC, PREDEC, DISP, INDEX, ABSW, ABSL})
DATA_ALTERABLE = DATA & ALTERABLE
MEMORY_ALTERABLE = MEMORY & ALTERABLE


def sign_extend_8(value: int) -> int:
    return (value & 0xFF) - 0x100 if value & 0x80 else value & 0xFF


def sign_extend_16(value: int) -> int:
    return (value & 0xFFFF) - 0x10000 if value & 0x8000 else value & 0xFFFF


def word_to_long(value: int) -> int:
    """A word sign-extended to 32 bits, as An, MOVEM.W and EXT.L take it (PRM 2.3)."""
    return sign_extend_16(value) & 0xFFFFFFFF


class EAMixin:
    """Private effective-address implementation shared by every family."""

    def _step_size(self, register: int, size: int) -> int:
        # (A7)+ and -(A7) move by 2 for a byte, keeping SP even (PRM 2.2.4-2.2.5).
        return 2 if size == 1 and register == 7 else size

    def _index(self, base: int) -> int:
        """Take the brief extension word from the queue and apply it to ``base``."""
        return self._indexed(base, self._extension())

    def _indexed(self, base: int, extension: int) -> int:
        """Apply a brief extension word (PRM 2.4) to ``base``.

        Bits 15-12 name Xn (D0-D7, A0-A7), bit 11 chooses the sign-extended
        low word (0) or the whole register (1), bits 7-0 are the signed
        displacement.  Bits 10-8, the 68020's scale, are ignored (PRM 2.4).
        JMP, JSR, LEA and PEA apply the word still waiting in IRC.
        """
        index = self.R[extension >> 12]
        if not extension & 0x0800:
            index = sign_extend_16(index)
        return (base + index + sign_extend_8(extension)) & 0xFFFFFFFF

    def _ea_address(self, kind: int, register: int, size: int) -> int:
        """Compute a memory operand's address, with its extension words and clocks.

        The standard source-operand sequence: the one TST, CMP, ADD <ea>,Dn
        and the read half of a read-modify-write use.
        """
        R = self.R
        if kind == IND:
            return R[8 + register]
        if kind == POSTINC:
            address = R[8 + register]
            R[8 + register] = (address + self._step_size(register, size)) & 0xFFFFFFFF
            return address
        if kind == PREDEC:
            self._cycles += 2
            self._commit_pc()
            address = (R[8 + register] - self._step_size(register, size)) & 0xFFFFFFFF
            R[8 + register] = address
            return address
        if kind == DISP:
            return (R[8 + register] + sign_extend_16(self._extension())) & 0xFFFFFFFF
        if kind == INDEX:
            self._cycles += 2
            return self._index(R[8 + register])
        if kind == ABSW:
            self._commit_pc()
            return word_to_long(self._extension())
        if kind == ABSL:
            high = self._extension()
            self._commit_pc()
            return ((high << 16) | self._extension()) & 0xFFFFFFFF
        if kind == PCDISP:
            base = self._pc - 2  # the address of the extension word itself
            return (base + sign_extend_16(self._extension())) & 0xFFFFFFFF
        if kind == PCINDEX:
            self._cycles += 2
            return self._index(self._pc - 2)
        raise AssertionError(f"not a memory kind: {kind}")

    def _ea_read(self, kind: int, register: int, size: int) -> int:
        """Fetch a source operand of any kind (UM Table 8-1)."""
        if kind == DN:
            return self.R[register] & MASK[size]
        if kind == AN:
            return self.R[8 + register] & MASK[size]
        if kind == IMM:
            if size == 4:
                return self._extension_long()
            return self._extension() & MASK[size]
        return self._ea_fetch(kind, register, size)[1]

    def _ea_fetch(self, kind: int, register: int, size: int) -> tuple[int, int]:
        """Address and value of a memory operand: the read half of every access.

        PC-relative operands are read in program space (FC 2/6, UM Table 3-2).
        """
        if size == 4 and kind == POSTINC:
            # A long (An)+ steps An between its two reads (SST ADD.l, MOVE.l and
            # every long (An)+ read; T3): a fault on
            # the first leaves An alone.
            R = self.R
            address = R[8 + register]
            high = self._read_word(address)
            R[8 + register] = (address + 4) & 0xFFFFFFFF
            return address, (high << 16) | self._read_word(address + 2)
        if size == 4 and kind == PREDEC:
            # A long -(An) does not bring PC up to date, unlike a word (SST
            # ADD.l, MOVE.l and every long -(An) read; T3).
            self._cycles += 2
            address = (self.R[8 + register] - 4) & 0xFFFFFFFF
            self.R[8 + register] = address
            return address, self._read_long(address)
        address = self._ea_address(kind, register, size)
        if kind >= PCDISP:
            return address, self._read_program_operand(size, address)
        return address, self._read(size, address)

    def _write_register(self, register: int, size: int, value: int) -> None:
        """Write the low byte, word or all of a data register (PRM 1.1)."""
        if size == 4:
            self.R[register] = value & 0xFFFFFFFF
        else:
            mask = MASK[size]
            self.R[register] = (self.R[register] & ~mask & 0xFFFFFFFF) | (value & mask)
