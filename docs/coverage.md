# Coverage: what the evidence reaches, and where it stops

"317,500 of 317,500 cases pass" is a count. This is the map behind it: which
of the 68000's encodings the pinned SingleStepTests/m68000 gate executes,
which behaviours it reaches, which lines of the core no case runs -- and,
for what the gate misses, what now covers it and what nothing can cover
without an oracle this repository does not have.

The approach is Aubrey's (2026-09-21): no exhaustive hardware oracle exists
for the 68000 the way ZEXALL-like evidence did for the Z80, so instead of
one authority the verification is a web of independent evidence -- the
microcode-derived gate (T3), the hardware BCD tables (T1), MAME lockstep on
real code (T3), WinUAE's rules read from source (T2), the manuals, and
relations the manuals imply -- and each claim says which strands hold it
up. [Mutation testing](mutation.md) measures how well the web catches a
wrong core.

Everything below is reproducible with `scripts/coverage_report.py`
(commits 689f18f onward):

```text
python scripts/coverage_report.py encodings [--corpus 680x0 | --suite]
python scripts/coverage_report.py paths     [--corpus 680x0 | --suite]
python scripts/coverage_report.py lines     [--corpus 680x0 | --suite]
```

`encodings` reads each case's first word (`initial.prefetch[0]`, the word
the step executes) or, with `--suite`, counts every dispatch while `pytest
tests` runs. `paths` runs every case through a probed subclass of
`M68000CPU` (the core is not modified) against a declared list of
behaviours, so a behaviour nothing reaches shows up as `NEVER` rather than
being assumed covered. `lines` traces `src/m68000_python` with
`sys.settrace`. Runtimes on the shared machine: `paths` over the 317,500
gate cases 7 s on PyPy 7.3.23, over the 1,000,060 680x0 cases 25 s; `lines`
over the gate 14 s on CPython 3.14.4.

## 1. Encodings

Of 65,536 first words the 68000 defines 45,815 (the rest are ILLEGAL, line
A, line F or unassigned).

| | SingleStepTests/m68000 (gate) | SingleStepTests/680x0 (detector) | Whole suite at e3629c1 | Whole suite now |
| --- | ---: | ---: | ---: | ---: |
| Defined words executed | **38,019** | 44,736 | 38,019 | **45,815** |
| Defined words never executed | 7,796 | 1,079 | 7,796 | 0 |
| Undefined words executed | 3,747 (all line A/F) | 0 | 3,747 | 3,751 |

At e3629c1 the hand-written tests (interrupts, tooling, BCD, decoder)
executed no first word the gate did not, so the gate's map was the suite's.
The "before" columns here and below were measured by running the current
`coverage_report.py` against an export of e3629c1.

The 680x0 corpus reaches more encodings but is a detector, not a gate:
212,400 of its cases disagree with the core for reasons docs/validation.md
names, so an encoding it reaches is reached by a weaker oracle.

### What the gate leaves unrun

| Handler | Defined | Unrun by the gate | | Handler | Defined | Unrun |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| move | 8,750 | 3,719 | | scc | 800 | 36 |
| bcc | 3,584 | 1,888 | | addi / subi | 150 / 150 | 18 / 17 |
| moveq | 2,048 | 618 | | cmp | 1,400 | 16 |
| sub / add | 2,408 / 2,408 | 363 / 361 | | ori, andi, cmpa, adda | | 7 each |
| addq / subq | 1,328 / 1,328 | 189 / 189 | | eor, bclr, bset, movea | | 6, 5, 5, 5 |
| bra | 256 | 125 | | btst, suba, cmpm, bchg, muls | | 3, 3, 3, 2, 2 |
| and / or | 2,280 / 2,280 | 98 / 94 | | eori, chk, divu | | 1 each |

Every other handler has every one of its words run by the gate.

Broken down by field, the gate is better than those totals suggest. **Every
value of every field of every rule is sampled somewhere**, with one
exception: 125 of BRA's 256 byte displacements never run. What the unrun
words lack is *combinations*: a register number never seen with a
particular mode, a condition never seen with a particular displacement. By
the axes the families are organised on -- size x addressing mode, and for
MOVE size x source mode x destination mode -- only **18** combinations are
unrun, all involving an absolute or PC-relative operand:

- MOVE.B: (xxx).W -> (xxx).W, (xxx).W -> (xxx).L, (xxx).L -> (xxx).L,
  (d16,PC) -> (xxx).W, (d8,PC,Xn) -> (xxx).W;
- MOVE.W: (xxx).W -> Dn, (xxx).W -> (xxx).L, (xxx).L -> (xxx).L,
  (d16,PC) -> (xxx).W, (d16,PC) -> (xxx).L, (d8,PC,Xn) -> (xxx).L,
  #<data> -> (xxx).L;
- MOVE.L: (xxx).W -> (xxx).L, (xxx).L -> (xxx).W, (xxx).L -> (xxx).L,
  (d8,PC,Xn) -> (xxx).L, #<data> -> (xxx).W;
- ADDI.W to (xxx).W.

The 680x0 corpus leaves 1,079 unrun (move 530, bcc 455, bra 41, moveq 39,
subq 6, add 3, sub 2, addq 2, and STOP, which it has no file for).

### How the suite now covers the 7,796

| Words | Evidence that now reaches them | Tests |
| ---: | --- | --- |
| 3,345 | Their **register-renamed twin is run by the gate**: the gate's evidence transfers through the register symmetry PRM 2.2 states | test_register_renaming.py |
| 2,631 | **Every word of their family is run** against the manual: all 3,584 Bcc words taken and not taken, all 255 BRA byte displacements, all 2,048 MOVEQ words | test_coverage_gaps.py |
| 1,510 | Their renamed twin is *not* run by the gate: the symmetry shows the handler treats register numbers alike, and the gate verifies the handler on other words | test_register_renaming.py |
| 253 | Their own canonical twin, compared as the twin of other words | test_register_renaming.py |
| 40 | Checked against a model of the effective address written from PRM 2.2 (A7's byte step included) and of MOVE, ADDQ/SUBQ and Scc from PRM Section 4 | test_coverage_gaps.py |
| 17 | Run directly: the 17 unrun (size, mode) combinations of MOVE and ADDI above | test_coverage_gaps.py |

The **register-renaming relation** is the one new kind of evidence. The
manuals define every instruction on a generic Dn and An; the only register
they single out is A7, the stack pointer, whose byte (A7)+ and -(A7) move it
by two (PRM 2.2.4-2.2.5). So a word and its twin with registers renamed
must do the same thing from correspondingly renamed states. The test
compares 35,981 words with their canonical twins (registers renamed 0, 1,
2 ... by first appearance, 7 fixed) and 1,559 whose fields name only
register 7 (176 of them among the gate's unrun words) with their 0 <-> 7
twins (A7 exchanged only where it is an ordinary address register), from
random states: every register, SR, both stack pointers, PC, clocks and
every bus access must correspond. It needs no oracle and asserts nothing
about what an instruction does -- only that the answer does not depend on
which register holds the operand.

## 2. Behavioural paths

`NEVER` in the gate (and, separately, in the 680x0 detector), and what
reaches each now. "Manual" means the test asserts what the manuals state;
"T3" that it rests on MAME. The whole suite at e3629c1 left 15 of these
unreached: bus error, illegal instruction, divide by zero (DIVU and DIVS),
the double fault and the halt, an address error during exception
processing, the DIVU overflow boundary, MULU by 0 and by $FFFF, MULS by
$8000, DBcc counting out, and MOVEM with an empty or a full mask
(tests/test_interrupts.py already reached the interrupt and trace paths).

| Path | Gate | 680x0 | Now reached by |
| --- | ---: | ---: | --- |
| Illegal instruction, vector 4 | 0 | 0 | test_the_illegal_instruction_takes_vector_four (manual); clocks 34, UM Table 8-14 |
| Divide by zero, vector 5 | 0 | 1 (DIVU) | test_divide_by_zero_* (manual: vector, stacked PC, operands, 38 + EA clocks; **flags not asserted**) |
| The trace exception itself, vector 9 | 0 | 0 | test_the_trace_exception_is_taken_after_the_instruction, test_a_traced_trap_* (manual) |
| Bus error, vector 2 | 0 | 0 | test_a_bus_error_takes_vector_two_* on 7 kinds of access (manual: R/W, I/N, FC, address) |
| Address error during exception processing (I/N set) | 0 | 0 | test_an_address_error_inside_exception_processing_sets_i_slash_n (manual) |
| Double bus fault, halt | 0 | 0 | test_a_fault_while_taking_an_address_error_halts_the_processor (UM 5.4.4) |
| Interrupts, all acknowledge answers, level 7 edge, trace before interrupt, STOP idling | 0 | 0 | tests/test_interrupts.py (consistent with the manual and MAME) and test_level_seven_held_and_reasserted_is_taken_once |
| Autovector E-clock wait, each of the 10 phases | 0 | 0 | test_autovector_clocks_at_each_e_clock_phase (**T3**: MAME's vpa_sync, matched by the lockstep) |
| Privilege violations | 11,276 | 0 | (gate); the 680x0 corpus never runs in user mode |
| Reset through `M68000CPU.reset()` | 0 | 0 | test_reset_loads_the_stack_pointer_* (UM 6.3.1) |
| DBcc counting out to -1 | 0 | 0 | test_dbcc_falls_through_when_the_count_expires, test_dbcc_runs_a_loop_body_* (manual) |
| MOVEM with an empty mask / all sixteen | 0 / 0 | 1 / 0 | test_movem_with_an_empty_and_a_full_register_list (manual) |
| DIVU overflow at dividend >> 16 = divisor | 0 | 0 | test_divu_overflow_at_the_boundary_* (manual) |
| MULU by 0 or $FFFF, MULS by $8000 | 0 | 3 / 0 / 0 | test_multiply_at_the_operand_boundaries (manual) |
| Trace after an illegal or privileged instruction | not observable | not observable | test_no_trace_follows_an_instruction_that_was_not_executed (manual; found a bug, below) |

Every path the probe declares is now reached by the suite, except an
address error on a program-space *write*, which cannot happen on a 68000.

What the gate reaches well: **all 64 shift counts** at all three sizes in
both directions for all four shift kinds (so every count >= width case);
**every condition against every CCR value** for Bcc, DBcc and Scc; every
TRAP vector; every privilege-violation instruction; 55,606 address errors
(44,096 data reads, 9,064 program reads, 2,446 data writes), in user and in
supervisor mode; S changing in both directions (43,814 and 2,904 times).

### Operand boundaries and flag outcomes

The gate's operands are random, so values at the boundaries of the word and
long ranges almost never occur. Classifying each operand of ADD, SUB, ADDX
and SUBX as 0, 1, all ones, max positive, min negative or other, the gate
reaches 3 of the 36 (destination, source) class pairs for ADD.W, 2 for
ADD.L, 1 for ADDX.W and ADDX.L, and 15 for ADD.B. Flag outcomes follow: the
gate never produces a zero sum without carry at word or long size (0 + 0),
nor Z with C or Z with V and C (e.g. $8000 + $8000). Against the outcomes
each rule can produce at all (found by enumerating the rule over every byte
pair), ADD.W reaches 6 of 9, ADDX.W 6 of 9, SUBX.W 7 of 9; CMP, SUB and the
logic rule reach all of theirs.

The suite now reaches **all 36 pairs at all three sizes** for all four
operations, and **every achievable flag outcome** of every rule, in tests
whose expected flags are PRM Table 3-18's boolean formulas restated in the
test, not taken from the core.

## 3. Source lines

| | Core statements run, in the 12 core modules |
| --- | ---: |
| The gate corpus alone | 1,291 of 1,466 |
| The whole suite at e3629c1 | 1,401 of 1,461 |
| The whole suite now | **1,442 of 1,466** |

(The core grew by 5 statements with the trace fix.)

The 24 core statements the suite does not run: 17 run at import, before the
tracer is installed (the decode table's construction, `_kind`, `_test`); 3
are defensive `AssertionError`s the decoder makes unreachable; and 4 are
**dead code**: `_push_word` in `_core.py`, which nothing calls, and the
long branch of `_write`, which no caller reaches (every long write goes
through `_write_long` or `_write_long_low_first` directly). Removing them
is a question for Aubrey (docs/worklog.md). The tooling modules (debug,
console, disasm, trace, `__main__`) are exercised by tests/test_tooling.py
and are outside this report's scope.

## 4. Open gaps

What the evidence does not settle, and what would. None of these is turned
into a test of what the core happens to do.

1. **Condition codes after a divide by zero (DIVU and DIVS).** PRM Table
   3-18: undefined. The core uses WinUAE's `divbyzero_special` (T2, read
   from source, not run). The gate has no divide by zero (its issue #3);
   the 680x0 corpus has one, a DIVU, which disagrees with CLK and matches
   the WinUAE reading; no DIVS by zero anywhere. Mutant D10 changes the
   DIVS rule and survives everything ([mutation](mutation.md)). *Settle:*
   run WinUAE's 68000 core on DIVU/DIVS #0 over dividend signs and sizes;
   decisively, a hardware run (transistorfet's 68k-test-runner or WinUAE
   `cputest` on a real 68000).
2. **The PC stacked by the illegal-instruction exception.** UM 6.3.6 says
   only "similar to traps". The core stacks the illegal word's own address,
   the rule the gate confirms for line A and line F (5,000 cases, T3) and
   the same code path; no case of either corpus takes vector 4. *Settle:* a
   MAME trace through an ILLEGAL, or hardware.
3. **Stacked PC and IR of bus errors, and of an address error raised during
   exception processing.** UM 6.2.5 calls the PC unpredictable. The gate
   pins these for ordinary address errors (T3); nothing pins them for BERR
   (no corpus models it) or for the I/N case (no corpus case). The tests
   assert only the documented fields. *Settle:* WinUAE (T2, run) or
   hardware.
4. **CHK's undefined flags at Dn = 0.** PRM defines N only when CHK traps;
   the gate and WinUAE agree on the core's rule where the gate has cases,
   but no case of either corpus has Dn = 0 (where the core sets Z).
   *Settle:* a WinUAE run, or hardware.
5. **Clock counts where the manual and the emulators disagree.** The core
   follows the microcode-derived corpus, and WinUAE agrees where read:
   ADDQ.W #,An is 8 clocks (UM Table 8-5 prints 4; 118 gate cases say 8;
   mutant CY14, which follows the manual, is killed by the gate); CHK taking
   the trap for Dn > bound is 38 + EA (UM Table 8-14 prints 40); an address
   error is 58 from the aborted access (UM prints 50; docs/undocumented-
   behavior.md). *Settle:* cycle-level hardware measurement, or WinUAE's
   `cputest` timing on a 7 MHz Amiga (its own claim is within 2 clocks, not
   enough for the CHK question).
6. **The double bus fault.** The core halts, as UM 5.4.4 says, and a test
   now asserts it; MAME 0.285 takes another address error instead. The
   manual decides it for the purposes of this suite; hardware would settle
   the disagreement with MAME.
7. **The autovector E-clock wait** is pinned by MAME's rule (T3), matched by
   the System 16B lockstep at all ten phases; the manual gives only the
   principle. *Settle:* a hardware timing capture of an autovectored
   interrupt at known E-clock phases.
8. **Carried over from the build session** (docs/worklog.md, open
   questions 1 and 5): the stacked PC of DBcc with an odd target (MAME, CLK
   and a WinUAE reading give three different answers), and the stacked PC
   of operand address errors against WinUAE case by case.

## 5. What the coverage work found

- **A core bug**, invisible to both corpora: with T set, an illegal word, a
  line A or F word, or a privileged instruction in user mode took its
  exception and then a trace exception. UM 6.3.8 says an instruction that
  is not executed is not traced; MAME's microcode and WinUAE agree. Test
  4206431 (failing), fix 8760315.
- **A weak existing test**: tests/test_interrupts.py's E-clock phase test
  can only fail if every phase gives the same clock count (docs/mutation.md,
  docs/worklog.md). Left as it is; a precise test was added beside it.
- **Dead code**: `_push_word`, and `_write`'s long branch.
- **A mistake of this session's own, corrected**: the first version of the
  path probe ran 680x0 cases on the m68000 corpus's word-addressed host and
  reported 199 divide-by-zero cases in that corpus; there is one. Fixed in
  e7ffbcd before any document used the number.
