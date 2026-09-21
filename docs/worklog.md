# Worklog

A running record of the session that builds the core: what was run, with
counts and pins, what did not pass, and what is waiting for Aubrey. Newest
entries at the bottom of each section.

## How I read the brief, and the plan (2026-09-18)

The brief (`docs/handoff-brief.md`, 18a681d) asks for a pure-Python MC68000
core in z80-python's module shape and m6800-python's structure (dispatch
tables built once at import by a `build_table`, callables host contract,
mnemonic-first docstrings enforced by a readability test), certified up a
ladder of six rungs in oracle-tier order, never lowering a bar to reach the
next one. The hard part is not the instruction semantics but the bus: the
m68000 corpus records every bus access (kind, address, size, value, strobes)
and the prefetch pair, so the core must reproduce the microcode's access
order, including the partial access list and the seven-word frame of
address errors, which random An values make common in the corpus.

What I will do, in order:

1. **Rung 1.** A corpus reader that parses `*.json.bin` directly; a test
   host whose `read_word`/`write_word`/`read_byte`/`write_byte` callables log
   transactions; the core skeleton (`_core.py` prefetch queue, exception
   entry with address-error frames, `_ea.py`, `_dispatch.py` decoding all
   65,536 words, `disasm.py`); then `NOP`, `MOVEQ` (`MOVE.q`), `Bcc`, `RTS`,
   `MOVE.w` to 2,500/2,500 each with transactions. The T-bit decision
   (corpus issue #2) is made here and written in `docs/validation.md`.
2. **Rung 2.** Port flamewing's BCD table generator (read from the pinned
   commit, not copied) and run ABCD/SBCD/NBCD over every input.
3. **Rung 3.** Every family, file by file, to 317,500/317,500 or named
   exclusions (TAS cycles, TRAPV if the README's issue is real).
4. Rungs 4-6 (MAME lockstep, 680x0 detector, interrupt scenarios) if time
   allows, in that order.

Reference material read but not copied: MAME 0.285's microcoded core
(`src/devices/cpu/m68000/m68000-sdf.cpp`, `m68000.lst`, `m68000gen.py` at tag
`mame0285`, fetched to a scratch directory outside the repository) to
understand bus-access order where the corpus leaves it ambiguous. The corpus
is generated from that same core, so reading it is reading the T3 oracle's
reasoning, not a higher tier; claims stay T3.

Performance: record instructions/second on CPython and PyPy per rung; keep
function codes and transaction logging out of the fast path (the test host
does the logging; function codes are passed only when the host asks).

## Open questions

For Aubrey; in each case the conservative choice was taken and the work
went on.

1. **DBcc with an odd branch target: which PC is stacked?** MAME's
   microcode (and so the pinned corpus, which the core passes) stacks the
   instruction's address + 4. WinUAE's generator (T2, read, not run) moves
   PC to the target and then adds 2, stacking target + 2; CLK (the 680x0
   corpus) stacks the target. The core follows the gate corpus. Settling it
   needs a WinUAE run or hardware.
2. **CHK timing, 8 or 10 clocks** for a negative Dn inside the bound when
   `bound - Dn` overflows 16 bits: MAME and the corpus say 8, WinUAE 10.
   WinUAE's cycle claim is only to within 2 clocks, so it does not decide;
   the core follows the corpus.
3. **Double bus fault.** The core halts, as UM 5.4.4 says; MAME 0.285
   takes another address error. No corpus case exercises it.
4. **Divide-by-zero flags** come from WinUAE's 68000 rule (T2): the m68000
   corpus has no divide by zero (its issue #3). One 680x0 case agrees with
   WinUAE's rule and not with CLK.
5. **Stacked PC of operand address errors vs WinUAE** (123,862 680x0
   disagreements): consistent with WinUAE where its source was read (JMP,
   MOVE's rules), not evaluated case by case. The next step that would
   settle it is to build WinUAE's (or Hatari's) 68000 core standalone and
   run the 680x0 cases through it as a T2 referee.
6. **altbeast lockstep resynchronises once**: the i8751 resets the 68000
   through the mapper partway through an instruction, which an
   instruction-level core cannot reproduce; after that reset the lockstep
   copies D0-D7/A0-A6/USP from MAME's next line (PC, SR and SSP come from
   the core's own reset). Acceptable?
7. **Nothing pushed, no GitHub repository created**, per the brief.

Added 2026-09-21 (coverage and mutation session):

8. **A weak existing test.** `tests/test_interrupts.py`,
   `test_autovector_wait_follows_the_e_clock_phase`, asserts
   `clocks == set(range(44 + 4, 44 + 14)) or len(clocks) > 1`. The range
   is 48-57; the core and MAME (per the lockstep) give 49-58, so the first
   half is false and the test passes only because the clocks vary. Mutant
   CY10 (the phase boundary moved) survived it. Conservative choice: the
   test is left exactly as it was (the session's rules forbid changing an
   existing test), and a precise one was added beside it
   (`test_mutation_survivors.py::test_autovector_clocks_at_each_e_clock_phase`,
   T3). Should the old one be corrected to `range(49, 59)` or removed?
   **Resolved 2026-09-21 (Aubrey):** corrected to exactly `range(49, 59)`,
   the `or` clause dropped.
9. **Dead code.** `_push_word` in `_core.py` is never called, and the long
   branch of `_write` is never reached (every long write calls
   `_write_long` or `_write_long_low_first` directly). Left in place (no
   change to `src/` except the bug fix). Remove them?
   **Resolved 2026-09-21 (Aubrey):** removed; `_write` now handles bytes
   and words only.
10. **The divide-by-zero flags remain open** (question 4, sharpened):
   mutant D10, which changes the DIVS-by-zero rule, survives the whole suite
   and both corpora -- the 680x0 corpus has one divide by zero, a DIVU, and
   no DIVS. No test asserts these flags, by design. Running WinUAE's core on
   these inputs would move it from T2-read to T2-run; hardware would settle
   it.
11. **The double bus fault** (question 3): a test now asserts the manual's
   halt (UM 5.4.4). If MAME's behaviour were ever preferred, that test is
   the one to revisit.

Added 2026-09-21 (referees session; docs/referees.md has the evidence).
What running WinUAE's CPU-tester core and Musashi said about the questions
above: 1 (DBcc) -- WinUAE stacks the target + 2, inside its checked scope:
now question 12; 2 (CHK 8 or 10) -- WinUAE, CLK and Musashi say 10, MAME 8,
a 2-clock difference inside cputest's +-2, so still undecided; 3 and 11
(double fault) -- outside cputest's scope; WinUAE's emulator (read) and
Musashi (run, odd SSP) halt, MAME does not; the test stands; 4 and 10
(divide-by-zero flags) -- **settled at T2 by running** and pinned
(tests/test_referee_evidence.py; mutant D10 killed); 5 (operand
address-error PCs) -- WinUAE agrees with the core except in the families of
questions 13-15.  In every conflict below the core follows the gate and is
unchanged; each needs Aubrey's decision.

12. **DBcc to an odd target: target + 2 (WinUAE, T2 by running) or the
   instruction + 4 (gate, MAME).**  632 gate cases; 1,964 680x0 cases where
   CLK stacks the target.  In scope: WinUAE changelog 4.3.0, 68000 list:
   "DBcc and odd offset ... UAE: Address error stacked PC was wrong" (fixed
   against hardware).  The core follows the gate.
13. **A word (An)+ operand that faults: is An moved?**  WinUAE (T2 by
   running; changelog 4.3.0 "An contents are updated (or not updated) if
   -(an) or (an)+", the AESRC preset checks registers): not moved.  The gate
   (4,330 cases in 32 files) and CLK (14,148 680x0 cases): moved.  This is
   the largest conflict and touches every word (An)+ address error the gate
   records.  The core follows the gate.
14. **JSR through (d16,An), (d8,An,Xn), (d16,PC), (d8,PC,Xn) to an odd
   target, and MOVEM through (d8,An,Xn), (d8,PC,Xn) at an odd address:
   the stacked PC.**  WinUAE (T2 by running): 2 less for those JSRs (762
   gate cases; 2,580 680x0 cases where CLK differs from both), 4 less for
   those MOVEMs (306 gate cases; 1,069 680x0 cases where WinUAE agrees
   with CLK).  JMP, and JSR through (An), (xxx).W, (xxx).L, agree.  The core
   follows the gate.
15. **CMPM.L (An)+,(An)+ that faults: An.**  WinUAE (T2 by running) leaves
   the faulting register 2 less than the gate does in 115 gate cases, and
   differs from both the core and CLK in 373 680x0 cases.  The core follows
   the gate.
16. **MOVE.W to -(An) whose write faults, when the word now in IR is illegal
   or privileged: I/N.**  WinUAE (T2 by running; changelog 4.3.0 "CPU bug
   found and emulated ... this only happens if following instruction would
   cause illegal instruction, privilege violation or trace is pending"): 1.
   Gate (35 cases) and CLK (85): 0.  The same rule, applied to bus errors,
   is most of the prefetch and write differences in question 19.
17. **I/N for a fault during group 2 exception processing** (TRAP, TRAPV,
   CHK, divide by zero with an odd vector or SSP).  WinUAE (T2 by running,
   ODDEXC preset) and MAME 0.285's microcode (T3, read: those instructions'
   own microcode stacks and refills without SSW_N; the illegal, privilege,
   line A/F, trace and interrupt states set it) give 0; the core gives 1,
   and `tests/test_coverage_gaps.py::test_an_address_error_inside_exception_processing_sets_i_slash_n`
   asserts 1 for TRAP #0, reading UM 6.3.9.1's "not an instruction".  The
   session's rules forbid weakening that test, so the core is unchanged.
   Should the test be changed to the two emulators' rule (1 for group 1,
   0 for group 2)?  TRAPV's IR in the same frame was a separate bug and is
   fixed (6ec31b4, e057279).
18. **Two 2-clock differences inside cputest's tolerance**: MOVE to -(An)
   whose write faults (WinUAE +2: 228 gate cases) and CHK's negative-Dn trap
   (question 2).  T2 cannot decide either; the gate's values stand.  A
   logic-analyser capture would.
19. **The bus-error model.**  No corpus pins BERR; the core's is its
   address-error model extended.  Over the gate's own states with BERR
   injected (validation/referees/bus_errors.py), WinUAE -- T2 for read and
   prefetch bus errors, re-verified on hardware in 2020 -- agrees on 90% of
   data-read faults and 33% of prefetch and write faults; the rest fall into
   named classes (docs/referees.md, "Bus errors"): the I/N rule of question
   16; instructions whose closing prefetch precedes their ALU step, where
   WinUAE stacks the instruction itself and has not yet written flags or
   register; and a few stacked PCs (LINK, RTS, MOVE to (An)/(An)+).
   Matching it means reordering the closing prefetch against the writes in
   most handlers.  Not attempted: is it wanted, with one lineage to check it?
20. **The RTE/RTR row of the rung 5 table was labelled T2.**  The order of
   bus reads is not something cputest checks; running WinUAE agrees with
   the core's order, but that is T3.  validation.md now says so.

## Log

### Rung 1 (2026-09-19)

- Core skeleton in `src/m68000_python/`: `_core.py` (state, bus, prefetch
  queue, group 0 and group 1/2 exception entry), `_ea.py`, `_flags.py`,
  `_dispatch.py` (65,536-entry table built from `RULES`), `_control.py`,
  `_loads.py`, `disasm.py`; `tests/corpus.py` (direct `.json.bin` parser
  and the 680x0 JSON adapter), `tests/harness.py`, `scripts/run_corpus.py`.
- Decoder: 45,815 defined first words plus ILLEGAL, 4,096 line A, 4,096
  line F, 11,529 illegal. Checked word for word against MAME 0.285's
  `m68000.lst` (tag `mame0285`, fetched to a scratch directory): the set of
  defined words and the family of every word agree (a scratch script, not
  committed, because the `.lst` is MAME's).
- **T bit decision (corpus issue #2):** trace is modelled as its own
  boundary. An instruction that starts with T set runs to completion and
  `step()` returns; the next `step()` takes the trace exception. The
  corpus captures `final` before the trace exception, so no stripping of
  T is needed and none is done.
- Corpus comparison (tests/harness.py): registers, USP, SSP, SR, the
  prefetch address and pair, RAM words, clock total, and the ordered bus
  accesses with kind, address, size, value, strobes and function code.
  Not compared: the data value of an aborted (`re`/`we`) access, and the
  position of idle (`n`) entries (their sum is in the clock total).
- Result, SingleStepTests/m68000 @ `64b25311`, CPython 3.14.4:
  NOP, MOVE.q, Bcc, RTS, MOVE.w, MOVE.b, MOVE.l: 2,500/2,500 each
  (17,500/17,500), transactions matched.
- What made the address-error cases pass (60% of MOVE cases fault): the
  stacked PC is the microcode's PC register, which trails the prefetch
  address and is brought up to it at mode-specific steps (`_commit_pc`);
  the IR slot and the access-information word carry IRD, which the closing
  prefetch replaces before its read; a long's flags are set as two word
  halves, and which half is visible at a faulting first write depends on
  source and destination. Each is a comment in the code, tier T3.

### Rung 2 (2026-09-19)

- `_bcd.py`: ABCD, SBCD, NBCD with the N/V rule written out from
  `docs/undocumented-behavior.md` (binary step, per-nibble correction, V
  when the correction flips bit 7), not copied from the verifier.
- T1 gate `tests/test_bcd.py`: flamewing/68k-bcd-verifier @
  `39a01be528b0744302bf1dc9b3463fc22a3fc45f` was cloned to a scratch
  directory, `bcd-gen.cc` built with g++ 15.2.0 and run; its
  `data/bcd-table.bin` is 1,050,624 bytes, SHA-256
  `8432868c9aa93c92574bae48bebd4efb2834e298340eb09530625365b80147e5`.
  The test runs the core over the same inputs in the same layout and
  compares hashes (GPL-3.0 data and code are not committed); with
  `M68000_BCD_TABLE` pointing at the local table it also compared byte
  for byte. **262,144 ABCD + 262,144 SBCD + 1,024 NBCD cases agree on
  result and all five flags.** CPython 3.14.4: 0.8 s; PyPy 7.3.23 /
  Python 3.11.15: see the commit.
- Corpus: ABCD, SBCD, NBCD 2,500/2,500 each.

### Rung 3 (2026-09-19)

- Every family written (`_alu.py`, `_bits.py`, `_shifts.py`, `_system.py`,
  the rest of `_loads.py` and `_control.py`); `tests/test_corpus.py` now
  gates all 127 files.
- **SingleStepTests/m68000 @ `64b25311`: 317,500 / 317,500, no exclusions.**
  CPython 3.14.4: 27.4 s under pytest (`nice -n 10`, load ~45);
  `scripts/run_corpus.py --all` 33 s. PyPy 7.3.23: 25.9 s under pytest,
  15.2 s for the script. Commit 66d373f.
- TAS: the corpus's totals are also WinUAE's (T2, `gencpu.cpp` at
  `1977af5`), so no cycle exclusion was needed. TRAPV: the README's
  "strange issue" did not appear. Both recorded in `docs/validation.md`.
- Rules the corpus settled are in `docs/undocumented-behavior.md`,
  "Settled while building the core"; notable: DIVU/DIVS overflow flags
  (N=1, V=1, Z=0, C=0) and CHK flags agree with WinUAE (T2) rather than
  Musashi; a CHK timing rule for negative Dn; long results' flags in two
  halves visible to a faulting first write.
- Readability test (`tests/test_readability.py`): 173 handler checks pass;
  no fallback handler remains.
- Speed (`benchmarks/speed.py`, 5-10 s runs, loaded machine): CPython
  3.14.4 about 596,000 instructions/s (4.6 emulated MHz); PyPy 7.3.23
  about 22.6 million/s (175 emulated MHz) on that tight loop.
- CI: `.github/workflows/ci.yml` runs the fast suite on 3.11-3.14 and
  PyPy, and the corpus gate (fetched once per pin, cached) on 3.14 and
  PyPy. Not run on GitHub: the repository is local only.

### Rung 4 (2026-09-19)

- `validation/lockstep.py` + `lockstep.lua` + `mame_trace.py`: MAME 0.285
  (`/usr/games/mame`) trace with registers and `totalcycles` per
  instruction, watched reads replayed, watched writes checked.
- **System 16B `altbeast`, 30 emulated seconds: 24,595,631 instructions
  identical**, 1,791 interrupts, 1 reset (i8751-driven), every write
  checked; clocks agree on all 24,593,837 intervals without the driver's
  i8751 spin stall. PyPy compare 563 s; MAME record 802 s.
- **Genesis, Altered Beast (USA, Europe) (Rev 2), 40 emulated seconds:
  28,249,660 instructions identical**, 3,788 interrupts; 28,181,328 of
  28,249,660 clock intervals agree, the rest (sampled) Z80-window and VDP
  wait states. PyPy compare 510 s; MAME record 805 s.
- First divergences, each diagnosed before extending: the i8751 reset
  mid-instruction; the i8751's mapper transfers and the Z80's bank-window
  accesses appearing on the 68000's bus (dropped by the reader); PC
  compared at 24 bits; the trace's last line (MAME stopped). No core
  error was found.
- Disassembler vs MAME's on every distinct traced instruction: 880/880
  (altbeast, 4 s trace) and 3,771/3,771 (Genesis) after writing DBF as
  `dbra` and arithmetic immediates signed, as MAME does.

### Rung 5 (2026-09-19)

- `scripts/run_680x0.py`, `scripts/classify_680x0.py`,
  `tests/harness_680x0.py`. 680x0 corpus @ `e0d5ece9`: **787,660 of
  1,000,060 agree**; every disagreement classified (none unclassified),
  table and sources in `docs/validation.md`. Most causes are explained
  by WinUAE's 68000 rules read from `gencpu.cpp`/`newcpu.cpp`/
  `newcpu_common.cpp` at `1977af5` (T2), ASR by transistorfet's hardware
  run (T1, exactly 1,642 ASR.b cases), ASL.b by the corpus's issue #4.
  Open: stacked PC of operand address errors (not evaluated case by case)
  and DBcc's (T2 reading disagrees with MAME). Divide-by-zero flags now
  follow WinUAE.

### Rung 6 (2026-09-19)

- Interrupt entry rebuilt on MAME's order (PC low, acknowledge, SR, PC
  high) with the E-clock wait of an autovector (`vpa_sync` + 1); the
  lockstep's clocks agree at all ten phases (1,791 + 3,788 interrupts).
- `tests/test_interrupts.py`: 12 scenarios. STOP now resumes, on interrupt
  or trace, at the instruction after it.

### Tooling (2026-09-19)

- `state.py`, `debug.py`, `trace.py`, `console.py`, `__main__.py`,
  `py.typed`, `attach_bus`, `set_sr`; docs `cpu-state.md`,
  `debug-session.md`, `trace-schema.md`, `disassembly.md`;
  `tests/test_tooling.py`.
- Speed, `benchmarks/speed.py`, load ~40: CPython 3.14.4 741,000
  instructions/s (5.7 emulated MHz); PyPy 7.3.23 19.3 million/s.

## Coverage and mutation testing (2026-09-21)

The brief for this session (from Aubrey, 2026-09-21): no exhaustive hardware
oracle exists for the 68000, so build a web of independent evidence and say
precisely where it is insufficient.  Task 1, a coverage map of what the
corpora reach and tests for the gaps the manuals decide; task 2, mutation
testing of the verification suite, reporting survivors.  Hard rules: no
change to `src/` to make anything pass, no gate weakened, a core bug gets a
failing test commit and then a separate fix commit.

### Coverage report (689f18f)

- `scripts/coverage_report.py`, three views: `encodings` (first words
  executed, per handler, per rule, per field, per (size x EA mode)
  combination), `paths` (a probed subclass of `M68000CPU` against a declared
  list of behavioural paths), `lines` (`sys.settrace` over
  `src/m68000_python` for the corpus or, with `--suite`, the whole suite).
- Reproduced Aubrey's number: SingleStepTests/m68000 runs **38,019** of the
  45,815 defined first words; 7,796 never run (move 3,719, bcc 1,888, moveq
  618).  Every *field value* of every rule is sampled somewhere except 125
  BRA displacements; what is unrun is combinations, and only 18 (size x
  mode) combinations are unrun (17 of MOVE, 1 of ADDI), all absolute or
  PC-relative.  The 680x0 corpus runs 44,736.
- Paths the gate corpus never reaches: vector 4 (illegal), 5 (divide by
  zero), 9 (the trace exception itself), bus error, double fault, an address
  error during exception processing (I/N set), any interrupt, DBcc counting
  out, MOVEM with an empty or full mask, MULU/MULS by 0/$FFFF/$8000, the DIVU
  overflow boundary; and word/long operands at 0, 1, all ones, max positive
  or min negative (3 of 36 pairs for ADD.w, 2 for ADD.l).
- Timing: `paths` over all 317,500 cases is 7 s on PyPy; `lines` 14 s on
  CPython 3.14.4 (which runs this core at about 28 microseconds a case
  without transaction comparison).

### Gap tests (9604270)

- `tests/test_coverage_gaps.py`: 48 tests of what the manuals decide, flag
  expectations restated from PRM Table 3-18's boolean formulas, never from
  the core.  Undefined flags, unpredictable stacked PCs and one clock count
  the manual and the corpus disagree on are left open (docs/coverage.md).

### A core bug, found by the coverage gap (4206431 test, 8760315 fix)

- **Trace after an instruction that was never executed.**  With T set, an
  ILLEGAL word, an undefined word, a line 1010 or 1111 word, or a privileged
  instruction in user mode took its exception and then, at the next step, a
  trace exception.  UM 6.3.8 says no trace follows an instruction that is
  not executed because it is illegal or privileged; MAME 0.285's microcode
  (T3: `state_illegal_df`, `state_priviledge_df`, `state_linea_df`,
  `state_linef_df` clear the pending trace) and WinUAE (T2, read:
  `exception_check_trace` keeps it only for vectors 5-7 and 32-47) agree.
  Invisible to both corpora: the gate captures `final` before any trace
  exception and never compares the pending-trace state, and the 680x0
  corpus never sets T.
- 4206431 adds the test, failing in 6 cases; 8760315 routes the four
  exceptions through `_not_executed`, which marks the step untraced.  The
  whole suite (395 tests, all 317,500 gate cases) passes after it on CPython
  3.14.4 and PyPy 7.3.23.

### Mutation testing (2026-09-21)

- `scripts/mutate.py` (3d241c3, e7ffbcd): 176 mutants in 17 areas, each an
  anchored replacement applied to a copy of `src/m68000_python` in
  `/tmp/claude-1000`; `src/`'s SHA-256 checked before and after every run
  (unchanged, `0af9369809dc`). Phase 1: each mutant's corpus files plus
  every non-corpus test module (330 s, PyPy, 4 jobs, load 7-11); phase 2:
  the 8 survivors and the 11 mutants only new tests had killed, against all
  127 files and every module (103 s); phase 3: the 8 survivors after tests
  were written for them (49 s); detector: the 3 final survivors against the
  680x0 files (nothing changes: those files hold no case these mutants
  touch).
- **Scores:** suite at e3629c1 158/176 (89.8%); with the coverage tests
  168/176 (95.5%); with the survivor tests 173/176 (98.3%), 173/174 without
  the two equivalent mutants. Weakest areas at e3629c1: division 60%, frame
  82%, overflow, prefetch and masking 80%. Details: docs/mutation.md.
- **Survivors of the whole suite (phase 2):** N7, M8 (both shown equivalent
  after the run: N7 exhaustively over 256 bytes, M8 by six programs across
  the 32-bit wrap), M3, D7, D9, SP12, CY10 (holes the manuals, or for CY10
  MAME, close: tests in `tests/test_mutation_survivors.py`, e8653f6), and
  D10 (the DIVS-by-zero flags: undefined in PRM, open).
- A mistake of mine, caught by the detector phase: the first coverage probe
  ran 680x0 cases on the m68000 corpus's word-addressed host, so its 680x0
  path counts were wrong (199 divide-by-zero cases reported; there is 1).
  Fixed in e7ffbcd; no committed document had used the wrong numbers.

### Closing the encodings (2026-09-21)

- `tests/test_register_renaming.py` (f8982e1, a7e3079): register renaming
  is a symmetry the manual implies (PRM 2.2 defines every mode on a generic
  n; only A7 is special). 35,981 words are compared with their canonical
  twins and 1,559 with their 0 <-> 7 twins, from random states, on every
  register, SR, stack pointer, PC, clock and bus access.
- `tests/test_coverage_gaps.py` grew: every Bcc word taken and not taken;
  the last 40 words (byte (A7)+/-(A7), absolute-only operands) against a
  model of PRM 2.2's effective addresses; the host-contract edges; one
  ordinary operand value beside the boundaries.
- Result: the suite executes **all 45,815 defined first words** (the gate
  38,019); of the 7,796 the gate misses, 3,345 are renamings of words it
  runs. Every declared behavioural path is reached, every achievable flag
  outcome of ADD/SUB/CMP/ADDX/SUBX/logic occurs, all 36 operand-class pairs
  at each size; 1,442 of 1,466 core statements run, the rest import-time
  code, defensive asserts and 4 dead lines. docs/coverage.md.
- Suite: 415 tests, CPython 3.14.4 about 11 s, PyPy 7.3.23 about 14 s (the
  corpus gate included), on the loaded machine.

## Referees (2026-09-21)

The brief for this session (from Aubrey, 2026-09-21): turn "T2 by reading"
into running.  Build WinUAE's 68000 core (the T2 referee) and Musashi (an
independent T3 lineage), calibrate each against the gate before trusting
it, put every open question to them, and re-derive the rung 5 table by
running.  Hard rules: no majority vote; no core change that would break the
gate; a gate-conflict inside WinUAE's checked scope goes to Aubrey; a core
bug the gate does not pin gets a failing test commit, then a fix commit;
nothing third-party committed.

### Building (b3ac8ed)

- `validation/referees/build_referees.py` fetches WinUAE `1977af50` and
  Musashi `313ebf1b` as GitHub archives into ignored `src/` and builds into
  ignored `build/` (about 20 s, 8 jobs, `nice`).  WinUAE: its CPU tester's
  own 68000 core (gencpu with CPU_TESTER on -> `cpuemu_90_test.cpp`), driven
  by `winuae_referee.cpp`, which `#include`s the tester's `cputest.cpp`.
  Two Unix adjustments, made to copies: od-unix's inline `cctrue()`, and a
  char overload for `wprintf`.  Hatari (same lineage) was not built.
- Harness bugs found and fixed while calibrating, before any use: frames
  built through the 24-bit mask landed at $3FA (test region now ends 1 KB
  short of 16 MB); Musashi's first `m68k_execute` spends the reset's clocks;
  a STOP left Musashi stopped for the next case; a vector-fetch detector
  misread MOVEM (xxx).W's reads of low memory as an exception; the tester's
  bus-error check compares 32-bit addresses.

### Calibration (docs/referees.md)

- WinUAE vs the gate: **308,416 / 314,988 judged cases agree**; the 6,572
  others are address errors and 2-clock differences in six named classes,
  none an ordinary case.  vs CLK where core and CLK agree: 779,253 /
  779,253 judged.  56 s (PyPy).
- Musashi vs the gate: **257,300 / 261,894 judged**; every difference is an
  undefined or disputed rule a higher tier decides (BCD N/V, DIV overflow
  and CHK flags, LINK A7, three line F words).  vs CLK: 807,147 / 821,973.

### Questions and the 680x0 table (c7e019e)

- `questions.py`, `rerun_680x0.py` (all 1,000,060 cases, 124 s with 4
  jobs), `bus_errors.py` (400,041 injected faults over the gate's states,
  154 s).  Results in docs/referees.md; validation.md's rung 5 table has a
  new column, what running WinUAE said, row by row.

### Tests and two core bugs

- 4ea03cf: `tests/test_referee_evidence.py`, T2 by running inside
  cputest's scope: divide-by-zero flags (kills mutant D10), CHK with Dn =
  0, illegal words' PC and clocks, 7 bus-error frames.
- **TRAPV's IR** (6ec31b4 test, e057279 fix): a taken TRAPV refilled the
  queue and handed the next opcode to the decoder before stacking its
  frame, so a fault during the trap (odd vector) stacked the next opcode as
  IR.  WinUAE (run, ODDEXC scope) and MAME's microcode (read) keep TRAPV.
  The gate has no such case.
- **TAS and BERR** (309f09e test, 36862e5 fix): a BusError raised by the
  host on TAS's write half escaped `step()` instead of becoming the bus
  error exception (UM 6.3.9.1; the host contract).  Found when the
  bus-error sweep crashed on it.
- Suite: 448 tests pass on CPython 3.14.4 and PyPy 7.3.23, the 317,500 gate
  cases included.

