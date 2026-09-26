"""System control: traps, the status register, the stack pointers, STOP, RESET.

PRM Table 3-10 and Section 6; the exception processing is UM 6.2-6.3.  The
privileged instructions check S first and take the privilege-violation
exception (vector 8) in user mode, stacking the address of the instruction
itself (UM 6.3.7).  An instruction that writes SR refills the prefetch queue
afterwards, re-reading the next instruction in the (possibly new) program
space (SST MOVEtoSR, ORItoSR, ANDItoSR, EORItoSR; T3).
"""

from m68000_python._core import (
    CCR_BITS,
    MASK24,
    VECTOR_CHK,
    VECTOR_ILLEGAL,
    VECTOR_LINE_A,
    VECTOR_LINE_F,
    VECTOR_PRIVILEGE,
    VECTOR_TRAP_BASE,
    VECTOR_TRAPV,
    VECTOR_ZERO_DIVIDE,
    N,
    S,
    V,
    X,
    Z,
)
from m68000_python._ea import DN, EA_KIND, sign_extend_16


class SystemMixin:
    """Private system-control implementation."""

    # -- exceptions an instruction raises -----------------------------------

    def _not_executed(self, vector: int) -> None:
        """The exception for an instruction that is never executed, stacking its address.

        Illegal words, the line 1010 and 1111 words, and privileged
        instructions in user mode are not executed, so no trace exception
        follows them even when T was set (UM 6.3.8; MAME 0.285's microcode
        clears the pending trace in these four states, T3; WinUAE keeps it
        only after vectors 5-7 and 32-47, T2).  step() reads ``_untraced``.
        """
        self._exception(vector, self._pc - 4)
        self._untraced = True

    def _privilege_violation(self) -> None:
        """Vector 8, stacking the address of the offending instruction (UM 6.3.7)."""
        self._not_executed(VECTOR_PRIVILEGE)

    def _op_illegal(self, opcode: int) -> None:
        """ILLEGAL -- take the illegal-instruction exception, vector 4 (PRM 4-107; UM 6.3.6).

        Also every first word the 68000 does not define.  The stacked PC is
        the address of the word itself (SST ILLEGAL_LINEA, ILLEGAL_LINEF, and
        WinUAE run for $4AFC itself; UM 6.3.6 says only
        "similar to that for traps").
        """
        self._not_executed(VECTOR_ILLEGAL)

    def _op_line_a(self, opcode: int) -> None:
        """LINE A -- words $Axxx: the line 1010 emulator exception, vector 10 (UM 6.3.6)."""
        self._not_executed(VECTOR_LINE_A)

    def _op_line_f(self, opcode: int) -> None:
        """LINE F -- words $Fxxx: the line 1111 emulator exception, vector 11 (UM 6.3.6)."""
        self._not_executed(VECTOR_LINE_F)

    def _op_trap(self, opcode: int) -> None:
        """TRAP -- exception through vector 32 + n, stacking the next PC (PRM 4-188; UM 6.3.5)."""
        self._exception(VECTOR_TRAP_BASE + (opcode & 0xF), self._pc - 2, by_instruction=True)

    def _op_trapv(self, opcode: int) -> None:
        """TRAPV -- if V, exception through vector 7 (PRM 4-189; UM Table 8-14: 34 clocks)."""
        if not self.SR & V:
            self._prefetch()
            return
        # Exception processing starts before the queue refill, which is
        # therefore read in supervisor program space (SST TRAPV).
        saved = self._enter_supervisor()
        self._prefetch()
        # IR takes IRC, but the decoder keeps TRAPV: a fault while the trap
        # is processed stacks TRAPV as its IR (WinUAE's CPU tester, run, T2;
        # MAME 0.285's trpv3 never loads IRD, T3; docs/referees.md).
        self._opcode = opcode
        self._exception(VECTOR_TRAPV, self._pc - 4, idle=0, saved=saved, by_instruction=True)

    def _divide_by_zero(self, signed: bool, dividend: int) -> None:
        """DIVU/DIVS by zero: vector 5, stacking the next PC (UM 6.3.5; Table 8-14: 38+).

        The flags are undefined in PRM.  The pinned corpus has no case (its
        issue #3); WinUAE's 68000 rule (``divbyzero_special``, T2) is used:
        DIVS clears N V C and sets Z; DIVU clears V C and sets N and Z from
        the high word of the dividend (docs/undocumented-behavior.md).
        """
        ccr = self.SR & (0xFF00 | X)
        if signed:
            ccr |= Z
        elif dividend & 0x80000000:
            ccr |= N
        elif not dividend & 0xFFFF0000:
            ccr |= Z
        self.SR = ccr
        self._exception(VECTOR_ZERO_DIVIDE, self._pc - 2, idle=8, by_instruction=True)

    def _op_chk(self, opcode: int) -> None:
        """CHK -- trap through vector 6 if Dn.w < 0 or Dn.w > source (PRM 4-69; UM Table 8-12).

        N, Z, V and C are undefined in PRM; here they are what the microcode
        leaves (SST CHK), which is also WinUAE run's rule on every case and on
        Dn = 0, which no corpus has: Z from Dn, V and C clear, N set for Dn < 0
        and clear for Dn > source (docs/undocumented-behavior.md, "Flags after
        CHK").  The trap for Dn > bound takes 38 clocks, the manual's 40 less 2,
        and the negative-Dn trap 8 or 10 internal clocks (below): SST CHK; the
        2-clock questions are inside WinUAE's tolerance (docs/claims.md).
        """
        bound = sign_extend_16(self._ea_read(EA_KIND[opcode & 0x3F], opcode & 7, 2))
        value = sign_extend_16(self.R[(opcode >> 9) & 7])
        ccr = self.SR & (0xFF00 | X)
        if value == 0:
            ccr |= Z
        if value < 0:
            ccr |= N
        self.SR = ccr
        # The microcode tests the upper bound first.  A negative Dn within it
        # costs one more internal step, unless bound - Dn, taken as a 16-bit
        # difference, came out negative (SST CHK: every case agrees).
        if value > bound:
            self._exception(VECTOR_CHK, self._pc - 2, idle=8, by_instruction=True)
        elif value < 0:
            idle = 8 if (bound - value) & 0x8000 else 10
            self._exception(VECTOR_CHK, self._pc - 2, idle=idle, by_instruction=True)
        else:
            self._cycles += 6
            self._prefetch()

    # -- the status register and CCR (PRM 4-20, 4-104, 4-155, 4-123, 6-*) --------

    def _refill_after_status(self) -> None:
        """Re-read the queue from the next instruction after SR or CCR is written."""
        self._jump(self._pc - 2)

    def _write_status(self, value: int, idle: int = 4) -> None:
        self._cycles += idle
        self._set_sr(value)
        self._refill_after_status()

    def _write_ccr(self, value: int, idle: int = 4) -> None:
        self._cycles += idle
        self._set_ccr(value)
        self._refill_after_status()

    def _op_ori_to_ccr(self, opcode: int) -> None:
        """ORI to CCR -- CCR <- CCR OR #data (PRM 4-155; UM Table 8-12: 20 clocks).

        8 idle clocks, then the queue re-read from the next instruction:
        SST ORItoCCR.
        """
        data = self._immediate(1)
        self._write_ccr((self.SR | data) & CCR_BITS, idle=8)

    def _op_andi_to_ccr(self, opcode: int) -> None:
        """ANDI to CCR -- CCR <- CCR AND #data (PRM 4-20; UM Table 8-12: 20 clocks).

        8 idle clocks, then the queue re-read from the next instruction:
        SST ANDItoCCR.
        """
        data = self._immediate(1)
        self._write_ccr(self.SR & data & CCR_BITS, idle=8)

    def _op_eori_to_ccr(self, opcode: int) -> None:
        """EORI to CCR -- CCR <- CCR XOR #data (PRM 4-104; UM Table 8-12: 20 clocks).

        8 idle clocks, then the queue re-read from the next instruction:
        SST EORItoCCR.
        """
        data = self._immediate(1)
        self._write_ccr((self.SR ^ data) & CCR_BITS, idle=8)

    def _op_ori_to_sr(self, opcode: int) -> None:
        """ORI to SR -- SR <- SR OR #data, privileged (PRM 6-27; UM Table 8-12: 20 clocks).

        8 idle clocks, then the queue re-read from the next instruction in the
        new program space: SST ORItoSR.
        """
        if not self.SR & S:
            self._privilege_violation()
            return
        data = self._immediate(2)
        self._write_status(self.SR | data, idle=8)

    def _op_andi_to_sr(self, opcode: int) -> None:
        """ANDI to SR -- SR <- SR AND #data, privileged (PRM 6-2; UM Table 8-12: 20 clocks).

        8 idle clocks, then the queue re-read from the next instruction in the
        new program space: SST ANDItoSR.
        """
        if not self.SR & S:
            self._privilege_violation()
            return
        data = self._immediate(2)
        self._write_status(self.SR & data, idle=8)

    def _op_eori_to_sr(self, opcode: int) -> None:
        """EORI to SR -- SR <- SR XOR #data, privileged (PRM 6-6; UM Table 8-12: 20 clocks).

        8 idle clocks, then the queue re-read from the next instruction in the
        new program space: SST EORItoSR.
        """
        if not self.SR & S:
            self._privilege_violation()
            return
        data = self._immediate(2)
        self._write_status(self.SR ^ data, idle=8)

    def _op_move_to_ccr(self, opcode: int) -> None:
        """MOVE to CCR -- CCR <- low byte of the source word (PRM 4-123; UM Table 8-12).

        4 idle clocks, then the queue re-read from the next instruction; the PC
        an address error stacks: SST MOVEtoCCR.
        """
        value = self._ea_read(EA_KIND[opcode & 0x3F], opcode & 7, 2)
        self._write_ccr(value)

    def _op_move_to_sr(self, opcode: int) -> None:
        """MOVE to SR -- SR <- source word, privileged (PRM 6-19; UM Table 8-12).

        4 idle clocks, then the queue re-read from the next instruction in the
        new program space; the PC an address error stacks: SST MOVEtoSR.
        """
        if not self.SR & S:
            self._privilege_violation()
            return
        value = self._ea_read(EA_KIND[opcode & 0x3F], opcode & 7, 2)
        self._write_status(value)

    def _op_move_from_sr(self, opcode: int) -> None:
        """MOVE from SR -- destination <- SR; not privileged on the 68000 (PRM 6-17; UM 6.3.7).

        The memory operand is read before it is written, as the chip does; the
        2 idle clocks of the register form and the PC an address error stacks:
        SST MOVEfromSR.
        """
        kind = EA_KIND[opcode & 0x3F]
        register = opcode & 7
        if kind == DN:
            self._prefetch()
            self._cycles += 2
            self._write_register(register, 2, self.SR)
            return
        address, _ = self._ea_fetch(kind, register, 2)  # read first, as the chip does
        self._prefetch()
        self._write_word(address, self.SR)

    def _op_move_usp(self, opcode: int) -> None:
        """MOVE USP -- An <-> USP, privileged (PRM 6-21; UM Table 8-12: 4 clocks)."""
        if not self.SR & S:
            self._privilege_violation()
            return
        an = 8 + (opcode & 7)
        if opcode & 8:
            self.R[an] = self._other_sp
        else:
            self._other_sp = self.R[an]
        self._prefetch()

    # -- returns that restore state --------------------------------------------

    def _op_rte(self, opcode: int) -> None:
        """RTE -- SR <- (SP)+, PC <- (SP)+, privileged (PRM 6-84; UM Table 8-12: 20 clocks)."""
        if not self.SR & S:
            self._privilege_violation()
            return
        sp = self.R[15]
        status = self._read_word(sp)
        high = self._read_word(sp + 2)
        self.R[15] = (sp + 6) & 0xFFFFFFFF
        pc = (high << 16) | self._read_word(sp + 4)
        self._set_sr(status)
        self._jump(pc)

    # -- STOP and RESET ------------------------------------------------------------

    def _op_stop(self, opcode: int) -> None:
        """STOP -- SR <- #data, then stop until an interrupt or reset (PRM 6-85; UM Table 8-12).

        The immediate is taken from IRC without a refill and the queue is left
        as it was, so a stopped CPU resumes at the instruction after STOP:
        SST STOP.
        """
        if not self.SR & S:
            self._privilege_violation()
            return
        data = self.irc
        self._cycles += 4
        self._set_sr(data)
        self.stopped = True

    def _op_reset(self, opcode: int) -> None:
        """RESET -- pulse the RESET line, privileged (PRM 6-83; UM Table 8-12: 132 clocks).

        The pulse is 124 clocks; the instruction takes 132 in all (UM Table
        8-12): 128 before the closing prefetch, as SST RESET records.  The
        processor itself is not reset.  A host that wants to see the pulse sets
        ``reset_devices``, called with no arguments.
        """
        if not self.SR & S:
            self._privilege_violation()
            return
        self._cycles += 128
        callback = getattr(self, "reset_devices", None)
        if callback is not None:
            callback()
        self._prefetch()


__all__ = ["MASK24"]
