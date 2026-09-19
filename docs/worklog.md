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

(none yet)

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
