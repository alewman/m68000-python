# Mutation testing: what the suite would notice

A passing suite says the core agrees with its tests. It does not say how
much a wrong core would have to differ before a test noticed. Mutation
testing measures that: seed one small semantic change into the core, run
the suite, and see whether anything fails. A mutant that no test fails
*survives*, and a survivor is a hole in the evidence -- behaviour the core
could get wrong without anything in this repository saying so. The list of
survivors is the result; the score is a summary of it.

This measures the **suite**, not the core. Nothing here changes
`src/m68000_python/`: every mutant is applied to a copy.

## How it was run

`scripts/mutate.py` (commits 3d241c3, e7ffbcd). Each of 176 mutants is an
anchored textual replacement in one file of the core -- a comparison off by
one, a mask dropped, a sign extension removed, a stacked PC moved by two, a
clock count changed -- written before the first run and not changed after
it. For each mutant the harness copies `src/m68000_python` into a scratch
directory under `/tmp/claude-1000`, applies the replacement (which must
match exactly once after its anchor), and runs the suite in a child process
that first checks it imported the copy. The SHA-256 of `src/` is taken
before and after every run and was unchanged (`0af9369809dc...`).

What each mutant ran against is recorded per mutant in the results file:

| Phase | Mutants | Run against |
| --- | --- | --- |
| 1 (`run`) | all 176 | the SingleStepTests/m68000 files named in the mutant's `corpus` field (every case, compared exactly as `tests/test_corpus.py` compares them; a file stops at its first failing case), plus every test module except `test_corpus.py` (at that point: test_bcd, test_coverage_gaps, test_dispatch, test_interrupts, test_readability, test_tooling) |
| 2 (`escalate`) | the 8 phase-1 survivors, and the 11 mutants that only the session's new tests had killed | all 127 gate files, plus every test module (now also test_register_renaming) -- the whole suite as of f8982e1 |
| 3 (`recheck`) | the 8 phase-2 survivors | all 127 gate files, plus every test module, now also test_mutation_survivors (written for the phase-2 survivors) |
| detector (`detect`) | the 3 final survivors | the matching SingleStepTests/680x0 files, case by case against the unmutated core |

Escalating the mutants that only new tests killed matters for the "suite at
e3629c1" column below: a phase-1 subset is narrower than the gate, and one
of those eleven, Z3, turned out to be caught by gate files outside its
subset (NEGX.b). An unmutated copy passed each phase's subset before
the phase ran (phase 1: the 115 gate files some mutant names, and 6
modules; phases 2 and 3: all 127 files and 7 or 8 modules).

PyPy 7.3.23 (Python 3.11.15), `nice -n 10`, four mutants at a time, on the
shared 32-core machine at a load average of 7 to 11. Phase 1: 330 s wall
(median 6.9 s a mutant); phase 2: 103 s; phase 3: 49 s; detector: 2 s. A
mutant run that hangs past 600 s would count as killed and be listed as a
timeout; none did.

## Scores

Killed, by the suite at three points: as it stood at e3629c1 (the gate and
the tests that existed then), with this session's coverage tests
(tests/test_coverage_gaps.py and tests/test_register_renaming.py), and with
the tests written for the phase-2 survivors
(tests/test_mutation_survivors.py).

| Area | Mutants | Suite at e3629c1 | + coverage tests | + survivor tests | Survivors | Equivalent |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| BCD correction | 6 | 6 (100%) | 6 (100%) | 6 (100%) | - | |
| carry | 10 | 10 (100%) | 10 (100%) | 10 (100%) | - | |
| cycle counts | 17 | 16 (94%) | 16 (94%) | 17 (100%) | - | |
| conditions | 2 | 2 (100%) | 2 (100%) | 2 (100%) | - | |
| division | 10 | 6 (60%) | 7 (70%) | 9 (90%) | D10 | |
| effective address | 12 | 12 (100%) | 12 (100%) | 12 (100%) | - | |
| extend | 8 | 8 (100%) | 8 (100%) | 8 (100%) | - | |
| stacked PC and frame | 17 | 14 (82%) | 17 (100%) | 17 (100%) | - | |
| word/long masking | 10 | 8 (80%) | 8 (80%) | 9 (90%) | M8 | M8 |
| negative | 8 | 7 (88%) | 7 (88%) | 7 (88%) | N7 | N7 |
| overflow | 10 | 8 (80%) | 10 (100%) | 10 (100%) | - | |
| prefetch queue | 10 | 8 (80%) | 10 (100%) | 10 (100%) | - | |
| results (other) | 14 | 13 (93%) | 14 (100%) | 14 (100%) | - | |
| shifts and rotates | 9 | 9 (100%) | 9 (100%) | 9 (100%) | - | |
| sign extension | 13 | 13 (100%) | 13 (100%) | 13 (100%) | - | |
| supervisor and stack pointers | 12 | 11 (92%) | 11 (92%) | 12 (100%) | - | |
| zero | 8 | 7 (88%) | 8 (100%) | 8 (100%) | - | |
| **all** | **176** | **158 (89.8%)** | **168 (95.5%)** | **173 (98.3%)** | 3 | 2 |

Excluding the two mutants shown to be equivalent, the final score is 173 of
174 (99.4%). The mutant list itself is `python scripts/mutate.py list`.

What the numbers do and do not say:

- The gate corpus is strong where it reaches: it alone killed 87 mutants,
  and it took part in killing 154. Every carry, extend, sign-extension,
  shift, BCD and effective-address mutant died on the corpus as it stood.
- Its holes are where its cases never go (docs/coverage.md): the trace
  exception itself, divide by zero, bus errors, the I/N bit, DBcc running
  out, word/long operands at their boundaries, the host-facing entry points
  (`set_pc`, `set_ipl`). The suite at e3629c1 let 18 mutants through; the
  session's new tests kill 15 of them (listed below), and 3 survive.
- A mutation score is only as good as the mutant population. These 176 are
  one person's guess at plausible mistakes, one per line, in the areas the
  brief named; a different population would give a different number. The
  score is not a probability that the core is right.

## Survivors

### After the whole suite (phase 2): 8

| Id | Area | Mutation | Why it survived | Resolution |
| --- | --- | --- | --- | --- |
| N7 | negative | `EXT.W` takes N and Z from the byte instead of the word | nothing can tell: see "Equivalent" | **equivalent** |
| M8 | masking | the fetch address is not wrapped to 32 bits after an extension word | nothing can tell: see "Equivalent" | **equivalent** |
| M3 | masking | `ADDQ`/`SUBQ #,An` without the 32-bit mask | no case carries An across 0 or $FFFFFFFF | test written (PRM 4-11); killed in phase 3 |
| D7 | division | `DIVU` 0/0 does not trap | every divide-by-zero test had a nonzero dividend | test written (PRM 4-96); killed |
| D9 | division | divide-by-zero entry 4 clocks short | the gate has no divide by zero; no test asserted its clocks | test written (UM Table 8-14: 38 + EA); killed |
| D10 | division | `DIVS` by zero sets N where the core sets Z | the flags are undefined in PRM, and no test asserts them | **killed 2026-09-21** by tests/test_referee_evidence.py (WinUAE's tester core, run: T2), below |
| SP12 | supervisor | level 7 re-taken each time the host sets 7 again | the scenario set the level once | test written (UM 6.3.2); killed |
| CY10 | clocks | E-clock wait boundary moved from phase 7 to 8 | the existing phase test accepts any varying set (see below) | test written (MAME 0.285, T3); killed |

### After the survivor tests (phase 3): 3

Phase 3 ran against the suite at e8653f6. After it, more coverage tests
were added (a7e3079, f6a61db); the eight phase-2 survivors were run again
against the whole suite at f6a61db, with the same result: N7, M8 and D10
survive, the other five are killed.

- **D10** (`_system.py`, `_divide_by_zero`): DIVS by zero with N set instead
  of Z. **A real hole, not decidable from the manuals.** PRM leaves the
  condition codes undefined after a divide by zero; the pinned gate has no
  divide-by-zero case (its issue #3); the 680x0 corpus has exactly one
  divide by zero, a DIVU, and none for DIVS, so the detector sees nothing
  (0 cases change). The core's rule is WinUAE's `divbyzero_special` (T2,
  read, not run). The same is true of the DIVU-by-zero flags, for which the
  population happened to have no mutant: no test asserts them either, and
  the one 680x0 case already disagrees with the core (CLK and WinUAE
  differ; docs/validation.md). What would settle both: running WinUAE's
  68000 core on DIVU/DIVS by zero across dividend signs and magnitudes (T2,
  run rather than read), or better, a hardware run -- transistorfet's
  68k-test-runner or WinUAE `cputest` on a real 68000.
  **Settled at T2, 2026-09-21:** WinUAE's CPU-tester core, built from the
  pinned source and run ([referees](referees.md)), gives the core's flags
  for DIVU and DIVS by zero on all 20 inputs tried (5 dividend shapes, CCR
  all clear and all set), inside the scope cputest checks on hardware.
  `tests/test_referee_evidence.py::test_divide_by_zero_flags` pins them;
  `scripts/mutate.py run --only D10` now reports D10 killed (65 s, PyPy).
- **N7** and **M8**: equivalent (below).

### Equivalent mutants

Shown equivalent *after* the run; they remain in the population and in the
raw score.

- **N7.** `EXT.W` stores the sign-extended low byte, so bit 15 of the word
  equals bit 7 and the word is zero exactly when the byte is: N and Z taken
  from the byte are N and Z of the word. Checked for all 256 bytes with both
  X values.
- **M8.** Every place the fetch address leaves the core masks it: the bus to
  24 bits, and the `PC` property, `capture_state`, stacked and pushed
  return addresses and every PC-relative computation to 32. Only the private
  attribute `_pc` can exceed 32 bits, and only after an extension word is
  taken at $FFFFFFFE. Six programs straddling the wrap (one taking an
  address error there, one pushing a JSR return address) gave identical
  registers, PC, captured state, memory and bus accesses on the mutant and
  the core. The gate harness compares `_pc` directly, but no corpus PC is
  anywhere near $FFFFFFFE.

## Killed only by the session's new tests

Mutants the suite at e3629c1 let through, with the tests that now kill
them. Each is a hole the old suite had.

| Id | Mutation | Killed by |
| --- | --- | --- |
| O14 | an illegal or privileged instruction is traced -- the core as it was before 8760315 | `test_no_trace_follows_an_instruction_that_was_not_executed` |
| P11 | the trace exception stacks the prefetch address | `test_the_trace_exception_is_taken_after_the_instruction`, `test_a_traced_trap_takes_the_trap_then_the_trace` |
| P7 | the group 0 I/N bit is never set | `test_an_address_error_inside_exception_processing_sets_i_slash_n` |
| P16 | bus errors vector through the address-error vector | `test_a_bus_error_takes_vector_two_with_the_group_zero_frame` |
| D4 | divide by zero stacks the instruction's own address | `test_divide_by_zero_takes_vector_five_and_leaves_the_dividend` |
| D7 | DIVU 0/0 does not trap | `test_divide_by_zero_traps_whatever_the_dividend` |
| D9 | divide-by-zero entry clocks | `test_exception_clocks_the_gate_never_measures` |
| V6 | DIVS calls a quotient of -32768 an overflow | `test_divs_at_the_signed_boundaries` |
| V7 | DIVU calls a quotient of $FFFF an overflow | `test_divu_overflow_at_the_boundary_leaves_the_operands_alone` |
| Z4 | a long's Z ignores bit 31 | `test_move_long_with_a_zero_low_word_is_not_zero` |
| Q8 | DBcc expiry does not skip its displacement word | `test_dbcc_falls_through_when_the_count_expires` |
| Q10 | `set_pc` leaves the fetch address a word short | most of test_coverage_gaps.py, which starts programs with it |
| M3 | ADDQ/SUBQ #,An unmasked | `test_addq_and_subq_to_an_address_register_wrap_at_32_bits` |
| SP12 | level 7 re-taken while held | `test_level_seven_held_and_reasserted_is_taken_once` |
| CY10 | E-clock wait boundary | `test_autovector_clocks_at_each_e_clock_phase` |

`python scripts/mutate.py report RESULTS.json` prints the same list with
every test that fails for each mutant.

## Findings along the way

- **A core bug** (4206431 test, 8760315 fix): not from a surviving mutant
  but from the coverage gap "trace after an exception": a traced illegal,
  line A/F or privilege-violating instruction was followed by a trace
  exception, contrary to UM 6.3.8. Mutant O14 re-introduces it; the old
  suite could not have caught it.
- **A weak existing test.** `tests/test_interrupts.py`,
  `test_autovector_wait_follows_the_e_clock_phase`, asserts
  `clocks == set(range(48, 58)) or len(clocks) > 1`. The range is off by one
  (the core, and MAME per the lockstep, give 49 to 58), so the first half is
  false and the test passes only because the clocks vary at all -- which is
  why CY10 survived it. A precise one was added beside it, and the old one
  was corrected to the exact set on 2026-09-21 (7e8237f).
- **CY14 was killed, and it matters.** CY14 gives `ADDQ.W #,An` the 4 clocks
  UM Table 8-5 prints; the gate killed it (118 cases say 8). The manual and
  the microcode-derived corpus disagree here, and the core follows the
  corpus (and WinUAE, T2); docs/coverage.md lists it.

## The anchors after the polish round (2026-09-25)

Nine mutants were re-pointed at code the polish round moved, with the
mutation itself unchanged: S4 (the brief-extension index) follows the
helper into `_ea._indexed`; S5, S6, S7, S8 and S11 mutate `word_to_long`
where they mutated the spelled-out sign extension; M8 and Q2 mutate the
fetch address `_extension` now computes as `address`; Q9's comment lost its
tier marker. The population is the same 176 mutants. The whole run was
repeated for the 0.1.0 certification record ([validation](validation.md)).

## Reproducing

```text
python scripts/mutate.py list
python scripts/mutate.py run --jobs 4 --out RESULTS.json
python scripts/mutate.py escalate RESULTS.json --jobs 4
python scripts/mutate.py recheck RESULTS.json --jobs 4     # after adding tests for survivors
python scripts/mutate.py detect RESULTS.json
python scripts/mutate.py report RESULTS.json
```

The corpus must be fetched (`python scripts/fetch_test_vectors.py`, with
`--with-680x0` for the detector). The results file is not committed. A
rerun reproduces the kills; its timings will differ with the machine's
load, and phase 1's list of test modules is whatever is in `tests/` when it
starts.
