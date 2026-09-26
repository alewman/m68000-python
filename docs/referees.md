# Referees: other emulators, run, as evidence with a lineage

Until 2026-09-21 most of what this repository said about WinUAE was read
from its source, never run, and the gate corpus and the MAME lockstep were
one oracle (MAME's microcode) consulted twice.  This page records two
emulators built here and run one instruction at a time against the core,
what each can judge, how each was calibrated, and what running them
answered.  Referees are evidence with a lineage and a tier
([validation](validation.md), "The tier rule"), not votes: two referees of
one lineage are one confirmation, and a referee's word counts as a judgement
only inside the scope its author corrected it on.

Everything is reproducible from the repository (third-party sources are
fetched at pinned commits into an ignored directory and never committed):

```text
python validation/referees/build_referees.py                 # fetch and build both, ~20 s
python validation/referees/calibrate.py winuae               # vs the gate, per file (~1 min, PyPy)
python validation/referees/calibrate.py musashi              # likewise
python validation/referees/calibrate.py musashi --corpus 680x0
python validation/referees/questions.py                      # the open questions, as tables
python validation/referees/rerun_680x0.py                    # the rung 5 table re-derived (~2 min)
python validation/referees/bus_errors.py                     # BERR on the gate's states (~3 min)
```

Timings are PyPy 7.3.23 on the shared 32-core machine at a load of about 8.

## The referees

| Referee | Pin | Lineage | Models | Tier |
| --- | --- | --- | --- | --- |
| WinUAE's CPU tester core | `tonioni/WinUAE` `1977af501f6c3389c2eefe119ecb10c82d6582f3` (2026-09-17) | UAE (Bernd Schmidt, 1995) as developed by Toni Wilen; corrected against real Amigas with `cputest`.  **Hatari's `src/cpu/` is the same code**: not built here, and it would never count as a second vote. | registers, SR, PC, memory written, the exception taken and its stack frame, the clock total; not the bus order, not the prefetch queue's contents | **T2** inside cputest's checked scope (below), T3 outside |
| Musashi | `kstenerud/Musashi` `313ebf1bd9f4d0d93341eb5ce21fd8a119e9dbdd` (2026-03-08) | Hand-written interpreter (Karl Stenerud), independent of both MAME's microcode transcription and UAE; MAME's 68000 core before 2023 | architectural results; group 1/2 exception entry | **T3**, and only inside its model |

Neither referee shares a lineage with the gate (SingleStepTests/m68000 and
the MAME lockstep are MAME's microcode) or with the 680x0 corpus (Tom
Harte's CLK).

## WinUAE's CPU tester core

**What was built.**  WinUAE's CPU tester (`cputest`, readme
`cputest/readme.txt`) generates its test data on a PC by running each test
instruction on a special core that `gencpu` emits when built with
`CPU_TESTER` set: `cpuemu_90_test.cpp`, the 68000 in cycle-exact prefetch
mode with address and bus errors.  That core, not WinUAE's emulator loop,
is what the Amiga-side program compares real hardware against.
`build_referees.py` follows the readme's build steps on Linux: gencpu with
`CPU_TESTER` switched on (the switch is a `#define 0` in `gencpu.cpp`,
changed in a copy), then the generator's own sources (`cputest.cpp`,
`cputest_support.cpp`, `newcpu_common.cpp`, `readcpu.cpp`, `disasm.cpp`,
the FPU and softfloat units it links) with two Unix adjustments made to
copies in `build/`: `od-unix/machdep/m68k.h` defines `cctrue()` inline where
the tester defines its own, and TCHAR-wide calls get a char overload
(`winuae_shim.h`).  `winuae_referee.cpp` `#include`s the fetched
`cputest.cpp` (renaming its `main`), sets up one test region over the
24-bit space, and for each case loads the state, runs the instruction's
handler once, and prints what the generator would have recorded.  The build
took one attempt at each step; nothing blocked it.

**What it models, and what it does not.**  The tester never executes an
exception: when the instruction raises one, it records the exception number
and builds the frame separately (`doexcstack`), and the Amiga side adds a
fixed cost for the exception's own processing (`cputest/main.c`,
`getexceptioncycles`: 58 for a bus error, 54 for an address error after its
aborted access, 34 for vectors 4-11, 30 for TRAPV, 44 for an interrupt, and
28 more when an odd vector turns a group 1/2 exception into an address
error).  So the referee's view is the state *at the moment the exception is
raised* plus the frame; `referee.py` recovers the same view from a corpus
case or a core run (the frame read off the stack, the SSP before it, the SR
it stacked).  The core reads the prefetch queue from memory ("no real
prefetch"), so the queue's contents and the order of bus cycles are not
modelled; the driver logs the order of the instruction's data accesses, a
T3 detector.  Cases it cannot represent are counted as not judged: an
access in the top 1 KB of the address space (where the tester builds its
frames), an odd SSP when an exception is taken, a double fault, RESET in
supervisor mode (the tester treats it as a reset) and a STOP that stops.

**Hardware-corrected scope.**  The tester runs on a real 68000 (a 7 MHz PAL
Amiga with Fast RAM for cycle counts) and stops at the first mismatch; its
author corrects the core until the hardware agrees.  What it compares,
from its readme and from `cputest/main.c`: every register, SR and PC; the
exception number and the whole stack frame (the 68000 group 0 frame
compared field by field, including bits 15-5 of the access word; the
stacked PC field since 09.05.2020); memory writes; the undefined flags --
every 68000 preset in `cputestgen.ini` sets `feature_undefined_ccr=1`, which
in `cputest.cpp` turns the ignore masks for DIV and CHK *off* (the ini's
comment reads the other way; the code decides); and the clock total,
including exception processing, **to within 2 clocks** (`cycles_range = 2`;
the counter is `$DFF006`).  The 68000 presets say which cases it generates:
BASIC (every instruction, all addressing modes, T set in a second round,
the illegal words last), AESRC/AEDST (odd source and destination
addresses: operand address errors), ODDSTK (odd user stack), ODDEXC (odd
exception vectors for MOVE to SR, MOVE USP, ILLEGAL, CHK, TRAP, TRAPV,
DIVU, DIVS, ORI to SR), IRQ/ODDIRQ (interrupts), and BEPR/BEBR/BESRC/BEDST/
BESRCW/BEDSTW (bus errors, with extra hardware).  The author's reports:
"09.02.2020 All 68000 tests are 100% confirmed, including full cycle-count
support"; "68000 re-verified (except bus errors)" (15.02.2020); "All
prefetch bus error tests verified.  68000 read bus errors re-verified"
(16.02.2020); and WinUAE's changelog (`od-win32/winuaechangelog.txt`, 4.3.0:
"Fixed CPU tester detected differences between UAE and real CPUs", a
68000 list covering LINK A7, CHK flags, divide-by-zero flags, MOVE.W to
-(An) faults, (An)+/-(An) on address errors, DBcc with an odd offset;
4.4.0: stacked PC fields, odd vectors; 5.3.0: branch bus errors).

So, inside scope (T2): results, flags (undefined ones included), address-
error frames and register side effects, odd-vector frames, read and
prefetch bus-error frames, and clock totals where the difference is more
than 2 clocks.  Outside (T3): bus order and function codes of accesses that
complete; clock differences of 2 or less; halting (every test that would
halt or reset is skipped); a STOP that stops; bus-error clocks (the readme
excludes them); write bus errors (presets exist, but they were not in the
last re-verification; treated as T3 here, conservatively); trace combined
with an odd vector (no preset); anything the random generator may not have
reached -- a checked *rule* is T2, while a particular corner of it (Dn = 0
for CHK, say) is covered only as far as the generator's operands went.

**Calibration against the gate** (all 127 files, 317,500 cases):
**308,416 of 314,988 judged cases agree** (97.9%); 2,512 not judged (1,233
RESET, 1,230 STOP, 49 in the top 1 KB).  89 files agree completely.  Every
one of the 6,572 disagreements is an address error or a clock difference
of exactly 2; no ordinary case disagrees, so the harness reproduces the
tester.  The residual, which is therefore a property of the referee against
the gate (and each is a question, below):

| Cases | What differs | Gate (MAME) | WinUAE |
| ---: | --- | --- | --- |
| 4,330 | An after a word (An)+ operand address error (32 files) | moved by 2 | not moved |
| 115 | An after CMPM.L (An)+,(An)+ faults | 2 further | 2 less |
| 762 | stacked PC of JSR (d16,An), (d8,An,Xn), (d16,PC), (d8,PC,Xn) to an odd target | instruction + 4 | instruction + 2 |
| 632 | stacked PC of DBcc to an odd target | instruction + 4 | target + 2 |
| 306 | stacked PC of MOVEM (d8,An,Xn), (d8,PC,Xn) at an odd address | 4 more | 4 less |
| 228 | clocks of MOVE to -(An) whose write faults (MOVE.w 120, MOVE.l 108) | n | n + 2 |
| (35 of those) | I/N of that MOVE.W's frame when the next word is illegal or privileged | 0 | 1 |
| 199 | clocks of CHK trapping with Dn < 0 when bound - Dn overflows 16 bits | 8 internal | 10 internal |

**Against the 680x0 corpus (CLK)**, where the core and CLK agree (787,660
cases), WinUAE agrees on all 779,253 it can judge (8,065 RESET and 342
top-KB cases not judged).  Its answers where they disagree are the
re-derived table below.

## Musashi

**What was built.**  `m68kmake` generates `m68kops.c` from `m68k_in.c`;
`m68kconf.h` is copied with the 68010-68040 cores off, address errors on
(so an odd access is not silently performed), trace and prefetch emulation
off.  `musashi_referee.c` links Musashi's own files, sets the registers
through `m68k_set_reg`, runs `m68k_execute(1)` (one instruction, exception
entry included) and prints the state after it.  No difficulty.

**In scope, and why.**  Musashi has no prefetch queue, no bus-cycle order,
no microcode PC: its address-error frame is a stylised one (bits 15-5 of the
access word empty, the stacked PC its own) and it takes an odd branch
target's fault only at the next fetch.  So it is compared only on the
**post** view of cases in which the gate takes no address or bus error:
D0-D7, A0-A6, both stack pointers, SR, the next PC, and memory, which covers
ordinary instructions and the entry into group 1/2 exceptions (the frame's
SR and PC, the new SR, the vector).  Its clock counts come from its own
table and are reported as a property, never judged.  Its undefined-flag
choices are its author's; where they differ from the core, WinUAE (T2) or
the BCD tables (T1) decide, not Musashi.

**Calibration against the gate:** **257,300 of 261,894 judged cases agree**
(98.2%); 55,606 not judged (the gate took an address error).  119 of 127
files agree completely.  Every disagreement is a known choice of Musashi's
on undefined or disputed behaviour, and in each a higher tier sides with
the core:

| Cases | What differs | Decided by |
| ---: | --- | --- |
| 1,130 + 1,037 + 279 | SBCD, NBCD, ABCD: N and V, and the result for non-BCD digits | T1: flamewing's BCD tables (the core's gate) |
| 1,025 + 687 | DIVS, DIVU overflow: Musashi leaves N and Z | T2 (WinUAE, run) and the gate |
| 326 | LINK A7: Musashi pushes the decremented A7 | T2 (WinUAE, run: the 4.3.0 LINK A7 fix) |
| 107 | CHK not trapping: Musashi leaves N | T2 (WinUAE, run) and the gate |
| 3 | `$F620-$F627` (line F): Musashi runs another handler | the manual (UM 6.3.6) and the gate |

Clocks differ in 10,371 of the judged cases (Musashi's table: ADDA.L,
SUBA.L, MULS, the long logic ops and CHK among them).  Against CLK's
corpus: **807,147 of 821,973 judged cases agree**; the rows that matter for
the re-derived table are that Musashi agrees with the core against CLK on
every ASR by a register count (3,736 cases: X and C set) and on corpus issue
#4 (2 ASL.b cases), and with CLK against the core on LINK A7 (1,005) and on
CHK's undefined flags (321).  None of that is a verdict: Musashi is T3.

## The open questions, put to the referees

`questions.py` writes each question as a handful of hand-made states (code
at $1000, SSP $8000, every vector pointing at its own NOPs).  "Scope" says
whether the case lies inside cputest's checked scope, which decides whether
WinUAE's answer is T2.

| Question | Core | WinUAE (lineage UAE) | Musashi | Other lineages | What can be claimed |
| --- | --- | --- | --- | --- | --- |
| **DBcc to an odd target** (DBF D0,*+$13): stacked PC | instr + 4 ($1004), = gate (MAME) | target + 2 ($1015); Dn not decremented (= core); in scope (changelog 4.3.0 "DBcc and odd offset ... Address error stacked PC was wrong", fixed on hardware; AESRC) | fault taken at the next fetch: no frame in one step (out of model) | CLK: the odd target | **Conflict** between T2 (WinUAE, run) and the gate (T3).  Core left on the gate; **contested** ([claims](claims.md)). |
| **CHK timing, 8 or 10** (Dn = $8000, bound $7FFF; and 2 more overflow cases) | 38 total (8 internal) | 40 (6 + 34) | 40 | CLK: 10 (the 605 680x0 cases, below) | Undecided.  WinUAE, CLK and Musashi say 10, MAME 8; the difference is 2 clocks, inside cputest's ±2, so no T2 claim either way.  Settle: a logic-analyser capture of this CHK on a 68000. |
| **Double bus fault** (address error with SSP odd; or with vector 3 odd) | halts (both) | tester: out of scope (skips halting tests; this driver reports `oddssp` / `doublefault`); WinUAE's emulator, read (`newcpu.cpp`, `Exception_ce000`): halts for both; changelog 4.4.0 "Odd bus error or address error vector will halt the CPU" | SSP odd: halts (run); vector 3 odd: fault at the next fetch, not run | MAME 0.285: another address error | T3 only (a reading and a hand-written core, against MAME), plus the manual (UM 5.4.4).  No change.  Settle: hardware (an odd SSP, then a fault). |
| **Divide-by-zero flags** (DIVU/DIVS over 5 dividends × CCR 0/1F) | DIVS: Z, N=V=C=0; DIVU: N from bit 31, Z from the upper word; X kept | **identical on all 20**; in scope (BASIC with undefined flags checked; changelog 4.3.0 "100% correct") | leaves all flags | CLK: 1 DIVU case, = WinUAE | **T2 by running.**  Pinned (`tests/test_referee_evidence.py`); mutant D10 is now killed. |
| **CHK flags with Dn = 0** (bound 5, 0, $FFFF × CCR 0/1F) | Z, N=V=C=0, X kept, trap or not | **identical on all 6**; in scope (CHK undefined flags, BASIC) | leaves N when not trapping | -- | **T2 by running** (for the rule; Dn = 0 itself is a corner the generator may not have hit).  Pinned. |
| **PC stacked by ILLEGAL** ($4AFC, $4AFA, $4AFB, $4E7B, line A, line F) | the word's own address, 34 clocks | **identical**; in scope (the tester's ILLEGAL set; illegal-exception timing is one its cycle counting relies on) | identical | gate: line A/F (5,000 cases) | **T2 by running.**  Pinned. |
| **Bus errors: stacked PC and IR** | see the sweep below | read: 87,930 of 97,316 swept cases agree; prefetch 76,792 of 231,067; write 23,327 of 70,350 | out of model | none | T2 where they agree on reads and prefetches (7 cases pinned); the disagreements are open (below). |
| **The I/N case** (an odd vector during group 1/2 processing) | I/N = 1 for all | ILLEGAL: I/N 1 (= core); TRAP, TRAPV, CHK, DIVU by zero: **I/N 0**; in scope (ODDEXC; changelog 4.4.0) | out of model | MAME's microcode (read): TRAP/TRAPV/CHK/DIV stacking and refill carry no N, illegal/privilege/line A/F/trace/interrupt do | For group 2 the core disagreed with T2 (run) and with MAME (read), and an existing test asserted I/N = 1 for TRAP #0 on the manual's wording.  **Decided 2026-09-21 (Aubrey): the core now clears I/N for group 2** (17594c3 test, e395be9 fix); `questions.py in-bit` agrees with WinUAE on all five cases, every field.  TRAPV's IR in the same frame was a core bug: fixed (6ec31b4, e057279). |
| **Stacked PCs of operand address errors** | the gate's | agrees except JSR (4 modes, 762 gate cases), MOVEM (d8,...) (306), DBcc (632); on the 680x0 cases agrees with the core on 118,245 of 123,858 judged | out of model | CLK: see the table below | **T2 by running** where they agree (the core's rule); the three families are conflicts with the gate: Aubrey's decision. |
| **Clocks where the manual and the emulators disagree** | ADDQ/SUBQ.W #,An 8; CHK trap (Dn > bound) 38; address error 58 | 8; 38; 58 | 4 (ADDQ.W, but 8 for SUBQ.W); 40; 50 | manual 4; 40; 50.  CLK: 6 for ADDQ.L #,An | **T2 by running** that ADDQ.W #,An is 8, not 4, and an address error 58, not 50 (differences above 2 clocks).  CHK's 38 vs 40 is inside ±2: undecided by T2; the gate says 38. |

Two further conflicts surfaced while calibrating, both inside scope and
both against the gate: **An after a word (An)+ address error** (WinUAE:
not moved; gate: moved; 4,330 gate cases, 14,148 680x0 cases where core and
CLK both move it; CMPM.L differs too, 115 gate cases; changelog 4.3.0 "An contents are updated (or not updated)
if -(an) or (an)+"), and **I/N of a MOVE.W to -(An) whose write faults when
the next word is illegal or privileged** (WinUAE 1, gate 0; 35 gate cases;
changelog 4.3.0 "CPU bug found and emulated").  Both are **contested**
([claims](claims.md), decided 2026-09-21: the core stays on the gate).

## The 680x0 disagreement table, re-derived by running WinUAE

`rerun_680x0.py` ran all 1,000,060 cases of SingleStepTests/680x0 on the
core, on CLK's recorded answer and on WinUAE, in the pre-exception view,
and for every field on which the core and CLK disagree recorded what WinUAE
says.  The table of docs/validation.md was not consulted while running;
the comparison with it is afterwards.  Counts are cases (a case can carry
several causes, as in the original table); "judged" excludes the top-1 KB
cases.

| Cause (the original table's row) | Cases | Running WinUAE says | Against the original write-up |
| --- | ---: | --- | --- |
| Address error costs 8 clocks more | 178,087 | clocks = core in all 178,083 judged | **Confirmed by running**; decisive (8 > 2 clocks). |
| Stacked PC of an address error | 123,862 | pc = core in 118,245; = CLK in 1,069 (MOVEM (d8,An,Xn), (d8,PC,Xn)); neither in 4,544 (JSR (d8,An,Xn) etc. 2,580: instr + 2; DBcc 1,964: target + 2); 4 not judged | Mostly **T2 by running** for the core.  **Contradictions:** MOVEM (d8,...) -- WinUAE sides with CLK; JSR through (d16,An), (d8,An,Xn), (d16,PC), (d8,PC,Xn) -- WinUAE differs from both (the write-up's JMP reading is confirmed, but JSR was never evaluated); DBcc -- target + 2, as the reading said. |
| Whether An had moved when the fault came | 17,119 | An/Dn = core in 16,746 (long (An)+, -(An), DBcc's Dn, MOVE.L to -(An)); **CMPM.L (An)+,(An)+: neither, 373** | Mostly confirmed; CMPM.L is a contradiction.  And the table never saw the larger one: in 14,148 cases the core and CLK *agree* that a word (An)+ moved, and WinUAE says it did not. |
| Accesses before the fault (MOVE with PC-relative source; RTE, RTR) | 8,180 | no pre-exception field differs except MOVE to -(An)'s +2 clocks (18) | Bus order: outside what the tester checks. |
| RTE/RTR read the stack in another order | 8,049 | the tester core's data-read order = the core's in all 8,048 judged | The order is not something cputest checks: **T3 by running**, not T2 as the table said.  Consistent with the core. |
| TAS logged as one access | 6,828 | no pre-exception difference | A format difference, as the table said. |
| FC of a PC-relative read (directly / in frames) | 4,541 / 3,175 | directly: not observable; in address-error frames: access word = core in all 3,175 | Frames: **T2 by running.**  Direct accesses: outside the tester (T3 reading stands). |
| CHK traps without refilling first | 4,291 | 3,672 no pre-exception difference (bus order); **605: clocks = CLK** (10 internal, the overflow case); 13 ccr = core | The refill order is bus order (T3).  The 605 are the CHK timing question: WinUAE agrees with CLK, within ±2. |
| ASR by a register count ≥ size | 3,736 | X and C = core in all | **T2 by running** for ASR.w and ASR.l too (T1 already for ASR.b). |
| DIVS/DIVU overflow flags; DIVS clocks | 2,839 + 1,855; 1,265 | flags = core in all judged; clocks = core in all judged (the core is 106-132 clocks longer than CLK) | **T2 by running**, decisive. |
| LINK A7 pushes the value before the push | 1,005 | memory = core in all | **T2 by running.** |
| Halfway flags of a MOVE.L whose first write faults | 822 | = core in all | **T2 by running.** |
| ADDQ/SUBQ.L to An: 8 clocks, not 6 | 731 | = core in all | Agrees, but the difference is 2 clocks: inside ±2, so **not** T2; the manual (8) and the gate remain the evidence. |
| IR of a MOVE.W whose -(An) write faults | 332 | IR = core in all; clocks +2 (neither); I/N differs in 85 (next word illegal/privileged) | IR **T2 by running**; the I/N and clocks are the conflicts above. |
| CHK's undefined flags | 321 | = core in all | **T2 by running.** |
| ASL.b 1583, 1761 (issue #4) | 2 | = core | Agrees. |

## Bus errors

No corpus models BERR.  `bus_errors.py` reuses the gate's own states: for
every gate case that takes no exception it asserts BERR from the case's
first data read, first data write, or first program read onward (a 512 KB
region, one kind of access, as in the tester's presets) and compares the
core with WinUAE on the pre-exception view.  **Data reads: 87,930 of 97,316
agree (90.4%)**; the rest are register side effects (6,600, e.g. MOVE.L
(An)+ whose second word faults: the core has moved An by 4, WinUAE not at
all), stacked PCs (1,863, all 1,263 RTS cases among them) and stack pointers
(961).  **Prefetches: 76,792 of 231,067 (33%).**  Three rules account for
nearly all of the rest: WinUAE sets I/N when the word already in IR is
illegal or privileged or a trace is pending (the core never does for an
instruction's own access); for the many instructions whose closing prefetch
comes before their ALU step (shifts, rotates, BCD, the -(An) arithmetic
forms...) WinUAE stacks the instruction itself as IR and has not yet
written the flags or the register, where the core has written both and
stacks the next opcode; and a few families differ in the stacked PC (LINK
by 4, all 2,500 cases).  **Writes: 23,327 of 70,350 (33%)**, mostly the same
I/N rule, and the stacked PC of MOVE to (An) and (An)+ (2 less in WinUAE).

Reads and prefetches are inside the tester's checked scope, so each of
these is T2 evidence that the core's bus-error model -- its address-error
model extended to BERR, pinned by nothing -- is wrong in these classes.  It
is not changed here: bringing it in line means reordering the closing
prefetch against the register and flag writes in most instruction
handlers, a redesign rather than a fix, with only one lineage (UAE) to
check it against.  The cases where the two agree on the documented and the
checked fields are pinned (`tests/test_referee_evidence.py`, 7 cases).  One
genuine core bug surfaced: a BusError raised on TAS's write half escaped
`step()` (309f09e test, 36862e5 fix).

## Harness decisions worth knowing

- The tester builds exception frames in 1 KB just past its test region,
  addressed through the 24-bit mask, so the region ends 1 KB short of
  16 MB and an access there is not judged (flags=`oob`).
- The tester's bus-error check compares full 32-bit addresses; the
  driver re-checks data accesses on the 24-bit address (the 68000 drives
  A23-A1).  Program fetches cannot be re-checked, so jump-type
  instructions are left out of the prefetch sweep.
- A group 1/2 exception whose vector is odd is re-run in the tester's
  ODDEXC mode (`feature_exception_vectors`), which is how the tester itself
  models it.
- The frame's SR slot as the tester builds it can be stale (the tester
  compares SR from its registers, not from the frame), so the referee's SR
  comes from its registers.
- A stopped CPU has made no closing prefetch, so for STOP the corpus's
  `pc` is compared as it stands (Musashi).
