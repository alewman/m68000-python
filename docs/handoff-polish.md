# Handoff: polish `m68000-python` to the z80-python bar

Written 2026-09-25 after a full read of the core, the tooling, the docs,
the tests and the CI, with the suite run (579 passed in 20 s on CPython
3.14, ruff check and format clean, CI green on `main` at `44c26f0`) and
the benchmark run. The question it answers is Aubrey's: *is this a project
we can be as proud of as z80-python, and if not, how do we close the gap?*

The honest answer: **the evidence is already prouder than z80's; the
project around it is not yet.** `docs/claims.md`, the WinUAE and Musashi
referees, the coverage map and the mutation score are the best-argued
correctness record in the family, and z80-python should inherit that shape
(a follow-up, not this brief). But the repository is still a groundwork
repo with a core dropped into it: four documents still speak of "the code
that does not yet exist", the README quotes a stale speed and a stale
mutation score, no handler names the corpus file that pins its undocumented
rule, the tooling has 172 lines of tests against z80's 1,003, there is no
changelog, release, example, contributing guide or API contract, and the
version is `0.1.0.dev0` on a private repository. z80-python looked like
this on 2026-09-18; one polish round fixed it. This is that round.

Do the items in order. Items 1-8 are the job; 9 is stretch, deferred by decision 2.

## The bar

Same as z80-python's brief, restated so nobody has to open it:

- every claim names its oracle and the oracle's tier in the sentence that
  makes it, and a reader can rerun the command that produced it;
- every handler says where its rule comes from, so a disagreement can be
  settled by opening the cited page or corpus file, not by trusting code;
- every deliberate divergence from an oracle is listed with the
  higher-tier source that decided it (claims.md already does this well);
- every number in the docs is current and regenerated, not remembered;
- nothing is kept that does not pay: a page, a test, a marker or a
  paragraph that does not move a number or settle a question is removed.

When an item as written falls short of the bar, do the better thing and say
so in the commit message; when meeting the bar exceeds the item's scope,
finish the item and record the gap in `CHANGELOG.md` under `[Unreleased]`.

## Context you are inheriting

- Repository `/data/emu/m68000-python`, PRIVATE as `alewman/m68000-python`,
  HEAD `44c26f0` (merge of PR #1, `step_clocks`), clean tree, version
  `0.1.0.dev0`. CI: `.github/workflows/ci.yml` runs pytest + ruff on
  3.11-3.14 + pypy3.11 and the SST corpus gate on 3.14 + pypy3.11 on every
  push (better than z80's weekly oracle run; keep that).
- Venv `.venv` (CPython 3.14.4); PyPy at `/data/emu/z80-python/.venv-pypy/bin/pypy3`
  (PyPy 7.3.20 / 3.11) works with `PYTHONPATH=src`. ruff `~/.local/bin/ruff`
  (0.14.0 locally; pyproject says `>=0.15`, see item 6).
- Oracles fetched and git-ignored: `tests/68000_test_vectors/m68000` (pin
  `64b25311`), `tests/68000_test_vectors/680x0`, referee builds under
  `validation/referees/build/`. MAME 0.285 lockstep needs the `altbeast`
  romset and a Genesis ROM that are not in the repo.
- Baseline, measured 2026-09-25: `pytest -q` **579 passed in 20 s**;
  `benchmarks/speed.py` **1.25-1.28 M instr/s** on CPython 3.14 (README
  says 0.6-0.7 M: stale).
- Gold standard to copy shapes from: `/data/emu/z80-python` at v0.4.0
  (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `docs/api-stability.md`, `docs/interrupt-lifecycle.md`,
  `docs/trace-comparison.md`, `docs/conformance.md`, `docs/ai-assisted-development.md`,
  `examples/minimal_z80_host.py`, `tests/test_public_api.py`,
  `tests/test_debug_session.py`, `tests/test_trace_comparison.py`,
  `tests/test_readability.py`, `benchmarks/compare_revisions.py`,
  `scripts/smoke_installed_package.py`, `.github/workflows/publish.yml`).
- Read first: `README.md`, `docs/claims.md`, `docs/validation.md`,
  `docs/worklog.md`, then every file under `src/m68000_python/` (4,607
  lines; read it all before changing any of it).

## Constraints

- **Every oracle passes unchanged after every item that touches `src/`**:
  the SST gate (`pytest tests/test_corpus.py tests/test_step_clocks.py`),
  BCD, the readability test, the referee-pinned tests. The 680x0 detector
  (`scripts/run_680x0.py`) and the referee calibration
  (`validation/referees/`) once at the end of item 7 and before item 8.
  The MAME lockstep once before item 8 if the ROMs are on this machine;
  if not, say so in the certification record rather than implying it ran.
- **Never change the core against the gate.** Contested rows in
  `docs/claims.md` stay contested; a T2-vs-gate conflict goes to Aubrey.
- The readability contract stays: `grep MOVEM src/` lands on the handler.
  Tables route to handlers; they never replace them.
- No runtime dependencies. PyPy stays green. `requires-python >= 3.11`,
  no 3.12+ syntax (the PyPy floor rule).
- Public API breaks are allowed only where an item below says so and are
  recorded under **Breaking** in `CHANGELOG.md` (nobody outside the family
  uses this package; megadrive-python does, so tell it).
- One commit per item (item 7 one per rung), authored as alewman with the
  session's Co-Authored-By line. Work on branch `polish-0.1.0`, push, open
  one PR, wait for CI, **merge and stop**. Tagging, making the repository
  public and publishing to PyPI are Aubrey's (item 8 prepares them).
- Never commit corpora, ROMs, MAME traces or referee builds.

## Decisions made (Aubrey, 2026-09-25: "go with your recommendations")

None of these is open. Items 7 and 8 run.

1. **Release and visibility: public, and to PyPI as `m68000-python` 0.1.0.**
   The bar is z80-python's, and a flagship is public. The worker prepares
   everything (item 6, item 8); Aubrey flips the repository to public, tags
   `v0.1.0` and lets `publish.yml` upload, in that order, after reading
   the merged result.
2. **Conformance kit deferred.** Item 5 fills `docs/trace-schema.md` and
   commits one reference trace under `examples/`. The manifest/diff module
   (item 9) waits for a planned 68000 port.
3. **Speed ladder runs in this round** (item 7), with the stop rule: a
   rung that gains under 5% on both interpreters is reverted.
4. **`parse_number`: decimal by default, `$` or `0x` for hex**, the z80
   rule (`z80_python.console.parse_number`); the `#`-decimal form goes.
   megadrive-python does not use the console, so nothing outside the repo
   changes. Record under **Breaking** in `CHANGELOG.md` anyway.
5. **`reset_devices` becomes a constructor keyword**,
   `M68000CPU(..., reset_devices=None)`, beside `acknowledge`, `tas_write`
   and `address_error`; the `getattr` lookup at `_system.py:264` goes, and
   `docs/interrupt-lifecycle.md` documents it with the others. No board
   uses the old attribute.
6. **Worklog question 6 is accepted as a lockstep artefact.** The i8751
   resets the 68000 through the mapper mid-instruction, which an
   instruction-level core cannot reproduce; the one-time register copy
   from MAME's next line is a limitation of the *comparison*, not a claim
   about the core. Record it in `docs/validation.md` rung 4 (how many
   times, which registers, which come from the core's own reset) and close
   the question.
7. **History pages move to `docs/history/`.** `handoff-brief.md` and
   `worklog.md` each get a one-line header saying they are records of how
   the core was built and verified, not contracts; the README and
   `docs/README.md` stop linking them as documentation; `claims.md` and
   `CHANGELOG.md` carry every decision that matters going forward.

## Item 1 — remove brief-era prose and stale numbers (half a day)

Four documents were written 2026-09-12, before the core, and never revised
for its existence. Fix every instance; the audit found these:

- `docs/start-here.md:1` "as this core **will** model it"; `:5` "the
  **future source**"; `:8-10` "the code **that does not yet exist**";
  `:377-379` "**will** let the host answer the acknowledge" (it does:
  `acknowledge=`); `:431-434` "treat statements ... `[unverified]` until
  the core reproduces the corpus" (it does, 317,500/317,500); `:445`
  reading order pointing at the handoff brief.
- `docs/timing.md:1` "clock counts the core **will** return"; `:6`, `:51`
  "future handlers"; **`:301-302` says address-error cases carry a
  50-clock frame push; claims.md and validation.md say 58, decided by
  WinUAE running.** Fix the number and cite the row.
- `docs/undocumented-behavior.md:8` "future handler comments"; `:231-233`
  "Where the truth **will** live / When the core exists"; `:58` and `:69`
  keep `[unverified]` on DIVU/DIVS-by-zero flags beside the 2026-09-21
  WinUAE run that settled them; `:315-318` calls the double-fault halt
  "untested" (a test exists: `test_coverage_gaps.py`,
  `test_a_fault_while_taking_an_address_error_halts_the_processor`);
  `:207-210` points at the handoff brief. Restructure the page z80's way:
  mechanism first, then the source line in `src/` that encodes it.
- `docs/mame-oracle.md:5` "the **future core**"; `:132` "the future
  lockstep comparer must decide" (validation.md rung 4 decided: `curpc`);
  `:155` "the future host".
- `docs/validation.md:284-285` BCD "is the **planned** T1 gate"; `:394`,
  `:444` "will".
- `README.md:33-36` "kills 173 ... one (DIVS by zero) is open": D10 was
  killed 2026-09-21; the score is 174/176 with two equivalent survivors
  (claims.md:200-203, mutation.md:106). `README.md:107-110` speed
  "0.6-0.7 M": regenerate (item 7 gives the method). `README.md:53-74`
  "What a pure-Python 68000 is" and the sentence "The handoff brief
  estimates the core at two to three times z80-python's size" (actual:
  4,607 lines): delete the section.
- `docs/worklog.md:78` question 7 "Nothing pushed" (pushed 2026-09-21);
  `:47-49` lists questions 1-6 as open while their resolutions sit 100
  lines lower. Apply decision 7: move the file, add a status column to
  the question list, mark 6 per Aubrey's answer.
- Code comments: `_core.py:166` cites `docs/handoff-brief.md`; `_core.py:510`
  cites `docs/worklog.md` for the double-fault rule. Both point at
  `docs/claims.md` after this item.

## Item 2 — handler citations to the z80 bar (one day)

All 86 `_op_*` handlers cite a PRM or UM page (86/86). None names the
SingleStepTests file that pins a rule the manuals do not give: `.json`
appears zero times in `src/`, while "(T3)" or "(corpus, T3)" appears 32
times (loads 9, core 6, system 5, alu 4, control 3, ea 2, bits, bcd,
flags 1 each). z80 names the file on every WZ/Q line, and its readability
test enforces it.

- Replace every bare "(T3)" with the corpus file(s) that pin the rule
  (`_ea.py:74` (xxx).W/L and PC-relative commit points; `_control.py:88`
  DBcc odd-target rule; `_loads.py:79`, `:84`, `:164` (xxx).L write order;
  the fault-PC commits in `_core.py`; the idle clocks in `_system.py`).
  Where the pin is WinUAE-run rather than the corpus, say
  "(WinUAE run, T2; referees.md §…)". Where a rule is contested, the
  docstring says "contested, follows the gate (claims.md)".
- Fix the weak ones: `_alu.py:203` `_op_and` and `:207` `_op_or` cite no
  UM timing table (their sibling `_op_add` does); `_loads.py:190`
  `_op_moveq` asserts "4 clocks" with no source; `_system.py:245`
  `_op_reset` says 124 clocks while the code adds 128 + 4 (state the UM
  Table 8-12 relationship); `_system.py:227` `_op_stop` gives no source
  for the 4 idle clocks; `_op_divs` cites PRM only while
  `divide_signed_clocks` (`_alu.py:70`) carries the Cwik T2 citation.
- Tighten `tests/test_readability.py` to z80's grammar: the citation
  closes the headline; the pattern is `(PRM <page>)`, `(UM <table|section>)`,
  `(SST <file>.json)`, `(WinUAE run, referees.md §n)`, and combinations,
  so "(PRM 4, MOVE)" no longer passes; any handler that reaches, directly
  or through a helper, a fault-PC commit, an undefined-flag rule, a bus
  order rule or an idle-clock constant must name a corpus file or a
  referee section (the AST reachability rule z80 uses for WZ/Q). Keep the
  two m68000 rules z80 lacks (every `NAMES` entry resolves to a handler;
  method name equals `_op_` + docstring name).
- Write the citation vocabulary down once, in `CONTRIBUTING.md` (item 5),
  and name the readability test in the README the way z80's does.

## Item 3 — test the tooling and close the CI gap (one day)

`tests/test_tooling.py` (172 lines, 11 tests) is the only test of
`state.py`, `debug.py`, `trace.py`, `console.py`, `disasm.py` and
`__main__.py`. z80 has five dedicated files, 1,003 lines, 69 tests. Add,
in z80's shape and names:

- `tests/test_public_api.py`: `__all__` equals the root exports (and add
  `Access` and the word-reader alias to the root; they are in module
  `__all__`s only); constructor rejects non-callables with a message; the
  four bus callables are replaceable; `CPUState` every-field round-trip
  and equality.
- `tests/test_debug_session.py`: `remove_breakpoint`/`remove_watchpoint`;
  `history`, `iter_history`, `clear_history`, `history_limit` bounding;
  `run()` clock budget and argument validation; `tracking`; a board-shaped
  target (`target.cpu`); `next_boundary` for `trace` and `halted_idle`;
  watchpoint kind validation.
- `tests/test_trace_comparison.py`: `TRACE_SCHEMA_VERSION` rejection;
  malformed line reported with its number (`trace.py:45`); unknown and
  missing keys (`trace.py:7`); `compare_step_records` field paths;
  `iter_trace_divergences`; `iter_session_steps` budget error
  (`trace.py:52`); accesses compared only when both records carry them.
  Make `StepRecord.__post_init__` and `step_record_from_dict` validate
  `instruction` and the `accesses` shape with messages, as z80 does.
- `tests/test_command_debugger.py`: every command (`help`, `delete`,
  `watch`/`unwatch`, all five `set` branches at `console.py:85-92`, `ipl`,
  `history`, `memory`, `interact()` on a text stream, `parse_number`
  edges: `$`, `0x`, decimal, `#` rejected, the maximum). Apply decision 4. Make
  `CommandResult` frozen and validated like z80's.
- `tests/test_disasm.py`: `disassemble_range`; a committed golden file of
  a few hundred words in MAME's spelling produced once by
  `validation/disasm_vs_mame.py`, so the spelling is checked in CI, not
  only on a machine with MAME.
- `tests/test_main.py`: `--zip` interleave and single-member paths
  (`__main__.py:27-53`), `--reset`, an image that does not fit.
- Tighten `tests/test_interrupts.py:41` (a 19-clock window on a value
  `test_mutation_survivors.py:119` pins exactly per phase): make it exact
  or delete it as redundant.
- `validation.md:38` says the decoder was checked word for word against
  MAME's `m68000.lst` "when the table was written"; there is no script.
  Add `scripts/check_decoder_vs_mame.py` reading a pinned listing, or
  reword the claim to what can be rerun.
- CI: the `corpus` job runs `test_corpus.py` and `test_bcd.py` only; add
  `tests/test_step_clocks.py` (it needs the corpus and is the `step_clocks`
  claim). Add a `package` job: build the wheel, install it in a clean
  venv, run `scripts/smoke_installed_package.py` (port z80's), and run
  `examples/minimal_m68000_host.py` (item 5). Add a weekly `oracles.yml`
  that builds the referees (`validation/referees/build_referees.py`, 42 s
  from pinned commits) and runs the calibration, the 680x0 detector and
  `scripts/coverage_report.py` + `scripts/mutate.py`, committing nothing
  but failing if a number moves from the recorded one.

## Item 4 — code hygiene and the public surface (half a day)

- Six `__all__` lists exist to silence unused-import warnings:
  `_control.py:204` (`MASK` unused), `_system.py:270` (`MASK24` unused),
  `_alu.py:543` (`MSB` unused), `_loads.py:197` (`MSB` unused, and the
  list sits mid-file before `class MultipleMixin`), `_ea.py:169`
  (`GroupZero` never used), `disasm.py:346` (`EA_KIND` unused). Remove the
  imports and the lists. Unused constants `BYTE`, `WORD`, `LONG`
  (`_core.py:64`) and `FC_CPU_SPACE` (`_core.py:38`): remove or use.
- `_brief_index` (`_control.py:151`) duplicates `_index` (`_ea.py:71`)
  except for consuming IRC; one helper taking the extension word.
  `sign_extend_16(x) & 0xFFFFFFFF` is written about 15 times across
  `_ea`, `_loads`, `_control`, `_alu`: one helper.
- Apply decision 5 (`reset_devices`). Three spellings of the program
  counter (`CPUState.pc`, `M68000CPU.PC`, `set_pc()`): keep the ones the
  boards use (`megadrive-python` is the consumer to grep), document them
  in `docs/api-stability.md`, and list every public writable attribute
  (`R`, `SR`, `ir`, `irc`, `ipl`, `clock`, `stopped`, `halted`,
  `last_acknowledge_phase`, `function_codes`, `tas_write`, the four bus
  callables) as contract or as development-tree.
- Put the SST `REVISION` in one place (it is hard-coded in
  `scripts/fetch_test_vectors.py:38`, `tests/test_corpus.py:20`,
  `tests/test_step_clocks.py:21`; the CI cache key and validation.md may
  keep their copies with a comment naming the source of truth).
- `benchmarks/speed.py`: port z80's shape (named workloads, CPU-time
  best-of, JSON output with interpreter and platform, a pytest smoke),
  and port `benchmarks/compare_revisions.py` (same-process A/B across two
  worktrees; this machine is shared and separate runs swing ±30%).
  Item 7 depends on this.

## Item 5 — documentation to the z80 shape (one to two days)

- **README** in z80's order: badges (CI; Oracles once item 3 adds it);
  what it is; **Validation** as a tiered bullet list (hardware-captured
  BCD; hardware-corrected WinUAE run with its 97.9% calibration and what
  the residuals are; the SST gate; the MAME lockstep; the 680x0 detector;
  the referee-pinned rules; `step_clocks`), each with a link to the
  reproducing command; a CI-coverage table saying what a green badge does
  and does not prove (the lockstep and the 680x0 run are local-only);
  install (PyPI once released, source tree, PEP 668 note); a **runnable**
  minimal host (`README.md:79-87` is pseudo-code today: give the four
  callables over a bytearray, vectors at 0 and 4, `reset()`, two
  instructions, asserted clocks and D0); the host protocol pointer;
  **Reference-core boundary** (owns / host owns / does not claim, with
  the bus-error frame, 68010+, wait states and the 68008 in the last
  list); **Learning and inspection** (start-here, handler citations and
  the readability test, CPUState, disassembler, DebugSession,
  CommandDebugger, `python -m m68000_python`, traces); Development
  (pytest, ruff, fetch); **Project records** (links, replacing the
  directory tree at `README.md:131-169`, which duplicates
  `docs/README.md`). Keep the claims.md paragraph first among the links.
  A "Vibe coded, oracle validated" section, honest about how this core
  was built (one agent, one night, from a brief, then three verification
  rounds), with `docs/ai-assisted-development.md` behind it.
- **New pages**, each copied in shape from z80 and rewritten for this
  processor: `docs/interrupt-lifecycle.md` (the host protocol in one
  place: `set_ipl`, level-7 edge, `acknowledge` returning a vector,
  `AUTOVECTOR` or `SPURIOUS`, the E-clock wait and its T3 status, STOP
  wake-up, `BusError`, `tas_write`, `address_error`, `reset_devices`,
  what the host must not do); `docs/api-stability.md`;
  `docs/trace-comparison.md`; `docs/ai-assisted-development.md`;
  `CONTRIBUTING.md` (commands CI runs, which tests a change must add, the
  citation vocabulary from item 2, what never gets committed);
  `SECURITY.md`; `CHANGELOG.md` (Keep-a-Changelog, `[Unreleased]`, with
  every decision from claims.md's history that changed the core: I/N in
  group 2, TRAPV IR, TAS BERR, trace after an unexecuted instruction).
- **Stubs to real pages**: `docs/disassembly.md` (12 lines: add the
  `Instruction` field list, `disassemble_bytes`/`disassemble_range`, the
  side-effect-free reader rule, MAME's spelling as the reference);
  `docs/debug-session.md` (25 lines: stop reasons, history, watchpoints,
  targets, every console command); `docs/trace-schema.md` (23 lines: key
  table, kind order, one full example record, versioning rules, and one
  committed reference trace under `examples/` so a port has something to
  diff against, per decision 2).
- `docs/validation.md`: add the **certification record** z80 has (one
  hash, both interpreters, every gate with its command, count and
  timing, the date), and a **Speed** section fed by item 7. State the
  test count. Note which claims are reproducible only with MAME + ROMs
  (lockstep, `disasm_vs_mame`) and that the transistorfet ASR.b T1 row
  (`validation.md:259`) rests on reading its README, not on a run.
- `examples/minimal_m68000_host.py` (run in CI) and
  `examples/interrupt_host.py` (the `acknowledge`/`set_ipl` path, which
  is what boards get wrong).

## Item 6 — packaging (an hour)

`pyproject.toml`: version `0.1.0` (item 8 decides the tag), classifiers
(Alpha, MIT, 3.11-3.14, CPython, PyPy, Emulators), `[project.urls]`,
`ruff==<the version the tree is formatted with>` pinned in `dev` because
CI runs `ruff format --check` (z80 pins `0.16.8` for this reason; an
unpinned ruff release can turn CI red with no code change).
`docs/releases/0.1.0.md` in z80's shape. `.github/workflows/publish.yml`
copied from z80 (tag/version check, `twine check`, Trusted Publishing,
dry run on PR); the upload runs on the `v0.1.0` tag, which Aubrey pushes after flipping the repository public (decision 1).

## Item 7 — speed ablation ladder (two days)

Dispatch is already the z80-polish shape (one 65,536-entry table built
once, packed SR, no per-call rebuilds), so the remaining cost is frame
depth, not waste. Profile 2026-09-25: `_read_program_word` is the top
self-time function (two per instruction), then `step`, then `_prefetch`.
A memory-operand ALU op is 8-9 Python frames deep
(`_op_add → _binary → _ea_read → _ea_fetch → _ea_address → _read →
_read_word → host`, then `_add → _flags_add → _to_data_register →
_prefetch`).

Run as a ladder: one commit per rung with the A/B numbers (item 4's
`compare_revisions.py`, CPython and PyPy) in the commit message, every
oracle green at every rung, and a rung that does not move the number is
reverted, not kept. Candidate rungs, cheapest first:

- **A** `MASK`/`MSB` dicts keyed by size (`_core.py:65-66`) to tuples
  indexed by size.
- **B** inline `_step_size` at its ten `(An)+`/`-(An)` call sites.
- **C** flatten the bus path: one `try/except BusError` per instruction
  boundary instead of per access (`_core.py:229-306`), and let
  `_prefetch` call the host directly instead of through
  `_read_program_word`.
- **D** merge `_flags_add`/`_flags_sub`/... into their arithmetic helpers
  and stop passing bound methods through `_binary`/`_modify`.
- **E** the six lambdas that wrap every bus call when
  `function_codes=True` (`_core.py:166-178`): a second table or partial
  application built once.

Stop rule: stop when a rung gains under 5% on both interpreters. Record
the ladder in `docs/validation.md` "Speed" and `CHANGELOG.md`. There is
no target number; megadrive-python runs on PyPy and the point is to keep
only what pays.

## Item 8 — certify, then hand over (half a day)

Rerun everything on the final commit and write the certification record
into `docs/validation.md` with that hash: full pytest on CPython and
PyPy, the SST gate and `step_clocks`, BCD, the referee build +
calibration + `questions.py`, the 680x0 detector with its classified
table, `coverage_report.py`, `mutate.py`, the benchmark JSON; the MAME
lockstep only if the ROMs are present, otherwise the record says which
earlier hash it last ran at. Update `CHANGELOG.md` from `[Unreleased]` to
`0.1.0` with the date, finish `docs/releases/0.1.0.md` (what it is, what
it claims, what it does not, the migration notes for megadrive-python if
item 4 renamed anything). Push, PR, CI green, merge, **stop**. Aubrey
flips visibility, tags `v0.1.0` and lets `publish.yml` publish.

## Item 9 — stretch: the conformance kit (deferred, decision 2)

Port `z80_python.conformance` (`ConformanceHost`, manifest, `trace`,
`diff`, `write_checkpoints`, the CLI) and `docs/conformance.md`'s ladder,
with two committed manifests and reference traces (a straight-line
program; an interrupt scenario). Only if a 68000 port (Rust, or another
language) is planned; otherwise the trace schema and one reference trace
from item 5 are enough.

## Follow-up outside this brief

z80-python should inherit `docs/claims.md`'s status vocabulary (verified /
strong / provisional / contested / undecidable here / outside the
contract) and the coverage + mutation pages. That is a z80 brief, written
after this round lands.

## What done looks like

A reader who opens the README learns in two screens what the core is,
what it claims at what tier, how to install it, how to embed it in eight
lines that run, and where the contract stops. Every handler settles its
own disputes by citation. The tooling is tested to the same depth as the
core. Every number in the tree was regenerated at one named hash. Nothing
in `docs/` speaks of a core that does not yet exist. And the family has
two flagship-grade cores instead of one.
