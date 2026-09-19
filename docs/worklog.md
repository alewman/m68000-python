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
