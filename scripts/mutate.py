"""Mutation testing of the verification suite: how much does a passing suite prove?

A mutant is the core with one small semantic change -- a flag rule off by
one, a sign extension dropped, a stacked PC moved by two.  A mutant the suite
fails is *killed*; one it passes *survives*, and a survivor is a hole in the
evidence: behaviour the core could get wrong without any test noticing.  The
list of survivors is the deliverable, and docs/mutation.md is its write-up.

    python scripts/mutate.py list                       # the mutants, by area
    python scripts/mutate.py run --jobs 4 --out R.json  # phase 1: the relevant subset
    python scripts/mutate.py escalate R.json --jobs 4   # phase 2: survivors vs everything
    python scripts/mutate.py recheck R.json             # phase 3: survivors after new tests
    python scripts/mutate.py detect R.json              # survivors vs the 680x0 detector
    python scripts/mutate.py report R.json              # the tables and the survivors

Each mutant is applied to a **copy** of ``src/m68000_python`` in a scratch
directory, never to ``src/`` itself (the run checks that ``src/`` is byte for
byte unchanged at the end), and the suite runs in a child process whose
``m68000_python`` is verified to be the copy.  What a mutant runs against is
stated per mutant and recorded in the results:

* **phase 1**: the SingleStepTests/m68000 files named in its ``corpus`` field
  (every case of each, compared exactly as tests/test_corpus.py compares
  them; a file stops at its first failing case), plus every fast test module
  (``FAST_TESTS``: all of tests/ except the corpus gate);
* **phase 2** (``escalate``), for phase-1 survivors and for mutants that
  only the session's new tests killed: all 127 corpus files plus the same
  fast tests -- the whole suite -- so that what the older suite catches is
  measured against the full gate, not a subset;
* **phase 3** (``recheck``), after tests were written for the survivors:
  the phase-2 survivors against the whole suite as it then stands;
* **detector** (``detect``), for whatever survives the last phase: the matching
  files of the SingleStepTests/680x0 corpus, which is not a gate (212,400 of
  its cases disagree with the core for named reasons, docs/validation.md),
  compared case by case with the unmutated core: a mutant that turns an
  agreeing case into a disagreeing one is *visible to the detector*.

A mutant that survives phase 1 has only escaped a subset; one that survives
phase 2 has escaped everything this repository runs as a test.  Mutants are written
before the run and not tuned to it; a timeout (a hung mutant) counts as
killed and is reported as such.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "m68000_python"
TESTS = ROOT / "tests"
VECTORS = TESTS / "68000_test_vectors" / "m68000" / "v1"

#: Every test module except the corpus gate, run whole for every mutant.  The
#: list is read from tests/ when a run starts, and each result records the
#: modules it ran.
FAST_TESTS = tuple(
    sorted(path.name for path in TESTS.glob("test_*.py") if path.name != "test_corpus.py")
)
#: Modules added in the coverage and mutation session (docs/coverage.md,
#: docs/mutation.md).  Kills by these alone are reported separately, to show
#: what the suite at e3629c1 -- the gate and the older tests -- did not catch.
NEW_TESTS = (
    "test_coverage_gaps.py",
    "test_register_renaming.py",
    "test_mutation_survivors.py",
)
HARTE_VECTORS = TESTS / "68000_test_vectors" / "680x0" / "68000" / "v1"
TIMEOUT = 600  # seconds per mutant run; a hang counts as a kill


@dataclass(frozen=True)
class Mutant:
    """One semantic change: replace ``old`` with ``new`` at its first
    occurrence after ``anchor`` (which must occur exactly once) in ``file``."""

    id: str
    area: str
    file: str
    anchor: str
    old: str
    new: str
    what: str
    corpus: tuple[str, ...] = ()


ARITH = ("ADD.b", "ADD.w", "ADD.l", "SUB.b", "SUB.w", "SUB.l")
LOGIC = ("AND.b", "AND.l", "OR.w", "EOR.b", "NOT.w", "TST.l", "MOVE.w", "MOVE.l")
CMPS = ("CMP.b", "CMP.w", "CMP.l", "CMPA.w", "CMPA.l")
EXTENDED = ("ADDX.b", "ADDX.w", "ADDX.l", "SUBX.b", "SUBX.w", "SUBX.l", "NEGX.w")
SHIFTS = ("ASL.b", "ASL.w", "ASL.l", "ASR.b", "ASR.w", "ASR.l", "LSL.b", "LSL.w", "LSL.l",
          "LSR.b", "LSR.w", "LSR.l")  # fmt: skip
ROTATES = ("ROL.b", "ROL.w", "ROL.l", "ROR.b", "ROR.w", "ROR.l", "ROXL.b", "ROXL.w",
           "ROXL.l", "ROXR.b", "ROXR.w", "ROXR.l")  # fmt: skip
BCD = ("ABCD", "SBCD", "NBCD")
DIVIDE = ("DIVU", "DIVS")
MULTIPLY = ("MULU", "MULS")
EXCEPTIONS = ("TRAP", "TRAPV", "CHK", "ILLEGAL_LINEA", "ILLEGAL_LINEF")
PRIVILEGED = ("MOVEtoSR", "ANDItoSR", "ORItoSR", "EORItoSR", "RTE", "STOP", "RESET",
              "MOVEtoUSP", "MOVEfromUSP")  # fmt: skip
ADDRESSING = ("MOVE.b", "MOVE.w", "MOVE.l", "LEA", "PEA", "ADD.w", "CMP.l")
BRANCHES = ("Bcc", "BSR", "DBcc", "Scc", "JMP", "JSR", "RTS", "RTR")

# fmt: off
MUTANTS: tuple[Mutant, ...] = (
    # -- carry -----------------------------------------------------------------
    Mutant('C1', 'carry', '_flags.py', 'def _flags_add(',
           'if result > MASK[size]:',
           'if result >= MASK[size]:',
           'ADD carry set on a result equal to the mask', ARITH),
    Mutant('C2', 'carry', '_flags.py', 'def _flags_sub(',
           'if result < 0:',
           'if result <= 0:',
           'SUB borrow set on a zero result', ARITH),
    Mutant('C3', 'carry', '_flags.py', 'def _flags_cmp(',
           'ccr |= C',
           'ccr |= 0',
           'CMP never sets C', CMPS),
    Mutant('C4', 'carry', '_flags.py', 'def _flags_addx(',
           'if result > MASK[size]:',
           'if result > MASK[size] + 1:',
           'ADDX misses the carry of mask + 1', EXTENDED),
    Mutant('C5', 'carry', '_flags.py', 'def _flags_subx(',
           'if result < 0:',
           'if result < -1:',
           'SUBX misses a borrow of exactly one', EXTENDED),
    Mutant('C6', 'carry', '_shifts.py', 'if kind == "ls":',
           'carry = (value >> (bits - count)) & 1 if count <= bits else 0',
           'carry = (value >> (bits - count + 1)) & 1 if count <= bits else 0',
           'LSL takes C from the wrong bit', SHIFTS),
    Mutant('C7', 'carry', '_shifts.py', 'if kind == "as":\n        signed',
           'carry = (signed >> (count - 1)) & 1',
           'carry = (signed >> count) & 1',
           'ASR takes C from the wrong bit', SHIFTS),
    Mutant('C8', 'carry', '_shifts.py', 'if kind == "ro":',
           'carry = result & 1',
           'carry = (result >> 1) & 1',
           'ROL takes C from bit 1', ROTATES),
    Mutant('C9', 'carry', '_flags.py', 'def _flags_logic(',
           'ccr = self.SR & (0xFF00 | X)',
           'ccr = self.SR & (0xFF00 | X | C)',
           'logic operations keep C instead of clearing it', LOGIC),
    Mutant('C10', 'carry', '_alu.py', 'def _op_divu(',
           '| V | N',
           '| V | N | C',
           'DIVU overflow sets C', DIVIDE),
    # -- overflow --------------------------------------------------------------
    Mutant('V1', 'overflow', '_flags.py', 'def _flags_add(',
           '(source ^ result) & (destination ^ result) & msb',
           '(source ^ result) & msb',
           "ADD overflow ignores the destination's sign", ARITH),
    Mutant('V2', 'overflow', '_flags.py', 'def _flags_sub(',
           '(source ^ destination) & (result ^ destination) & msb',
           '(source ^ result) & (result ^ destination) & msb',
           'SUB overflow rule wrong', ARITH),
    Mutant('V3', 'overflow', '_flags.py', 'def _flags_cmp(',
           'ccr |= V',
           'ccr |= 0',
           'CMP never sets V', CMPS),
    Mutant('V4', 'overflow', '_shifts.py', 'overflow = False',
           'if (shifted ^ result) & msb:',
           'if (shifted ^ result) & msb and _ == count - 1:',
           'ASL overflow only checks the last step', SHIFTS),
    Mutant('V5', 'overflow', '_flags.py', 'def _flags_logic(',
           'ccr = self.SR & (0xFF00 | X)',
           'ccr = self.SR & (0xFF00 | X | V)',
           'logic operations keep V', LOGIC),
    Mutant('V6', 'overflow', '_alu.py', 'def _op_divs(',
           'if not -0x8000 <= quotient <= 0x7FFF:',
           'if not -0x8000 < quotient <= 0x7FFF:',
           'DIVS calls a quotient of -32768 an overflow', DIVIDE),
    Mutant('V7', 'overflow', '_alu.py', 'def _op_divu(',
           'if quotient > 0xFFFF:',
           'if quotient >= 0xFFFF:',
           'DIVU calls a quotient of $FFFF an overflow', DIVIDE),
    Mutant('V8', 'overflow', '_bcd.py', 'def decimal_add(',
           'if result & 0x80 and not uncorrected & 0x80:',
           'if result & 0x80:',
           'ABCD V set whenever the result is negative', BCD),
    Mutant('V9', 'overflow', '_flags.py', 'def _flags_subx(',
           '(source ^ destination) & (result ^ destination) & msb',
           '(source ^ destination) & msb',
           'SUBX overflow ignores the result', EXTENDED),
    Mutant('V10', 'overflow', '_system.py', 'def _op_chk(',
           'ccr = self.SR & (0xFF00 | X)',
           'ccr = self.SR & (0xFF00 | X | V)',
           'CHK keeps V (undefined in PRM; corpus pins it)', ('CHK',)),
    # -- zero ------------------------------------------------------------------
    Mutant('Z1', 'zero', '_flags.py', 'def _flags_add(',
           'if not result & MASK[size]:',
           'if not result:',
           'ADD Z tested on the unmasked sum (misses a carry to zero)', ARITH),
    Mutant('Z2', 'zero', '_flags.py', 'def _flags_addx(',
           'ccr = self.SR & (0xFF00 | Z)',
           'ccr = self.SR & 0xFF00',
           'ADDX Z not sticky: never set', EXTENDED),
    Mutant('Z3', 'zero', '_flags.py', 'def _flags_subx(',
           'if result & MASK[size]:',
           'if result:',
           'SUBX Z tested on the unmasked difference', EXTENDED),
    Mutant('Z4', 'zero', '_flags.py', 'def _flags_high_word(',
           'if value & 0xFFFF0000:',
           'if value & 0x7FFF0000:',
           "a long's Z ignores bit 31", ('MOVE.l', 'TST.l', 'AND.l')),
    Mutant('Z5', 'zero', '_bits.py', 'def _set_z(',
           'if value >> number & 1:',
           'if value >> number & 3:',
           'BTST tests two bits', ('BTST', 'BCHG', 'BCLR', 'BSET')),
    Mutant('Z6', 'zero', '_bcd.py', 'def _set_bcd_flags(',
           '(sr & flags & Z)',
           '(flags & Z)',
           'BCD Z not sticky', BCD),
    Mutant('Z7', 'zero', '_flags.py', 'def _flags_logic(',
           'if not result & MASK[size]:',
           'if not result & 0xFFFF:',
           'logic Z always tests the low word', LOGIC),
    Mutant('Z8', 'zero', '_alu.py', 'self.R[dn] = (remainder << 16) | quotient',
           'self._flags_logic(quotient, 2)',
           'self._flags_logic((remainder << 16) | quotient, 4)',
           'DIVU N Z from the whole long, not the quotient', DIVIDE),
    # -- negative --------------------------------------------------------------
    Mutant('N1', 'negative', '_flags.py', 'def _flags_add(',
           'if result & msb:',
           'if result & (msb >> 1):',
           'ADD N from the wrong bit', ARITH),
    Mutant('N2', 'negative', '_flags.py', 'def _flags_logic(',
           'if result & MSB[size]:',
           'if result & MSB[4]:',
           'logic N always from bit 31', LOGIC),
    Mutant('N3', 'negative', '_alu.py', 'def _op_muls(',
           'self._flags_logic(product, 4)',
           'self._flags_logic(product, 2)',
           'MULS N Z from the low word', MULTIPLY),
    Mutant('N4', 'negative', '_shifts.py', 'def _nz(',
           'if result & MSB[size]:',
           'if result & MSB[2]:',
           'shift N always from bit 15', SHIFTS),
    Mutant('N5', 'negative', '_bcd.py', 'def decimal_add(',
           'if result & 0x80:\n        flags |= N',
           'if uncorrected & 0x80:\n        flags |= N',
           'ABCD N from the uncorrected byte', BCD),
    Mutant('N6', 'negative', '_loads.py', 'def _op_swap(',
           'self._flags_logic(value, 4)',
           'self._flags_logic(value, 2)',
           'SWAP N Z from the low word', ('SWAP',)),
    Mutant('N7', 'negative', '_loads.py', 'def _op_ext(',
           'self._flags_logic(value, 2)',
           'self._flags_logic(value, 1)',
           'EXT.W N Z from the byte', ('EXT.w',)),
    Mutant('N8', 'negative', '_alu.py', 'def _op_divs(',
           '| V | N',
           '| V',
           'DIVS overflow leaves N clear', DIVIDE),
    # -- extend ----------------------------------------------------------------
    Mutant('X1', 'extend', '_flags.py', 'def _flags_cmp(',
           'ccr = self.SR & (0xFF00 | X)',
           'ccr = self.SR & 0xFF00',
           'CMP clears X', CMPS),
    Mutant('X2', 'extend', '_flags.py', 'def _flags_add(',
           'ccr |= X | C',
           'ccr |= C',
           'ADD never sets X', ARITH),
    Mutant('X3', 'extend', '_shifts.py', 'def _set_shift_flags(',
           'if kind == "ro" or (count == 0 and kind != "rox"):',
           'if count == 0 and kind != "rox":',
           'ROL/ROR change X', ROTATES),
    Mutant('X4', 'extend', '_alu.py', 'def _addx(',
           '((self.SR >> 4) & 1)',
           '((self.SR >> 0) & 1)',
           'ADDX adds C instead of X', EXTENDED),
    Mutant('X5', 'extend', '_shifts.py', 'if count == 0:',
           'carry = C if (kind == "rox" and x) else 0',
           'carry = 0',
           'ROXd by 0 does not copy X into C', ROTATES),
    Mutant('X6', 'extend', '_flags.py', 'def _flags_low_word(',
           'ccr = self.SR & (0xFF00 | X)',
           'ccr = self.SR & 0xFF00',
           'a long MOVE clears X', ('MOVE.l',)),
    Mutant('X7', 'extend', '_bcd.py', 'def decimal_subtract(',
           'if binary < 0 or corrected < 0:',
           'if binary < 0:',
           "SBCD misses the correction's borrow", BCD),
    Mutant('X8', 'extend', '_alu.py', 'def _negate_extended(',
           'return self._subx(0, value, size)',
           'return self._sub(0, value, size)',
           'NEGX ignores X', ('NEGX.b', 'NEGX.w', 'NEGX.l')),
    # -- sign extension --------------------------------------------------------
    Mutant('S1', 'sign extension', '_ea.py', 'def sign_extend_8(',
           'if value & 0x80',
           'if value & 0x40',
           'sign_extend_8 tests bit 6', ('MOVE.q', 'Bcc', 'LEA')),
    Mutant('S2', 'sign extension', '_ea.py', 'def sign_extend_16(',
           'if value & 0x8000',
           'if value & 0x4000',
           'sign_extend_16 tests bit 14', ADDRESSING),
    Mutant('S3', 'sign extension', '_ea.py', 'def _index(',
           'index = sign_extend_16(index)',
           'index = index & 0xFFFF',
           '(d8,An,Xn) zero-extends a word index', ADDRESSING),
    Mutant('S4', 'sign extension', '_control.py', 'def _brief_index(',
           'index = sign_extend_16(index)',
           'index = index & 0xFFFF',
           'JMP/JSR/LEA (d8,An,Xn) zero-extends a word index', ('JMP', 'JSR', 'LEA', 'PEA')),
    Mutant('S5', 'sign extension', '_loads.py', 'def _op_movea(',
           'value = sign_extend_16(value) & 0xFFFFFFFF',
           'value = value & 0xFFFF',
           'MOVEA.W zero-extends', ('MOVEA.w',)),
    Mutant('S6', 'sign extension', '_alu.py', 'def _address_source(',
           'source = sign_extend_16(source) & 0xFFFFFFFF',
           'source = source & 0xFFFF',
           'ADDA/SUBA/CMPA.W zero-extend', ('ADDA.w', 'SUBA.w', 'CMPA.w')),
    Mutant('S7', 'sign extension', '_loads.py', 'def _op_movem(',
           'R[index] = sign_extend_16(read(address)) & 0xFFFFFFFF',
           'R[index] = read(address)',
           'MOVEM.W loads zero-extended', ('MOVEM.w',)),
    Mutant('S8', 'sign extension', '_ea.py', 'if kind == ABSW:',
           'return sign_extend_16(self._extension()) & 0xFFFFFFFF',
           'return self._extension()',
           '(xxx).W not sign-extended', ADDRESSING),
    Mutant('S9', 'sign extension', '_control.py', 'def _branch_target(',
           'return (base + sign_extend_8(displacement)) & 0xFFFFFFFF',
           'return (base + displacement) & 0xFFFFFFFF',
           'Bcc byte displacement unsigned', ('Bcc', 'BSR')),
    Mutant('S10', 'sign extension', '_control.py', 'def _op_dbcc(',
           'sign_extend_16(self.irc)',
           'self.irc',
           'DBcc displacement unsigned', ('DBcc',)),
    Mutant('S11', 'sign extension', '_loads.py', 'def _op_ext(',
           'value = sign_extend_16(self.R[register]) & 0xFFFFFFFF',
           'value = sign_extend_8(self.R[register]) & 0xFFFFFFFF',
           'EXT.L extends the byte', ('EXT.l',)),
    Mutant('S12', 'sign extension', '_loads.py', 'def _op_moveq(',
           'value = sign_extend_8(opcode) & 0xFFFFFFFF',
           'value = opcode & 0xFF',
           'MOVEQ zero-extends', ('MOVE.q',)),
    Mutant('S13', 'sign extension', '_loads.py', 'def _op_link(',
           'displacement = sign_extend_16(self._extension())',
           'displacement = self._extension()',
           'LINK displacement unsigned', ('LINK',)),
    # -- word/long masking -----------------------------------------------------
    Mutant('M1', 'masking', '_ea.py', 'def _write_register(',
           'self.R[register] = (self.R[register] & ~mask & 0xFFFFFFFF) | (value & mask)',
           'self.R[register] = value & mask',
           "byte/word writes clear Dn's upper bits", ('ADD.b', 'MOVE.b', 'MOVE.w', 'AND.w')),
    Mutant('M2', 'masking', '_alu.py', 'def _add(',
           'return result & MASK[size]',
           'return result',
           'ADD result unmasked', ARITH),
    Mutant('M3', 'masking', '_alu.py', 'an = 8 + register',
           'self.R[an] = (self.R[an] + sign * data) & 0xFFFFFFFF',
           'self.R[an] = self.R[an] + sign * data',
           'ADDQ/SUBQ #,An unmasked', ('ADD.l', 'SUB.w')),
    Mutant('M4', 'masking', '_alu.py', 'def _op_suba(',
           'self.R[an] = (self.R[an] - source) & 0xFFFFFFFF',
           'self.R[an] = self.R[an] - source',
           'SUBA unmasked', ('SUBA.w', 'SUBA.l')),
    Mutant('M5', 'masking', '_core.py', 'def _read_word(',
           'return self._read_data_word(address & MASK24)',
           'return self._read_data_word(address & 0xFFFFFFFF)',
           'word reads drive all 32 address bits', ('MOVE.w', 'ADD.w', 'CMP.w')),
    Mutant('M6', 'masking', '_core.py', 'def _set_sr(',
           'value &= SR_BITS',
           'value &= 0xFFFF',
           'SR keeps its unimplemented bits',
           (*PRIVILEGED, 'MOVEtoSR')),
    Mutant('M7', 'masking', '_core.py', 'def _set_ccr(',
           '(value & CCR_BITS)',
           '(value & 0xFF)',
           'CCR keeps bits 7-5', ('MOVEtoCCR', 'ANDItoCCR', 'ORItoCCR', 'EORItoCCR', 'RTR')),
    Mutant('M8', 'masking', '_core.py', 'def _extension(',
           'self._pc = (self._pc + 2) & 0xFFFFFFFF',
           'self._pc = self._pc + 2',
           'the fetch address does not wrap at 32 bits', ('MOVE.l', 'ADD.l')),
    Mutant('M9', 'masking', '_ea.py', 'def _step_size(',
           'return 2 if size == 1 and register == 7 else size',
           'return size',
           '(A7)+ and -(A7) move by 1 for a byte', ('MOVE.b', 'ADD.b', 'CMP.b')),
    Mutant('M10', 'masking', '_alu.py', 'def _op_cmpa(',
           'self._cmp(self.R[8 + ((opcode >> 9) & 7)], source, 4)',
           'self._cmp(self.R[8 + ((opcode >> 9) & 7)], source, 2)',
           'CMPA compares words', ('CMPA.w', 'CMPA.l')),
    # -- BCD correction --------------------------------------------------------
    Mutant('B1', 'BCD', '_bcd.py', 'def decimal_add(',
           '(uncorrected & 0xF) > 9',
           '(uncorrected & 0xF) >= 9',
           'ABCD corrects a low digit of 9', BCD),
    Mutant('B2', 'BCD', '_bcd.py', 'def decimal_add(',
           'uncorrected > 0x99',
           'uncorrected > 0x9F',
           'ABCD high correction threshold', BCD),
    Mutant('B3', 'BCD', '_bcd.py', 'def decimal_subtract(',
           'if binary < 0:\n        correction',
           'if binary < -1:\n        correction',
           'SBCD high correction misses -1', BCD),
    Mutant('B4', 'BCD', '_bcd.py', 'def decimal_subtract(',
           '- extend < 0',
           '- extend <= 0',
           'SBCD low borrow on an equal digit', BCD),
    Mutant('B5', 'BCD', '_bcd.py', 'def _op_nbcd(',
           'decimal_subtract(0, self.R[register] & 0xFF, extend)',
           'decimal_subtract(0, self.R[register] & 0xFF, 0)',
           'NBCD Dn ignores X', ('NBCD',)),
    Mutant('B6', 'BCD', '_bcd.py', 'def _bcd_pair(',
           'source_address = (R[8 + ry] - self._step_size(ry, 1))',
           'source_address = (R[8 + ry] - 1)',
           'ABCD/SBCD -(A7) source moves by 1', ('ABCD', 'SBCD')),
    # -- shifts and rotates ----------------------------------------------------
    Mutant('SH1', 'shift', '_shifts.py', 'def _shift_register(',
           'count = self.R[(opcode >> 9) & 7] & 63',
           'count = self.R[(opcode >> 9) & 7] & 31',
           'register count taken mod 32',
           (*SHIFTS, *ROTATES)),
    Mutant('SH2', 'shift', '_shifts.py', 'if left:\n            carry = (value',
           'result = value >> count if count < bits else 0',
           'result = value >> (count % bits)',
           'LSR by >= width wraps the count', SHIFTS),
    Mutant('SH3', 'shift', '_shifts.py', 'if count >= bits:',
           'carry = 1 if signed < 0 else 0',
           'carry = 0',
           "ASR by >= width clears C and X (the 680x0 corpus's rule)", SHIFTS),
    Mutant('SH4', 'shift', '_shifts.py', '# rox: rotate through X',
           'steps = count % (bits + 1)',
           'steps = count % bits',
           'ROXd rotates mod width', ROTATES),
    Mutant('SH5', 'shift', '_shifts.py', 'if kind == "ro":',
           'steps = count % bits',
           'steps = count % (bits + 1)',
           'ROd rotates mod width + 1', ROTATES),
    Mutant('SH6', 'shift', '_shifts.py', 'def _shift_register(',
           'self._cycles += (4 if size == 4 else 2) + 2 * count',
           'self._cycles += (4 if size == 4 else 2) + 2 * (count & 31)',
           'shift clocks for counts 32-63',
           (*SHIFTS, *ROTATES)),
    Mutant('SH7', 'shift', '_shifts.py', 'if kind == "ls":',
           'carry = (value >> (bits - count)) & 1 if count <= bits else 0',
           'carry = (value >> (bits - count)) & 1 if count < bits else 0',
           'LSL by exactly the width loses C', SHIFTS),
    Mutant('SH8', 'shift', '_shifts.py', 'def _shift_memory(',
           'shift(kind, bool(opcode & 0x0100), value, 1, 2, x)',
           'shift(kind, bool(opcode & 0x0100), value, 2, 2, x)',
           'memory shifts by 2', ('ASL.w', 'LSR.w', 'ROL.w', 'ROXR.w')),
    Mutant('SH9', 'shift', '_shifts.py', 'def _shift_register(',
           'kind, bool(opcode & 0x0100), self.R[register] & MASK[size], count, size, x',
           'kind, bool(opcode & 0x0080), self.R[register] & MASK[size], count, size, x',
           'direction from the wrong bit',
           (*SHIFTS, *ROTATES)),
    # -- division --------------------------------------------------------------
    Mutant('D1', 'division', '_alu.py', 'def _op_divu(',
           'self.R[dn] = (remainder << 16) | quotient',
           'self.R[dn] = (quotient << 16) | remainder',
           'DIVU swaps quotient and remainder', DIVIDE),
    Mutant('D2', 'division', '_alu.py', 'def _op_divs(',
           'remainder = dividend - quotient * divisor',
           'remainder = abs(dividend) - abs(quotient * divisor)',
           'DIVS remainder always positive', DIVIDE),
    Mutant('D3', 'division', '_alu.py', 'def _op_divs(',
           'quotient = abs(dividend) // abs(divisor)\n'
           '        if (dividend < 0) != (divisor < 0):\n            quotient = -quotient',
           'quotient = dividend // divisor',
           'DIVS rounds toward minus infinity', DIVIDE),
    Mutant('D4', 'division', '_system.py', 'def _divide_by_zero(',
           'self._exception(VECTOR_ZERO_DIVIDE, self._pc - 2, idle=8, by_instruction=True)',
           'self._exception(VECTOR_ZERO_DIVIDE, self._pc - 4, idle=8, by_instruction=True)',
           "divide by zero stacks the instruction's own address", DIVIDE),
    Mutant('D5', 'division', '_alu.py', 'def divide_unsigned_clocks(',
           'return 10',
           'return 12',
           'DIVU overflow clocks', DIVIDE),
    Mutant('D6', 'division', '_alu.py', 'def divide_signed_clocks(',
           'if dividend < 0:\n        half_clocks += 1',
           'if dividend < 0:\n        half_clocks += 2',
           'DIVS negative-dividend clocks', DIVIDE),
    Mutant('D7', 'division', '_alu.py', 'def _op_divu(',
           'if source == 0:',
           'if source == 0 and dividend:',
           'DIVU of 0 by 0 does not trap', DIVIDE),
    Mutant('D8', 'division', '_alu.py', 'def divide_unsigned_clocks(',
           'for _ in range(15):',
           'for _ in range(16):',
           'DIVU clock loop one step long', DIVIDE),
    Mutant('D9', 'division', '_system.py', 'def _divide_by_zero(',
           'idle=8',
           'idle=4',
           'divide-by-zero entry clocks', DIVIDE),
    Mutant('D10', 'division', '_system.py', 'def _divide_by_zero(',
           'if signed:\n            ccr |= Z',
           'if signed:\n            ccr |= N',
           'DIVS by zero flags (undefined in PRM; WinUAE T2)', DIVIDE),
    # -- effective-address calculation -----------------------------------------
    Mutant('E1', 'effective address', '_ea.py', 'if kind == DISP:',
           'return (R[8 + register] + sign_extend_16(self._extension())) & 0xFFFFFFFF',
           'return (R[register] + sign_extend_16(self._extension())) & 0xFFFFFFFF',
           '(d16,An) adds Dn', ADDRESSING),
    Mutant('E2', 'effective address', '_ea.py', 'def _index(',
           'if not extension & 0x0800:',
           'if extension & 0x0800:',
           'index size bit inverted', ADDRESSING),
    Mutant('E3', 'effective address', '_ea.py', 'def _index(',
           'index = self.R[extension >> 12]',
           'index = self.R[(extension >> 12) & 7]',
           'index register is always a data register', ADDRESSING),
    Mutant('E4', 'effective address', '_ea.py', 'if kind == PCDISP:',
           'base = self._pc - 2',
           'base = self._pc',
           '(d16,PC) base two bytes late', ADDRESSING),
    Mutant('E5', 'effective address', '_ea.py', 'if kind == PREDEC:',
           'R[8 + register] = address\n            return address',
           'return address',
           '-(An) does not write An back', ADDRESSING),
    Mutant('E6', 'effective address', '_ea.py', 'if kind == POSTINC:',
           'R[8 + register] = (address + self._step_size(register, size)) & 0xFFFFFFFF',
           'R[8 + register] = address',
           '(An)+ does not step', ('ADD.w', 'CMP.b', 'TST.w')),
    Mutant('E7', 'effective address', '_ea.py', 'if kind == ABSL:',
           'return ((high << 16) | self._extension()) & 0xFFFFFFFF',
           'return ((high << 8) | self._extension()) & 0xFFFFFFFF',
           '(xxx).L high word shifted 8', ADDRESSING),
    Mutant('E8', 'effective address', '_control.py', 'def _control_address(',
           'return (R[8 + register] + sign_extend_16(self.irc)) & 0xFFFFFFFF',
           'return (R[8 + register] + sign_extend_16(self.ir)) & 0xFFFFFFFF',
           'JMP/JSR (d16,An) displacement from IR', ('JMP', 'JSR', 'LEA', 'PEA')),
    Mutant('E9', 'effective address', '_control.py', 'if kind == PCDISP:',
           'return (self._pc - 2 + sign_extend_16(self.irc)) & 0xFFFFFFFF',
           'return (self._pc + sign_extend_16(self.irc)) & 0xFFFFFFFF',
           'JMP/JSR (d16,PC) base two late', ('JMP', 'JSR', 'LEA', 'PEA')),
    Mutant('E10', 'effective address', '_loads.py', 'def _op_move(',
           'register = (opcode >> 9) & 7',
           'register = (opcode >> 9) & 3',
           'MOVE destination register loses bit 2', ('MOVE.b', 'MOVE.w', 'MOVE.l')),
    Mutant('E11', 'effective address', '_ea.py', 'def _index(',
           '(base + index + sign_extend_8(extension))',
           '(base + index + (extension & 0xFF))',
           'index displacement unsigned', ADDRESSING),
    Mutant('E12', 'effective address', '_loads.py', 'if opcode & 0x80:',
           'address += 2',
           'address += 1',
           'MOVEP writes adjacent bytes', ('MOVEP.w', 'MOVEP.l')),
    # -- stacked PC and frame contents -----------------------------------------
    Mutant('P1', 'frame', '_core.py', 'def _exception(',
           'self._write_word(sp + 2, pc >> 16)',
           'self._write_word(sp + 2, pc)',
           'group 1/2 frame: PC high word written as the low', EXCEPTIONS),
    Mutant('P2', 'frame', '_core.py', 'def _exception(',
           'self._write_word(sp, saved)',
           'self._write_word(sp, self.SR)',
           'group 1/2 frame stacks the new SR', EXCEPTIONS),
    Mutant('P3', 'frame', '_system.py', 'def _op_trap(',
           'self._pc - 2, by_instruction=True)',
           'self._pc - 4, by_instruction=True)',
           'TRAP stacks its own address', ('TRAP',)),
    Mutant('P4', 'frame', '_system.py', 'def _not_executed(',
           'self._exception(vector, self._pc - 4)',
           'self._exception(vector, self._pc - 2)',
           'illegal/privilege stack the next word', ('ILLEGAL_LINEA', 'MOVEtoSR', 'RTE')),
    Mutant('P5', 'frame', '_system.py', 'if value > bound:',
           'self._exception(VECTOR_CHK, self._pc - 2, idle=8, by_instruction=True)',
           'self._exception(VECTOR_CHK, self._pc, idle=8, by_instruction=True)',
           'CHK stacks two bytes late', ('CHK',)),
    Mutant('P6', 'frame', '_core.py', 'information = (',
           '(0 if fault.write else 0x10)',
           '(0x10 if fault.write else 0)',
           'group 0 R/W inverted', ('MOVE.w', 'ADD.l')),
    Mutant('P7', 'frame', '_core.py', 'information = (',
           '(0x08 if self._processing_exception else 0)',
           '0',
           'group 0 I/N never set',
           ('TRAP', 'TRAPV', 'CHK', 'ILLEGAL_LINEA', 'ILLEGAL_LINEF', 'MOVE.w')),
    Mutant('P8', 'frame', '_core.py', 'information = (',
           '(self._opcode & 0xFFE0)',
           '0',
           'group 0 undefined bits zero (UM: undefined; corpus pins IR)', ('MOVE.w', 'ADD.l')),
    Mutant('P9', 'frame', '_core.py', 'self._write_word(sp + 8, saved)',
           'self._write_word(sp + 4, fault.address)',
           'self._write_word(sp + 4, fault.address >> 16)',
           'group 0 access address low word wrong', ('MOVE.w', 'ADD.l')),
    Mutant('P10', 'frame', '_core.py', 'self._write_word(sp + 10, pc >> 16)',
           'self._write_word(sp + 6, self._opcode)',
           'self._write_word(sp + 6, self.ir)',
           'group 0 frame IR from the queue, not the decoder', ('MOVE.w', 'MOVE.l', 'ADD.l')),
    Mutant('P11', 'frame', 'cpu.py', 'self._trace_pending = False\n                self._opcode',
           'self._exception(VECTOR_TRACE, self._next_pc())',
           'self._exception(VECTOR_TRACE, self._pc)',
           'trace stacks the prefetch address', ('NOP',)),
    Mutant('P12', 'frame', 'cpu.py', 'def _interrupt(',
           'pc = self._next_pc()',
           'pc = self._pc',
           'interrupt stacks the prefetch address', ('NOP',)),
    Mutant('P13', 'frame', '_control.py', 'def _op_bsr(',
           'returns = self._pc if not opcode & 0xFF else self._pc - 2',
           'returns = self._pc - 2 if not opcode & 0xFF else self._pc',
           'BSR return address swapped between forms', ('BSR',)),
    Mutant('P14', 'frame', '_control.py', 'def _op_jsr(',
           'returns = self._pc - 2 if kind == IND else self._pc',
           'returns = self._pc',
           'JSR (An) return address two late', ('JSR',)),
    Mutant('P15', 'frame', '_core.py', 'def _commit_pc(',
           'self._fault_pc = self._pc',
           'pass',
           'the microcode PC is never brought up to date', ('MOVE.w', 'ADD.w', 'LEA')),
    Mutant('P16', 'frame', '_core.py', 'self._write_word(sp + 2, fault.address >> 16)',
           'target = self._read_vector(fault.vector)',
           'target = self._read_vector(3)',
           'bus errors vector through the address-error vector', ('MOVE.w',)),
    Mutant('P17', 'frame', '_system.py', 'def _op_rte(',
           'pc = (high << 16) | self._read_word(sp + 4)',
           'pc = (self._read_word(sp + 4) << 16) | high',
           'RTE swaps the PC halves', ('RTE',)),
    # -- supervisor bit and stack pointers -------------------------------------
    Mutant('SP1', 'supervisor', '_core.py', 'def _set_sr(',
           'if (value ^ self.SR) & S:',
           'if False:',
           'S changes never swap the stack pointers',
           (*PRIVILEGED, *EXCEPTIONS)),
    Mutant('SP2', 'supervisor', '_core.py', 'def _fc(',
           'if self.SR & S:',
           'if not self.SR & S:',
           'function codes of the other mode', ('NOP', 'MOVE.w')),
    Mutant('SP3', 'supervisor', '_core.py', 'def _enter_supervisor(',
           'self._set_sr((saved | S) & ~T)',
           'self._set_sr(saved & ~T)',
           'exceptions do not enter supervisor mode',
           ('TRAP', 'TRAPV', 'CHK', 'ILLEGAL_LINEA', 'ILLEGAL_LINEF', 'MOVEtoSR')),
    Mutant('SP4', 'supervisor', '_core.py', 'def _enter_supervisor(',
           'self._set_sr((saved | S) & ~T)',
           'self._set_sr(saved | S)',
           'exceptions keep T', EXCEPTIONS),
    Mutant('SP5', 'supervisor', '_system.py', 'def _op_move_to_sr(',
           'if not self.SR & S:',
           'if False:',
           'MOVE to SR not privileged', ('MOVEtoSR',)),
    Mutant('SP6', 'supervisor', '_system.py', 'def _op_move_usp(',
           'if opcode & 8:',
           'if not opcode & 8:',
           'MOVE USP direction inverted', ('MOVEtoUSP', 'MOVEfromUSP')),
    Mutant('SP7', 'supervisor', '_core.py', 'def usp(self)',
           'return self._other_sp if self.SR & S else self.R[15]',
           'return self.R[15]',
           'usp reads A7 in supervisor mode', ('MOVEtoUSP', 'MOVEfromUSP', 'RTE')),
    Mutant('SP8', 'supervisor', '_system.py', 'def _op_rte(',
           'self._set_sr(status)',
           'self.SR = status & 0xA71F',
           'RTE to user mode keeps the SSP in A7', ('RTE',)),
    Mutant('SP9', 'supervisor', '_system.py', 'def _op_stop(',
           'if not self.SR & S:',
           'if False:',
           'STOP not privileged', ('STOP',)),
    Mutant('SP10', 'supervisor', 'cpu.py', 'def _interrupt(',
           'self._set_sr(((saved | S) & ~T & ~IPL_MASK) | (level << 8))',
           'self._set_sr((saved | S) & ~T)',
           'interrupt entry does not raise the mask', ('NOP',)),
    Mutant('SP11', 'supervisor', 'cpu.py', 'elif level and (',
           'level > (self.SR >> 8) & 7',
           'level >= (self.SR >> 8) & 7',
           'an interrupt at the mask level is taken', ('NOP',)),
    Mutant('SP12', 'supervisor', 'cpu.py', 'def set_ipl(',
           'if level == 7 and self.ipl != 7:',
           'if level == 7:',
           'level 7 retaken while held', ('NOP',)),
    # -- prefetch queue --------------------------------------------------------
    Mutant('Q1', 'prefetch', '_core.py', 'def _prefetch(self)',
           'self.ir = self._opcode = self.irc',
           'self.ir = self.irc',
           'the closing prefetch does not hand the next opcode to the decoder',
           ('MOVE.w', 'ADD.w', 'NOP')),
    Mutant('Q2', 'prefetch', '_core.py', 'def _extension(',
           'self._pc = (self._pc + 2) & 0xFFFFFFFF\n        return value',
           'return value',
           'taking an extension word does not advance the fetch address', ('MOVE.w', 'ADDA.l')),
    Mutant('Q3', 'prefetch', '_core.py', 'def _jump(',
           'self._pc = (target + 2) & 0xFFFFFFFF',
           'self._pc = (target + 4) & 0xFFFFFFFF',
           'a jump skips a word', ('JMP', 'RTS', 'Bcc')),
    Mutant('Q4', 'prefetch', '_core.py', 'def _prefetch_before_write(',
           'self.ir = self.irc\n',
           'pass\n',
           'a write-last prefetch leaves IR stale', ('MOVE.l', 'PEA')),
    Mutant('Q5', 'prefetch', '_control.py', 'def _op_bcc(',
           'if not opcode & 0xFF:\n            self._extension()',
           'if False:\n            pass',
           'Bcc not taken does not skip its displacement word', ('Bcc',)),
    Mutant('Q6', 'prefetch', 'cpu.py', 'def _next_pc(',
           'return self._pc if self.stopped else (self._pc - 4) & 0xFFFFFFFF',
           'return (self._pc - 4) & 0xFFFFFFFF',
           'a stopped CPU resumes at the STOP', ('STOP',)),
    Mutant('Q7', 'prefetch', '_system.py', 'def _refill_after_status(',
           'self._jump(self._pc - 2)',
           'self._jump(self._pc)',
           'after an SR write the queue refills a word late', ('MOVEtoSR', 'ANDItoCCR')),
    Mutant('Q8', 'prefetch', '_control.py', 'def _op_dbcc(',
           'self._extension()  # expired',
           'pass  # expired',
           'DBcc expiry does not skip the displacement word', ('DBcc',)),
    Mutant('Q9', 'prefetch', '_loads.py', 'def _op_movem(',
           'read(address)  # one word past the last register (T3)',
           'pass',
           'MOVEM loads without the extra read', ('MOVEM.w', 'MOVEM.l')),
    Mutant('Q10', 'prefetch', 'cpu.py', 'def set_pc(',
           'self._pc = (address + 4) & 0xFFFFFFFF',
           'self._pc = (address + 2) & 0xFFFFFFFF',
           'set_pc leaves the fetch address one word short', ('NOP',)),
    # -- cycle counts ----------------------------------------------------------
    Mutant('CY1', 'clocks', '_alu.py', 'def multiply_unsigned_clocks(',
           'bin(source & 0xFFFF).count("1")',
           'bin(source & 0x7FFF).count("1")',
           'MULU clocks ignore bit 15', MULTIPLY),
    Mutant('CY2', 'clocks', '_alu.py', 'def multiply_signed_clocks(',
           'pattern = (source & 0xFFFF) << 1',
           'pattern = source & 0xFFFF',
           'MULS clocks without the appended 0', MULTIPLY),
    Mutant('CY3', 'clocks', '_control.py', 'def _op_bcc(',
           'self._cycles += 2\n            self._jump(',
           'self._cycles += 4\n            self._jump(',
           'Bcc taken 12 clocks', ('Bcc',)),
    Mutant('CY4', 'clocks', '_shifts.py', 'def _shift_register(',
           '(4 if size == 4 else 2)',
           '(2 if size == 4 else 2)',
           'long shifts 2 clocks short', SHIFTS),
    Mutant('CY5', 'clocks', '_alu.py', 'def _to_data_register(',
           'self._cycles += 4 if kind in (DN, AN, IMM) else 2',
           'self._cycles += 2',
           'long ops to Dn from a register 2 clocks short', ARITH),
    Mutant('CY6', 'clocks', '_bits.py', 'def _bit_operation(',
           'self._cycles += 4 if operation == CLEAR else 2',
           'self._cycles += 2',
           'BCLR Dn 2 clocks short', ('BCLR',)),
    Mutant('CY7', 'clocks', '_bits.py', 'def _bit_operation(',
           'if number >= 16:',
           'if number > 16:',
           'bit 16 costs the low-bit time', ('BCHG', 'BSET', 'BCLR')),
    Mutant('CY8', 'clocks', '_core.py', 'def _group_zero(',
           'self._cycles += 4 + 4 + 2 + 2',
           'self._cycles += 4 + 4 + 2',
           'address error entry 2 clocks short', ('MOVE.w',)),
    Mutant('CY9', 'clocks', '_core.py', 'def _exception(',
           'idle: int = 4,',
           'idle: int = 6,',
           'group 1/2 entry 2 clocks long', EXCEPTIONS),
    Mutant('CY10', 'clocks', 'cpu.py', 'def _e_clock_wait(',
           'if phase < 7 else',
           'if phase < 8 else',
           'E-clock wait boundary moved', ('NOP',)),
    Mutant('CY11', 'clocks', '_system.py', 'def _op_reset(',
           'self._cycles += 128',
           'self._cycles += 124',
           'RESET 4 clocks short', ('RESET',)),
    Mutant('CY12', 'clocks', '_control.py', 'def _op_dbcc(',
           'self._cycles += 2\n        target',
           'self._cycles += 4\n        target',
           'DBcc condition-false 2 clocks long', ('DBcc',)),
    Mutant('CY13', 'clocks', '_system.py', 'else:\n            self._cycles += 6',
           'self._cycles += 6',
           'self._cycles += 4',
           'CHK in range 2 clocks short', ('CHK',)),
    Mutant('CY14', 'clocks', '_alu.py', '# An: the whole register',
           'self._cycles += 4\n',
           'self._cycles += 0 if size == 2 and sign == 1 else 4\n',
           'ADDQ.W #,An in 4 clocks, as UM Table 8-5 prints', ('ADD.w', 'ADD.l')),
    Mutant('CY15', 'clocks', '_system.py', 'elif value < 0:',
           'idle = 8 if (bound - value) & 0x8000 else 10',
           'idle = 10',
           "CHK negative always 10 idle clocks (WinUAE's rule)", ('CHK',)),
    Mutant('CY16', 'clocks', '_loads.py', 'def _op_lea(',
           'if kind in (INDEX, PCINDEX):\n            self._cycles += 2',
           'if kind in (INDEX, PCINDEX):\n            self._cycles += 0',
           'LEA indexed 2 short', ('LEA',)),
    Mutant('CY17', 'clocks', '_core.py', 'def _jump_idle(',
           'self._cycles += 2',
           'pass',
           'exception refill without its 2 idle clocks', EXCEPTIONS),
    # -- conditions, results and the rest --------------------------------------
    Mutant('O1', 'conditions', '_flags.py', 'def _test(',
           'n == v,  # GE',
           'n or v,  # GE',
           'GE wrong', ('Bcc', 'Scc', 'DBcc')),
    Mutant('O2', 'conditions', '_flags.py', 'def _test(',
           'not c and not z,  # HI',
           'not c,  # HI',
           'HI ignores Z', ('Bcc', 'Scc', 'DBcc')),
    Mutant('O3', 'results', '_control.py', 'def _op_scc(',
           'value = 0xFF if',
           'value = 0x80 if',
           'Scc sets $80', ('Scc',)),
    Mutant('O4', 'results', '_alu.py', 'def _op_tas(',
           'value | 0x80)',
           'value | 0x40)',
           'TAS sets bit 6', ('TAS',)),
    Mutant('O5', 'results', '_loads.py', 'def _op_exg(',
           'elif mode == 0x09:',
           'elif mode == 0x11:',
           'EXG An,An exchanges Dn with An', ('EXG',)),
    Mutant('O6', 'results', '_loads.py',
           'if kind == PREDEC:\n            address = R[8 + register]',
           'value = R[15 - bit]',
           'value = R[bit]',
           'MOVEM -(An) stores in the wrong order', ('MOVEM.w', 'MOVEM.l')),
    Mutant('O7', 'results', '_alu.py', 'def _op_cmpm(',
           'R[ax] = (address + (self._step_size(ax - 8, size) if size != 4 else 4))',
           'R[ax] = (address + size)',
           'CMPM (A7)+ byte steps by 1', ('CMP.b', 'CMP.w')),
    Mutant('O8', 'results', '_loads.py', 'def _op_link(',
           'value = self.R[an]  # LINK A7',
           'value = (self.R[an] - 4) & 0xFFFFFFFF if an == 15 else self.R[an]  # LINK A7',
           "LINK A7 pushes the decremented SP (CLK's rule)", ('LINK',)),
    Mutant('O9', 'results', '_loads.py', 'def _op_unlk(',
           'self.R[15] = (address + 4) & 0xFFFFFFFF\n        self.R[an] = value',
           'self.R[an] = value\n        self.R[15] = (address + 4) & 0xFFFFFFFF',
           'UNLK A7 order', ('UNLINK',)),
    Mutant('O10', 'results', '_system.py', 'def _op_trapv(',
           'if not self.SR & V:',
           'if not self.SR & 1:',
           'TRAPV tests C', ('TRAPV',)),
    Mutant('O11', 'results', '_bits.py', 'def _bit_operation(',
           'number &= 7',
           'number &= 15',
           'memory bit number mod 16', ('BTST', 'BCHG', 'BCLR', 'BSET')),
    Mutant('O12', 'results', '_control.py', 'def _op_rtr(',
           'self._set_ccr(ccr)',
           'self._set_sr(ccr)',
           'RTR restores the whole SR', ('RTR',)),
    Mutant('O13', 'results', '_system.py', 'def _op_move_to_ccr(',
           'self._write_ccr(value)',
           'self._write_status(value)',
           'MOVE to CCR writes the whole SR', ('MOVEtoCCR',)),
    Mutant('O14', 'results', '_system.py', 'def _not_executed(',
           'self._untraced = True',
           'pass',
           'an illegal or privileged instruction is traced (the bug fixed at 8760315)',
           ('ILLEGAL_LINEA',)),
    Mutant('O15', 'results', '_loads.py', 'def _op_movep(',
           'self._write_register(dn, count, value)',
           'self.R[dn] = value',
           "MOVEP.W load clears Dn's upper word", ('MOVEP.w',)),
    Mutant('O16', 'results', '_alu.py', 'def _clear(',
           'self.SR = (self.SR & (0xFF00 | X)) | Z',
           'self.SR = (self.SR & 0xFF00) | Z',
           'CLR clears X', ('CLR.b', 'CLR.w', 'CLR.l')),
)
# fmt: on

AREAS = sorted({mutant.area for mutant in MUTANTS})

#: Survivors shown, after the run, to be equivalent to the core on every
#: observable output, with the argument.  They stay in the population and
#: count as survivors in the raw score; the report gives both scores.
EQUIVALENT = {
    "N7": "EXT.W's result is the sign-extended byte, so its bit 15 equals bit 7 and it "
    "is zero exactly when the byte is: N and Z of the byte are N and Z of the word "
    "(checked for all 256 bytes and both X values).",
    "M8": "every use of the fetch address masks it (the bus to 24 bits; PC, "
    "capture_state, stacked and pushed PCs, and every PC-relative address to 32), so "
    "only the private _pc differs, and only after an extension word is taken at "
    "$FFFFFFFE; six programs straddling the wrap, one taking an address error there, "
    "gave identical registers, PC, captured state, memory and bus accesses.",
}


# -- applying a mutant -----------------------------------------------------------


def mutated_source(mutant: Mutant) -> str:
    """The source of ``mutant.file`` with the mutation applied; raises if it is ambiguous."""
    text = (SOURCE / mutant.file).read_text()
    if text.count(mutant.anchor) != 1:
        raise ValueError(f"{mutant.id}: anchor occurs {text.count(mutant.anchor)} times")
    start = text.index(mutant.anchor)
    at = text.find(mutant.old, start)
    if at < 0:
        raise ValueError(f"{mutant.id}: {mutant.old!r} not found after the anchor")
    return text[:at] + mutant.new + text[at + len(mutant.old) :]


def build_tree(mutant: Mutant | None, work: Path) -> Path:
    """Copy src/m68000_python into ``work`` and apply ``mutant``; return the parent to import."""
    tree = work / "src"
    if tree.exists():
        shutil.rmtree(tree)
    shutil.copytree(SOURCE, tree / "m68000_python", ignore=shutil.ignore_patterns("__pycache__"))
    if mutant is not None:
        (tree / "m68000_python" / mutant.file).write_text(mutated_source(mutant))
    return tree


def source_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(SOURCE.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


# -- the child: run the chosen subset against one tree --------------------------------


def child_detect(tree: str, stems: list[str]) -> dict:
    """Run in the child: the 680x0 files, returning each file's disagreeing case names."""
    sys.path[:0] = [tree, str(TESTS)]
    import m68000_python

    loaded = Path(m68000_python.__file__).resolve()
    if not str(loaded).startswith(str(Path(tree).resolve())):
        return {"error": f"imported {loaded}, not the mutant tree"}
    from corpus import read_680x0
    from harness_680x0 import run_case_680x0

    disagreeing: dict[str, list[str]] = {}
    for stem in stems:
        names = []
        for case in read_680x0(HARTE_VECTORS / f"{stem}.json.gz"):
            try:
                differences = run_case_680x0(case)[0]
            except Exception as error:
                differences = [repr(error)]
            if differences:
                names.append(case.name)
        disagreeing[stem] = names
    return {"disagreeing": disagreeing}


def child(tree: str, corpus: list[str], tests: list[str]) -> dict:
    """Run in the child process: import the tree, run the corpus files and tests."""
    sys.path[:0] = [tree, str(TESTS)]
    import m68000_python

    loaded = Path(m68000_python.__file__).resolve()
    if not str(loaded).startswith(str(Path(tree).resolve())):
        return {"error": f"imported {loaded}, not the mutant tree"}

    result: dict = {"corpus": {}, "tests": {}, "errors": []}
    try:
        from corpus import read_m68000
        from harness import run_case
    except Exception as error:  # a mutant that breaks import is killed by everything
        result["errors"].append(f"import: {type(error).__name__}: {error}")
        return result
    for stem in corpus:
        path = VECTORS / f"{stem}.json.bin"
        for case in read_m68000(path):
            try:
                differences, _ = run_case(case)
            except Exception as error:
                differences = [f"{type(error).__name__}: {error}"]
            if differences:
                result["corpus"][stem] = f"{case.name}: {differences[0]}"
                break

    if tests:
        import pytest

        class Collector:
            def __init__(self) -> None:
                self.failed: list[str] = []

            def pytest_runtest_logreport(self, report) -> None:
                if report.failed:
                    self.failed.append(report.nodeid)

            def pytest_collectreport(self, report) -> None:
                if report.failed:
                    self.failed.append(f"collect:{report.nodeid}")

        collector = Collector()
        arguments = [str(TESTS / name) for name in tests]
        arguments += ["-q", "-p", "no:cacheprovider", "-o", "pythonpath=", "--rootdir", str(ROOT)]
        with open(os.devnull, "w") as quiet:
            saved = sys.stdout
            sys.stdout = quiet
            try:
                pytest.main(arguments, plugins=[collector])
            finally:
                sys.stdout = saved
        for nodeid in collector.failed:
            module = nodeid.split("::")[0].split("/")[-1].removeprefix("collect:")
            result["tests"].setdefault(module, []).append(nodeid)
    return result


def run_one(mutant: Mutant | None, corpus: list[str], tests: list[str], work: Path,
            python: str) -> dict:  # fmt: skip
    """Build the tree for ``mutant`` in ``work`` and run the subset in a child process."""
    tree = build_tree(mutant, work)
    spec = json.dumps({"tree": str(tree), "corpus": corpus, "tests": tests})
    command = ["nice", "-n", "10", python, str(Path(__file__).resolve()), "_child", spec]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=TIMEOUT, cwd=str(work), check=False
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "seconds": TIMEOUT}
    seconds = round(time.perf_counter() - started, 1)
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    if not lines:
        return {"status": "crashed", "seconds": seconds, "stderr": completed.stderr[-2000:]}
    outcome = json.loads(lines[-1])
    if "error" in outcome:
        raise RuntimeError(f"{mutant and mutant.id}: {outcome['error']}")
    killed = bool(outcome["corpus"] or outcome["tests"] or outcome["errors"])
    return {"status": "killed" if killed else "survived", "seconds": seconds, **outcome}


# -- the two phases ---------------------------------------------------------------------


def all_stems() -> list[str]:
    return sorted(path.name.removesuffix(".json.bin") for path in VECTORS.glob("*.json.bin"))


def run_phase(mutants: list[Mutant], phase: str, jobs: int, python: str, work_root: Path,
              baseline_first: bool = True) -> dict[str, dict]:  # fmt: skip
    results: dict[str, dict] = {}

    def subset(mutant: Mutant) -> tuple[list[str], list[str]]:
        corpus = all_stems() if phase == "full" else list(mutant.corpus)
        return corpus, list(FAST_TESTS)

    if baseline_first:
        # The unmutated copy must pass everything a mutant will run, or a
        # "kill" would mean nothing.
        corpus = sorted({stem for mutant in mutants for stem in subset(mutant)[0]})
        baseline = run_one(None, corpus, list(FAST_TESTS), work_root / "baseline", python)
        if baseline["status"] != "survived":
            raise RuntimeError(f"the unmutated tree fails its own subset: {baseline}")
        print(
            f"baseline: unmutated copy passes {len(corpus)} corpus files and "
            f"{len(FAST_TESTS)} test modules ({baseline['seconds']} s)",
            flush=True,
        )

    def work(mutant: Mutant) -> tuple[str, dict]:
        corpus, tests = subset(mutant)
        outcome = run_one(mutant, corpus, tests, work_root / mutant.id, python)
        outcome["subset"] = {
            "corpus": corpus if phase != "full" else "all 127 files",
            "tests": tests,
        }
        return mutant.id, outcome

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for mutant_id, outcome in pool.map(work, mutants):
            results[mutant_id] = outcome
            print(f"{mutant_id:5} {outcome['status']:9} {outcome.get('seconds', '')}", flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    run = sub.add_parser("run")
    run.add_argument("--jobs", type=int, default=4)
    run.add_argument("--only", nargs="*", default=None, help="mutant ids")
    run.add_argument("--out", default="mutation-results.json")
    run.add_argument("--python", default=str(ROOT / ".venv-pypy" / "bin" / "python"))
    run.add_argument("--work", default=None, help="scratch directory (default: a temp dir)")
    for name in ("escalate", "recheck", "detect"):
        later = sub.add_parser(name)
        later.add_argument("results")
        later.add_argument("--jobs", type=int, default=3)
        later.add_argument("--python", default=str(ROOT / ".venv-pypy" / "bin" / "python"))
        later.add_argument("--work", default=None)
    report = sub.add_parser("report")
    report.add_argument("results")
    child_parser = sub.add_parser("_child")
    child_parser.add_argument("spec")
    args = parser.parse_args()

    if args.command == "_child":
        spec = json.loads(args.spec)
        if "detect" in spec:
            print(json.dumps(child_detect(spec["tree"], spec["detect"])))
        else:
            print(json.dumps(child(spec["tree"], spec["corpus"], spec["tests"])))
        return 0
    if args.command == "list":
        for mutant in MUTANTS:
            mutated_source(mutant)  # validates the anchor and the replacement
            print(f"{mutant.id:5} {mutant.area:18} {mutant.file:12} {mutant.what}")
        print(f"{len(MUTANTS)} mutants in {len(AREAS)} areas")
        return 0
    if args.command == "report":
        return print_report(json.loads(Path(args.results).read_text()))

    for mutant in MUTANTS:
        mutated_source(mutant)
    ids = [mutant.id for mutant in MUTANTS]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate mutant ids")
    before = source_digest()
    scratch = (
        Path(args.work)
        if args.work
        else Path(tempfile.mkdtemp(prefix="m68k-mutants-", dir=_scratch_parent()))
    )
    started = time.perf_counter()
    if args.command == "run":
        chosen = [m for m in MUTANTS if args.only is None or m.id in args.only]
        results = {
            "phase1": run_phase(chosen, "subset", args.jobs, args.python, scratch),
            "python": args.python,
            "src_digest": before,
        }
        out = Path(args.out)
    elif args.command == "escalate":
        out = Path(args.results)
        results = json.loads(out.read_text())
        chosen = [m for m in MUTANTS if m.id in results["phase1"] and needs_escalation(
            results["phase1"][m.id])]  # fmt: skip
        results["phase2"] = run_phase(chosen, "full", args.jobs, args.python, scratch)
    elif args.command == "recheck":
        # After tests were written for the survivors: the survivors of phase
        # 2 against the whole suite as it now stands.
        out = Path(args.results)
        results = json.loads(out.read_text())
        before_recheck = {**results["phase1"], **results.get("phase2", {})}
        chosen = [m for m in MUTANTS if before_recheck.get(m.id, {}).get("status") == "survived"]
        results["phase3"] = run_phase(chosen, "full", args.jobs, args.python, scratch)
    else:
        out = Path(args.results)
        results = json.loads(out.read_text())
        results["detector"] = run_detector(results, args.jobs, args.python, scratch)
    results[f"{args.command}_seconds"] = round(time.perf_counter() - started, 1)
    after = source_digest()
    if after != before:
        raise RuntimeError("src/m68000_python changed during the run")
    out.write_text(json.dumps(results, indent=1, sort_keys=True))
    print(f"wrote {out}; src/ unchanged (sha256 {after[:12]})")
    return 0


def needs_escalation(outcome: dict) -> bool:
    """Phase-1 survivors, and mutants that only the session's new tests killed."""
    if outcome["status"] == "survived":
        return True
    sources = kill_sources(outcome)
    return sources == {"new gap tests"}


def run_detector(results: dict, jobs: int, python: str, work_root: Path) -> dict:
    """Run each final survivor's 680x0 files, and the unmutated core's, case by case."""
    final = {**results["phase1"], **results.get("phase2", {}), **results.get("phase3", {})}
    by_id = {mutant.id: mutant for mutant in MUTANTS}
    survivors = [by_id[i] for i, outcome in final.items() if outcome["status"] == "survived"]
    stems = sorted({stem for m in survivors for stem in m.corpus
                    if (HARTE_VECTORS / f"{stem}.json.gz").exists()})  # fmt: skip

    def detect(mutant: Mutant | None, files: list[str]) -> dict:
        name = mutant.id if mutant else "baseline"
        tree = build_tree(mutant, work_root / f"detect-{name}")
        spec = json.dumps({"tree": str(tree), "detect": files})
        command = ["nice", "-n", "10", python, str(Path(__file__).resolve()), "_child", spec]
        completed = subprocess.run(command, capture_output=True, text=True, check=False,
                                   timeout=3 * TIMEOUT)  # fmt: skip
        lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
        if not lines:
            return {"error": completed.stderr[-2000:]}
        return json.loads(lines[-1])

    baseline = detect(None, stems)["disagreeing"]
    report: dict[str, dict] = {}

    def one(mutant: Mutant) -> tuple[str, dict]:
        files = [stem for stem in mutant.corpus if stem in baseline]
        if not files:
            return mutant.id, {"files": [], "note": "no 680x0 file for this mutant's subset"}
        outcome = detect(mutant, files)["disagreeing"]
        newly = {s: sorted(set(outcome[s]) - set(baseline[s])) for s in files}
        cured = {s: sorted(set(baseline[s]) - set(outcome[s])) for s in files}
        return mutant.id, {
            "files": files,
            "agree_then_disagree": sum(len(v) for v in newly.values()),
            "disagree_then_agree": sum(len(v) for v in cured.values()),
            "examples": [name for names in newly.values() for name in names[:3]],
        }

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for mutant_id, outcome in pool.map(one, survivors):
            report[mutant_id] = outcome
            print(f"{mutant_id:5} {outcome}", flush=True)
    return report


def _scratch_parent() -> str | None:
    candidate = Path("/tmp/claude-1000")
    return str(candidate) if candidate.is_dir() else None


# -- the report -------------------------------------------------------------------------


def kill_sources(outcome: dict) -> set[str]:
    sources = set()
    if outcome.get("corpus"):
        sources.add("gate corpus")
    for module in outcome.get("tests", {}):
        sources.add("new gap tests" if module in NEW_TESTS else "other tests")
    if outcome.get("errors"):
        sources.add("import error")
    if outcome.get("status") == "timeout":
        sources.add("timeout")
    return sources


def print_report(results: dict) -> int:
    phase1 = results["phase1"]
    phase2 = results.get("phase2", {})
    phase3 = results.get("phase3", {})
    by_id = {mutant.id: mutant for mutant in MUTANTS}
    survivor_tests = {"test_mutation_survivors.py"}

    def status(mutant_id: str, *phases: dict) -> str:
        outcome = phase1[mutant_id]["status"]
        for phase in phases:
            if mutant_id in phase:
                outcome = phase[mutant_id]["status"]
        return "survived" if outcome == "survived" else "killed"

    def killed_by(mutant_id: str, allowed) -> bool:
        """Killed in phase 1 or 2 by a source ``allowed`` accepts."""
        for outcome in (phase1.get(mutant_id, {}), phase2.get(mutant_id, {})):
            if outcome.get("status") in ("timeout", "crashed"):
                return True
            if any(allowed(source) for source in kill_sources(outcome)):
                return True
        return False

    def old_suite(mutant_id: str) -> bool:
        return killed_by(mutant_id, lambda source: source != "new gap tests")

    def with_gap_tests(mutant_id: str) -> bool:
        return status(mutant_id, phase2) == "killed"

    def now(mutant_id: str) -> bool:
        return status(mutant_id, phase2, phase3) == "killed"

    columns = [("suite at e3629c1", old_suite), ("+ coverage tests", with_gap_tests)]
    if phase3:
        columns.append(("+ survivor tests", now))
    header = " | ".join(name for name, _ in columns)
    print(f"| Area | Mutants | {header} | Survivors | Equivalent |")
    print("| --- | ---: |" + " ---: |" * len(columns) + " --- | --- |")
    for area in [*AREAS, "all"]:
        ids = [m.id for m in MUTANTS if m.id in phase1 and (area == "all" or m.area == area)]
        if not ids:
            continue
        cells = []
        for _, killed in columns:
            count = sum(killed(i) for i in ids)
            cells.append(f"{count} ({100 * count / len(ids):.0f}%)")
        last = columns[-1][1]
        left = [i for i in ids if not last(i)]
        equivalent = [i for i in left if i in EQUIVALENT]
        label = f"**{area}**" if area == "all" else area
        shown = ", ".join(left) if area != "all" else str(len(left))
        print(f"| {label} | {len(ids)} | {' | '.join(cells)} | {shown or '-'} | "
              f"{', '.join(equivalent) if area != 'all' else len(equivalent)} |")  # fmt: skip
    print()
    total = len(phase1)
    last = columns[-1][1]
    killed_now = sum(last(i) for i in phase1)
    equivalent_left = [i for i in phase1 if not last(i) and i in EQUIVALENT]
    print(f"Score: {killed_now}/{total} = {100 * killed_now / total:.1f}%; excluding the "
          f"{len(equivalent_left)} equivalent mutants, {killed_now}/{total - len(equivalent_left)}"
          f" = {100 * killed_now / (total - len(equivalent_left)):.1f}%.\n")  # fmt: skip

    sources: dict[str, int] = {}
    for mutant_id in phase1:
        combined = kill_sources(phase1[mutant_id]) | kill_sources(phase2.get(mutant_id, {}))
        key = " + ".join(sorted(combined)) or "survived phases 1 and 2"
        sources[key] = sources.get(key, 0) + 1
    print("What killed each mutant in phases 1 and 2 (a mutant can be killed by several):\n")
    for key, count in sorted(sources.items(), key=lambda item: -item[1]):
        print(f"- {key}: {count}")
    print()

    detector = results.get("detector", {})
    print("Every mutant that survived phase 2:\n")
    print("| Id | Area | Mutation | Phase 1 subset | Phase 2 | Phase 3 | 680x0 detector |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for mutant_id in phase1:
        if status(mutant_id, phase2) != "survived":
            continue
        mutant = by_id[mutant_id]
        subset = ", ".join(mutant.corpus) + " + fast tests"
        if mutant_id in phase3:
            third = phase3[mutant_id]
            if third["status"] == "survived":
                after = "survived"
            else:
                modules = sorted(third.get("tests", {}))
                after = "killed by " + (", ".join(modules) or "the gate")
        else:
            after = "not run"
        if mutant_id in EQUIVALENT:
            after += " (equivalent)"
        seen = detector.get(mutant_id)
        if seen is None:
            shown = "not run"
        elif not seen.get("files"):
            shown = "no matching file"
        else:
            shown = (f"{seen['agree_then_disagree']} of its cases newly disagree, "
                     f"{seen['disagree_then_agree']} newly agree")  # fmt: skip
        print(f"| {mutant_id} | {mutant.area} | {mutant.what} (`{mutant.file}`) | {subset} | "
              f"survived | {after} | {shown} |")  # fmt: skip
    print()
    print("Killed only by the session's new tests (the suite at e3629c1 let them through):\n")
    for mutant_id in phase1:
        if old_suite(mutant_id) or not now(mutant_id):
            continue
        mutant = by_id[mutant_id]
        modules = {**phase1[mutant_id].get("tests", {}), **phase2.get(mutant_id, {}).get(
            "tests", {}), **phase3.get(mutant_id, {}).get("tests", {})}  # fmt: skip
        names = sorted({node.split("::")[1].split("[")[0] for nodes in modules.values()
                        for node in nodes if "::" in node})  # fmt: skip
        print(f"- {mutant_id} ({mutant.area}): {mutant.what} -- {', '.join(names)}")
    for mutant_id, reason in EQUIVALENT.items():
        print(f"\nEquivalent, {mutant_id}: {reason}")
    del survivor_tests
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
