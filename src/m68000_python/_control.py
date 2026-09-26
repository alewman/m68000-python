"""Program control: branches, jumps, returns, DBcc, Scc, NOP (PRM Table 3-9).

A taken branch or jump throws the prefetch queue away and refills it from
the target with two program reads (UM Table 8-9, "What prefetch does to
these numbers" in docs/timing.md).  A target at an odd address faults on the
first of those reads.
"""

from m68000_python._ea import (
    ABSL,
    ABSW,
    DISP,
    DN,
    EA_KIND,
    IND,
    INDEX,
    PCDISP,
    PCINDEX,
    sign_extend_8,
    sign_extend_16,
    word_to_long,
)
from m68000_python._flags import CONDITION


class ControlMixin:
    """Private program-control implementation."""

    # -- branches (PRM 4, Bcc/BRA/BSR; UM Table 8-9) -------------------------

    def _branch_target(self, opcode: int) -> int:
        """The target of a Bcc/BRA/BSR: displacement from the extension word's address.

        An 8-bit displacement of 0 means a 16-bit one follows; $FF is an
        ordinary -1 on the 68000 (the 68020's long form does not exist;
        corpus issue #4).
        """
        base = self._pc - 2  # the address of the word after the opcode
        displacement = opcode & 0xFF
        if displacement:
            return (base + sign_extend_8(displacement)) & 0xFFFFFFFF
        return (base + sign_extend_16(self.irc)) & 0xFFFFFFFF

    def _op_bra(self, opcode: int) -> None:
        """BRA -- branch always: PC <- PC + d (PRM 4-25; UM Table 8-9: 10 clocks)."""
        self._cycles += 2
        self._jump(self._branch_target(opcode))

    def _op_bcc(self, opcode: int) -> None:
        """Bcc -- branch if the condition holds (PRM 4-25; UM Table 8-9).

        Taken: 10 clocks, two internal then the refill.  Not taken with an
        8-bit displacement: 8 clocks; with a 16-bit one, 12, the extra read
        skipping the displacement word.
        """
        if CONDITION[(opcode >> 8) & 0xF][self.SR & 0xF]:
            self._cycles += 2
            self._jump(self._branch_target(opcode))
            return
        self._cycles += 4
        if not opcode & 0xFF:
            self._extension()
        self._prefetch()

    def _op_bsr(self, opcode: int) -> None:
        """BSR -- push the return address, then branch (PRM 4-59; UM Table 8-9: 18 clocks).

        A fault on the refill stacks the target itself: SST BSR.
        """
        target = self._branch_target(opcode)
        # The return address is past the displacement word, when there is one.
        returns = self._pc if not opcode & 0xFF else self._pc - 2
        self._cycles += 2
        self._push_long(returns)
        self._fault_pc = target  # a fault on the refill stacks the target
        self._jump(target)

    # -- DBcc and Scc (PRM 4-91, 4-173) ---------------------------------------

    def _op_dbcc(self, opcode: int) -> None:
        """DBcc -- if cc is false, decrement Dn.w; branch unless it is -1 (PRM 4-91; UM Table 8-9).

        UM Table 8-9: condition true 12 clocks; false and branching 10; false
        with the count expired 14.

        The branch target's word is read before Dn is written, so an odd target
        faults with Dn unchanged and stacks the instruction's address + 4:
        SST DBcc.  WinUAE run stacks the target + 2 instead: contested, the core
        follows the gate (docs/claims.md).
        """
        register = opcode & 7
        if CONDITION[(opcode >> 8) & 0xF][self.SR & 0xF]:
            self._cycles += 4
            self._extension()
            self._prefetch()
            return
        # Condition false: the word at the branch target is read whether or
        # not the count expires, and Dn is written only after that read, so
        # an odd target faults with Dn unchanged.
        self._cycles += 2
        target = (self._pc - 2 + sign_extend_16(self.irc)) & 0xFFFFFFFF
        self._commit_pc()
        count = (self.R[register] - 1) & 0xFFFF
        self.irc = self._read_program_word(target)
        if count != 0xFFFF:
            self._pc = (target + 2) & 0xFFFFFFFF
        else:
            self._extension()  # expired: carry on after the displacement word
        self.R[register] = (self.R[register] & 0xFFFF0000) | count
        self._prefetch()

    def _op_scc(self, opcode: int) -> None:
        """Scc -- set a byte to $FF if the condition holds, else $00 (PRM 4-173; UM Table 8-6).

        UM Table 8-6: register 4 clocks false, 6 true; memory 8 plus the EA,
        the operand read before it is written.  The read, the refill between it
        and the write, and the PC an address error stacks: SST Scc.
        """
        value = 0xFF if CONDITION[(opcode >> 8) & 0xF][self.SR & 0xF] else 0
        kind = EA_KIND[opcode & 0x3F]
        register = opcode & 7
        if kind == DN:
            self._prefetch()
            if value:
                self._cycles += 2
            self.R[register] = (self.R[register] & 0xFFFFFF00) | value
            return
        address = self._ea_address(kind, register, 1)
        self._read_byte(address)
        self._prefetch()
        self._write_byte(address, value)

    # -- jumps and returns ----------------------------------------------------

    def _control_address(self, kind: int, register: int) -> int:
        """The address of a control-mode operand, for JMP/JSR/LEA/PEA (UM Table 8-10).

        Unlike an operand read, these modes do not take the extension word
        from the queue as they go: the refill happens later, as part of the
        jump or the next step.  Internal clocks are the table's.
        """
        R = self.R
        if kind == IND:
            return R[8 + register]
        if kind == DISP:
            return (R[8 + register] + sign_extend_16(self.irc)) & 0xFFFFFFFF
        if kind == INDEX:
            return self._indexed(R[8 + register], self.irc)
        if kind == ABSW:
            return word_to_long(self.irc)
        if kind == ABSL:
            high = self._extension()
            return ((high << 16) | self.irc) & 0xFFFFFFFF
        if kind == PCDISP:
            return (self._pc - 2 + sign_extend_16(self.irc)) & 0xFFFFFFFF
        if kind == PCINDEX:
            return self._indexed(self._pc - 2, self.irc)
        raise AssertionError(f"not a control kind: {kind}")

    def _op_jmp(self, opcode: int) -> None:
        """JMP -- PC <- effective address (PRM 4-108; UM Table 8-10)."""
        kind = EA_KIND[opcode & 0x3F]
        target = self._control_address(kind, opcode & 7)
        if kind in (DISP, ABSW, PCDISP):
            self._cycles += 2
        elif kind in (INDEX, PCINDEX):
            self._cycles += 6
        self._jump(target)

    def _op_jsr(self, opcode: int) -> None:
        """JSR -- push the return address, PC <- effective address (PRM 4-109; UM Table 8-10).

        The target's first word is read before the push, so an odd target faults
        with nothing pushed: SST JSR.  Through (d16,An), (d8,An,Xn), (d16,PC) and
        (d8,PC,Xn) WinUAE run stacks 2 less than the gate: contested, the core
        follows the gate (docs/claims.md).
        """
        kind = EA_KIND[opcode & 0x3F]
        target = self._control_address(kind, opcode & 7)
        # The return address is past the extension words.
        returns = self._pc - 2 if kind == IND else self._pc
        if kind in (DISP, ABSW, PCDISP):
            self._cycles += 2
        elif kind in (INDEX, PCINDEX):
            self._cycles += 6
        if kind != IND:
            self._commit_pc()
        # The target's first word is read before the push, so an odd target
        # faults with nothing pushed.
        target &= 0xFFFFFFFF
        self.irc = self._read_program_word(target)
        self._pc = (target + 2) & 0xFFFFFFFF
        self._push_long(returns)
        self._prefetch()

    def _op_rts(self, opcode: int) -> None:
        """RTS -- PC <- (SP)+ (PRM 4-169; UM Table 8-12: 16 clocks)."""
        self._jump(self._pop_long())

    def _op_rtr(self, opcode: int) -> None:
        """RTR -- CCR <- (SP)+, then PC <- (SP)+ (PRM 4-168; UM Table 8-12: 20 clocks)."""
        ccr = self._pop_word()
        self._set_ccr(ccr)
        self._jump(self._pop_long())

    def _op_nop(self, opcode: int) -> None:
        """NOP -- no operation (PRM 4-147; UM Table 8-12: 4 clocks, the prefetch)."""
        self._prefetch()
