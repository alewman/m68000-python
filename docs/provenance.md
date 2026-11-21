# Provenance

Audit of 2026-11-13 (provenance audit wave 1), against the family charter's
"Licences and provenance" rules: nothing copied or transcribed from GPL, LGPL
or unlicensed code; facts about the chip are not code; other emulators may be
run as closed boxes; permissive sources are used with their notice kept.

No GPL source was opened for this audit. Evidence is this repository's own
records (docstrings, `docs/`, `docs/history/worklog.md`, commit messages) and
the licence headers of the references. `provenance_check.py` was run against
the two permissive references only (below).

Verdicts: **clean** (own work from facts or permissive sources, cited);
**cite** (clean, but a source must be named or a notice kept); **rewrite**
(derived from code we may not take); **unclear** (what would settle it).

## Summary

| Verdict | Count |
| --- | ---: |
| clean | 12 |
| cite | 4 |
| rewrite | 3 |
| unclear | 1 |

After wave 2 (2026-11-19): the three `rewrite` rows are rewritten or moved
out, the `unclear` row is rewritten from closed-box results (accepted by the
owner), and the second-pass `unclear` item (MAME's header-less m68000
files) is resolved: every piece that rested on reading them is re-sourced
to permitted evidence, two unpinned steps are removed, and the decoder
check moved to Musashi (below, "Wave 2, second pass"). No `rewrite` or
`unclear` row remains.

## The core (`src/m68000_python/`)

| Piece | Where its behaviour came from | Source licence | Verdict |
| --- | --- | --- | --- |
| `_dispatch.py` opcode map (`RULES`) | PRM section 8. Until 2026-11-19 checked against MAME 0.285's `m68000.lst`, which has no licence header (GPL-2.0+); now checked against Musashi's decoder (`scripts/check_decoder_vs_musashi.py`: 45,799 + 19,721 words agree, 16 known differences decided by the PRM) and SingleStepTests/680x0's `map/68000.official.json` (19,721 undefined, `tests/test_dispatch.py`). The map is PRM bit patterns in opcode-map order, not the listing's structure. | Motorola manual; Musashi MIT | **clean** (re-sourced 2026-11-19) |
| `_ea.py`, `_flags.py`, `_loads.py`, `_bits.py`, `_shifts.py`, `_control.py` | PRM/UM tables; bus order, idle clocks and undefined results from SingleStepTests/m68000 (MIT), which records every access in order with its function code, the prefetch pair and the clock total, and `step_clocks` pins each idle step's position. The 2026-09 build also read MAME's header-less microcode files (GPL); every hidden-state step they could have placed was ablated one by one (`scripts/ablate_hidden_state.py`): see "Wave 2, second pass". | PRM/UM; SST MIT; closed-box runs | **clean** (re-sourced 2026-11-19; two unpinned steps removed) |
| `_core.py` prefetch, exception entry, address-error frames | UM (frame layout, Figure 6-7; double bus fault, 5.4.4); SST for the queue, push order, the 12 clocks of a group 0 entry, the stacked PC and IR, the halfway flags (every address-error case of the corpus); group 2 I/N clear OBSERVED from WinUAE's tester core run as a closed box. The MAME microcode reading is no longer relied on: wave 1's "cite MAME's m68000 core" assumed the whole directory was BSD-3. | UM; SST MIT; closed box | **clean** (re-sourced 2026-11-19) |
| `cpu.py` interrupt entry, autovector E-clock wait (`vpa_sync` + 1) | The E-clock rule as MAME 0.285's `m68000.cpp` states it (BSD-3-Clause header, Olivier Galibert; restated in our words, no code reproduced); the entry's write order and clocks OBSERVED from the MAME lockstep run as a closed box (1,791 System 16B entries with every frame write checked in order, all ten E-clock phases); the sequence UM 6.3.2 and the 44 clocks UM Table 8-14. The trace and interrupt entries' hand-over of IR to the decoder is the core's own model (HYPOTHESIS; UM 6.2.5 calls those frames unpredictable). | BSD-3-Clause (cited in NOTICE); closed box; UM | **cite** (done: NOTICE, docstring) |
| `_alu.py` ALU, MULU/MULS clocks | PRM, UM Table 8-4 (38 + 2n) | manual | clean |
| `_alu.py` `divide_unsigned_clocks`, `divide_signed_clocks` | **Rewritten 2026-11-19 (wave 2).** The old bodies (Jorge Cwik's algorithm as carried in WinUAE, GPL-2.0+) were moved aside unread. The new rule is a 16-step shift-and-subtract division whose step costs and constants were FITTED to every SingleStepTests/m68000 DIVU/DIVS case that divides (3,064 cases, 0 unexplained; `scripts/fit_divide_clocks.py`), inside UM Table 8-4's maxima (DOC). MAME's microcode was not used: the generated handler files and `m68000gen.py` carry no BSD header (below). Musashi gives only the fixed maxima. One HYPOTHESIS: whether DIVS quotient bit 15 counts (only a quotient of exactly -32768 would show it). | SST MIT; UM | **clean** (FITTED, DOC) |
| `_system.py` `_divide_by_zero` flags | **Rewritten 2026-11-19 from the recorded closed-box results** (`tests/test_referee_evidence.py`: WinUAE's tester core run 2026-09-21; re-run on the 680x0 detector's one DIVU-by-zero case 2026-11-19, = core) after the old body was moved aside unread; the trap and clocks from UM 6.3.5 and Table 8-14. No permitted document defines N, Z, V (PRM Table 3-18: undefined; C cleared) and neither SST corpus judges it (m68000 has no case; 680x0's one case clears N where WinUAE and the core set it: written down, not followed). | closed-box run (OBSERVED, WinUAE `1977af50`); UM | **OBSERVED; accepted by the owner 2026-11-19** (resting it on a closed-box run is acceptable) |
| `_system.py` CHK flags, TRAPV IR, trace rules | SST CHK etc. (T3), WinUAE run (closed box, T2), UM | MIT; closed box | clean |
| `_bcd.py` ABCD/SBCD/NBCD | The mechanism (uncorrected/corrected byte, V from the correction) as `docs/undocumented-behavior.md` describes it from Musashi's `m68k_in.c`; results gated by the table from running flamewing's GPL-3.0 generator locally (only its SHA-256 is committed). The 2026-09-12 plan said "port flamewing's BCD table generator (read from the pinned commit, not copied)"; the rung-2 record says `_bcd.py` was written from the doc, "not copied from the verifier". | Musashi MIT; flamewing GPL-3.0 (run, hash only) | cite: name Musashi (Karl Stenerud, MIT) beside the mechanism in `_bcd.py`. Whether `bcd-gen.cc` was opened while writing is not recorded; the code matches Musashi's description, not a generator. |
| `disasm.py` | Text format follows MAME's `m68kdasm.cpp` (Karl Stenerud, BSD-3-Clause) so lines diff against MAME traces; mnemonics from PRM | BSD-3-Clause | clean (format only; provenance_check: no hits beyond condition-code names) |
| `conformance.py`, `debug.py`, `console.py`, `trace.py`, `state.py`, `__main__.py` | own work | — | clean |
| SPDX headers | none of the source files carries `SPDX-License-Identifier: MIT` | — | cite: add the header family-wide (charter rule 2) |

## Validation, tests and fixtures

| Piece | Source | Licence / terms | Verdict |
| --- | --- | --- | --- |
| SingleStepTests/m68000 @ `64b25311` | fetched by `scripts/fetch_test_vectors.py`, not committed | MIT (Copyright (c) 2024 SingleStepTests) | clean |
| SingleStepTests/680x0 @ `e0d5ece9` (Tom Harte, CLK) | fetched, not committed | no licence stated | clean (run only, nothing committed) |
| flamewing/68k-bcd-verifier @ `39a01be` | built and run locally; only the SHA-256 of its table is in `tests/test_bcd.py` | GPL-3.0 | clean (closed-box output, hash only) |
| `tests/disasm_mame.txt` | MAME 0.285 disassembler output | output of a BSD-3-Clause disassembler | clean |
| `examples/conformance/*` | generated by this core | — | clean |
| `validation/lockstep.*`, `mame_trace.py` | MAME 0.285 run as a closed box (`/usr/games/mame`), ROMs via `-rompath`, never committed | — | clean |
| `validation/referees/musashi_referee.c` | own driver linking Musashi (fetched) | Musashi MIT | clean |
| `validation/referees/winuae_referee.cpp`, `winuae_shim.*`, the WinUAE half of `build_referees.py` | **Moved out 2026-11-19** to a separate local tool, `m68000-winuae-referee` (GPL-2.0-or-later LICENSE, SPDX headers, README crediting WinUAE; outside this repository, never shipped). `referee.py` runs its binary through `WINUAE_REFEREE`; the Oracles workflow no longer builds it. Binary rebuilt there byte-identical; calibration unchanged (308,416 / 314,988). | GPL-2.0-or-later (the tool) | **resolved** (out of the MIT tree; still in history, `v0.1.0` and the 0.1.0 sdist) |
| `docs/undocumented-behavior.md`, `docs/validation.md`, `docs/referees.md`, `docs/timing.md` (and `coverage.md`, `mutation.md`, test and core docstrings) | **Rewritten 2026-11-19**: the quoted WinUAE code fragments, code comments and function names are gone; each behaviour is stated in prose with its permitted source (the gate, the UM, or the closed-box run, tagged OBSERVED). The 680x0 table's "Explained by" column now names the gate or the manual. The record that WinUAE's source was read before 2026-09-21 is kept as history. `docs/history/` and `docs/handoff-polish.md` are left as written (dated records). | — | **clean** |

## provenance_check runs (2026-11-13)

- `provenance_check.py --repo src --reference validation/referees/src/musashi-313ebf1bd9f4`
  (Musashi, MIT): 2 file pairs, `_flags.py` condition-code names only. Clean.
- `provenance_check.py --repo src --reference <mame0285 src/devices/cpu/m68000/{m68000.cpp,m68000.h,m68000gen.py,m68000.lst,m68000-head.h,m68kdasm.cpp,m68kdasm.h}>`
  (fetched to a scratch directory, then believed BSD-3-Clause): 1 file pair,
  the same condition-code names. Clean. Note (2026-11-19): `m68000gen.py` and
  `m68000.lst` in that list have no licence header and are GPL
  (`m68000-head.h` was not checked and is treated the same); the similarity tool compared them mechanically and found nothing
  in common with this source, which is evidence that nothing was copied;
  they are not to be fetched again.
- Not run against WinUAE or flamewing (GPL).

## History

Public repository (alewman/m68000-python); PyPI `m68000-python` 0.1.0.

| What | Introduced | Where it is |
| --- | --- | --- |
| Cwik/WinUAE divide clocks in `_alu.py` | `66d373f` (2026-09-19) | every branch (`main`, `conformance-kit`, `polish-0.1.0`, `reset-40-clocks`, `table-at-class`, all on origin), tag `v0.1.0` (`f557abf`), PyPI 0.1.0 sdist and wheel |
| WinUAE code fragments in docs | `1c908b0` (2026-09-12) | every branch, `v0.1.0`, 0.1.0 sdist |
| `winuae_referee.cpp` with reproduced cputest code | `b3ac8ed` (2026-09-21) | every branch from then, `v0.1.0`, 0.1.0 sdist |
| `divbyzero_special` cited in code | `979c928`, `a44c0f7`, `4ea03cf` | as above |

No deleted file carried third-party code (`benchmarks/speed.py`,
`tests/test_tooling.py` were own work). Tag `v0.1.0` names its tagger
by full name (a privacy item, not a provenance one).

Downstream: m68000-rust, m68000-rust-fast (and through it megadrive-rust-fast
and the play-md site build) carry the same divide clocks.

## Citation-only fixes made in this audit

None.

## Wave 2 (2026-11-19): what was done

In place: the flagged pieces were a function pair, one method, one driver
and some document fragments. Each was moved aside without being displayed
(`trash/`, git-ignored, never read) and rewritten from permitted sources.
Nothing by Jorge Cwik or from WinUAE's source was read; WinUAE was only run.

| Gate | Before | After |
| --- | --- | --- |
| SST DIVU / DIVS (cases / cycles agree) | 2,500 / 2,500 each | 2,500 / 2,500 each |
| Judged divide cases (cases that divide) | 3,064 agree | 3,064 agree |
| Old vs new clock functions, run side by side | — | 0 differ in 882,215 inputs (random, small quotients, quotient -32768) |
| Old vs new divide by zero (SR, PC, clocks, frame) | — | identical on 72,192 probes |
| SST gate, all files + `step_clocks` | 317,500 / 317,500 | 317,500 / 317,500 (257 tests) |
| Fast suite | pass | 2,090 passed |
| 680x0 detector (`classify_680x0.py`) | 787,660 / 1,000,060 | 787,660 / 1,000,060 |
| WinUAE calibration (from the moved tool) | 308,416 / 314,988 | 308,416 / 314,988 |
| Mutants D4, D5, D6, D8, D9, D10 (rewritten against the new code) | killed | killed |

Tests: none encoded the flagged clocks except the corpus; the three
divide-clock mutants (D5, D6, D8) and the three divide-by-zero mutants
(D4, D9, D10) quoted the old code and were rewritten against the new.

### Wave 2, second pass: MAME's header-less m68000 files (2026-11-19)

**The finding.** MAME's `m68000.cpp` and `m68000.h` carry
`license:BSD-3-Clause` (Olivier Galibert; checked by fetching only those
two files), but `m68000gen.py`, `m68000.lst` and the generated handlers
(`m68000-sdf.cpp`, `m68000-sif.cpp` and siblings) carry no licence header,
so under MAME's COPYING they are GPL-2.0+. Wave 1 assumed the whole
directory was BSD-3. From now on those files are not opened.

**What rested on them** (from this repository's own records; the MAME files
were not opened for this pass). The worklog (2026-09-18, "Reference material
read but not copied") says `m68000-sdf.cpp`, `m68000.lst` and `m68000gen.py`
were read "to understand bus-access order where the corpus leaves it
ambiguous", and the decoder was checked against `m68000.lst` by a scratch
script (later `scripts/check_decoder_vs_mame.py`). The code and documents
cited the microcode for: the bus order and idle clocks of every handler;
the steps where the PC an address error stacks is brought up to date; the
decoder's opcode hand-overs (IR in a group 0 frame); a long's halfway
flags; the order of a long write's halves; CHK's bound order; DIVU's
overflow flags; group 2 I/N (worklog question 17: "MAME 0.285's microcode
(T3, read ... without SSW_N)"); TRAPV's IR (`trpv3`); no trace after an
unexecuted instruction ("the nanocode's trace-pending bit"); the double bus
fault ("MAME takes another address error"); interrupt entry order ("MAME
0.285's order"). The E-clock wait cites `m68000.cpp`, which is BSD-3.

**Structure.** The handlers are per-instruction Python functions in the
family's module shape, named after PRM mnemonics, with the hidden state
expressed as four plain fields (`_fault_pc`, `_opcode`, the CCR halves,
the write order). No microcode or nanocode state names, addresses, tables
or sequencing structure appear in the code; the only microcode names in the
tree were in comments (`trpv3`, `SSW_N`, "IRD", "the nanocode's
trace-pending bit"), now gone. So each behaviour was judged by whether
permitted evidence pins it.

**How "pinned" was shown.** SingleStepTests/m68000 (MIT) records every bus
access in order with its function code, the prefetch pair and the clock
total, and `step_clocks` is checked at every access end of 261,894 cases,
so bus order and idle-clock positions are pinned wherever the corpus
reaches. The hidden state an address error exposes is pinned only if
moving it breaks a case, so `scripts/ablate_hidden_state.py` removes each
site one at a time in a copy of the core and runs all 317,500 cases:

| Sites (43 before this pass) | Removed or swapped, then the whole corpus | Verdict |
| --- | --- | --- |
| 24 of the 26 `_commit_pc` calls, the `_control.py` jump target, 10 halfway-flag calls, 2 `_write_long_low_first` | 37 sites: some case fails for every one | **pinned by SST** (MIT): clean |
| `_bcd.py` ABCD/SBCD `-(An)` commit, `_bits.py` immediate bit-number commit | corpus passes (byte operands: only a bus error can see the step) | **OBSERVED**: WinUAE's tester core run as a closed box (`validation/referees/bus_errors.py`) agrees with the step: ABCD+SBCD read faults 2,514 / 2,514 with it, 0 without; BTST/BCHG/BCLR/BSET read 6,754 with it against 6,199 without, prefetch 4,731 against 3,619. Kept. |
| `_loads.py` MOVE.L -(An) hand-over after the first write; PEA hand-over after its push | corpus passes; WinUAE bus-error sweep identical with and without | **not pinned by anything**: removed (the decoder takes IR at the boundary, as everywhere else) |
| `cpu.py` trace-entry and interrupt-entry hand-over | corpus passes (no case faults inside those entries) | the core's boundary model (HYPOTHESIS; UM 6.2.5: unpredictable). Kept. |

The rest, behaviour by behaviour:

| Behaviour | Permitted evidence now | Verdict |
| --- | --- | --- |
| Bus order, idle clocks, address-error stacked PC/IR/flags/registers, CHK bound order and flags, DIVU/DIVS overflow flags, RTE/RTR read order, FC of PC-relative reads | SST, every case (and the ablation above) | clean (T3, SST MIT) |
| No trace after an unexecuted instruction | UM 6.3.8 | clean (DOC) |
| Double bus fault halts | UM 5.4.4 | clean (DOC); the MAME claim is dropped |
| Group 2 I/N clear | WinUAE's tester core run (ODDEXC), `tests/test_coverage_gaps.py` | OBSERVED; now **provisional** in claims.md (was "strong" with the read as the second lineage) |
| TRAPV's IR in a nested fault | WinUAE's tester core run, `tests/test_referee_evidence.py` | OBSERVED |
| Interrupt entry: write order and clocks | UM 6.3.2, Table 8-14; the MAME lockstep run as a closed box (every frame write checked in order, clocks at all ten E-clock phases) | OBSERVED + DOC |
| E-clock wait of an autovector | MAME `m68000.cpp` (`vpa_sync`, `vpa_after`; BSD-3-Clause header verified 2026-11-19), stated in our words; lockstep | cite (NOTICE) |
| Decoder | PRM; Musashi's decoder (MIT), `scripts/check_decoder_vs_musashi.py` | clean |

**Removed unread:** the local copy of `m68000.lst`
(`validation/mame/mame0285-m68000.lst`, fetched by the old check) and
`scripts/check_decoder_vs_mame.py` were moved to `trash/header-less-mame/`
(git-ignored) without being displayed. No code was transcribed from the
header-less files (provenance_check found no hits in wave 1), so no core
code needed removing beyond the two unpinned hand-overs.

| Gate | Before | After |
| --- | --- | --- |
| SST gate, all files + `step_clocks` (`pytest -q`, whole suite) | 2,218 passed (317,500 / 317,500) | 2,218 passed (317,500 / 317,500) |
| Fast suite (corpus and `step_clocks` deselected) | 1,961 passed | 1,961 passed |
| 680x0 detector (`classify_680x0.py`) | 787,660 / 1,000,060, table unchanged | 787,660 / 1,000,060, table unchanged |
| Decoder | vs `m68000.lst`: 0 of 65,536 differ (retired) | vs Musashi: 45,799 + 19,721 agree, 16 known (PRM), 0 unexpected |
| WinUAE bus-error sweep, all gate files (read / write / prefetch agree) | 87,930 / 97,354; 23,327 / 70,378; 76,792 / 232,309 | identical, line for line |
| Hidden-state ablation | 37 of 43 sites pinned by SST | 37 of 41 pinned; the other 4 as the table says |
| Downstream: m68000-rust rungs 1-6 (MAME lockstep replays through it, rung 3) | all pass; replays 24,597,382 + 28,253,448 records identical | the same (m68000-rust `006c147`); m68000-rust-fast `ladder.sh` clean (`cd530fd`) |

**Behaviour change:** one, outside the contract. A bus error on the second
write of MOVE.L to `-(An)` (possible only when a host's BERR region covers
the lower word but not the upper) now stacks the MOVE as IR instead of the
next opcode. PEA's hand-over had no observable effect at all.

Downstream: m68000-rust (`src/alu.rs`) and m68000-rust-fast carry the
rewritten functions (their own `docs/provenance.md`); megadrive-rust-fast
needs a repin and play-md a rebuild and redeploy.

