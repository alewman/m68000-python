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
