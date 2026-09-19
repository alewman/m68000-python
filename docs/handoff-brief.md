# Handoff: build `m68000-python`, a pure-Python 68000 core in the shape of z80-python

## Context you are inheriting

`z80-python` (`/data/emu/z80-python`), `6502-python` (`/data/emu/6502-python`),
`i8080-python` and `m6800-python` (`/data/emu/m6800-python`) are pure-Python instruction cores with one identity: readable code that is
the spec, verified against external oracles ranked by where their expected
values came from, embedded through a small host contract (the host owns
memory and devices; the core returns cycles per step). This repository,
`/data/emu/m68000-python`, is the groundwork for the next core: documents
and oracle plumbing, no core code. Read these, in this order, before writing
any Python:

1. `README.md` — scope and the embedding contract.
2. `docs/start-here.md` — registers, SR, opcode fields, the twelve EA modes,
   families, the exception model, prefetch.
3. `docs/validation.md` — every oracle with its tier and pin; what was
   fetched and counted.
4. `docs/undocumented-behavior.md` — the undefined-on-paper rules and their
   evidence tiers.
5. `docs/timing.md` — the cycle tables and what prefetch does to them.
6. `docs/mame-oracle.md` — the working MAME trace recipe.
7. `/data/emu/m6800-python/src/m6800_python/_dispatch.py`, `_core.py` and
   `tests/test_readability.py` there — the structural template you are
   copying: dispatch tables built once at import by `build_table`, the
   callables host contract, the docstring convention and readability test.
8. `/data/emu/z80-python/docs/validation.md` and `docs/conformance.md` —
   the evidence template: how a certification record states its oracles,
   pins, counts and exclusions.

## Your task

Write the core under `src/m68000_python/`, dependency-free, Python 3.11+
(`requires-python = ">=3.11"`, ruff `target-version = "py311"`: the floor is
the newest Python PyPy supports, and PyPy is where the corpus and lockstep
runs happen; no 3.12-only syntax), in z80-python's module shape: `_core.py` (fetch,
prefetch queue, exception entry, interrupt acceptance), `_ea.py`
(effective-address decode and the twelve modes), `_flags.py`, `_alu.py`,
`_loads.py` (MOVE family, MOVEM, MOVEP, LEA/PEA, LINK/UNLK, EXG, SWAP,
EXT), `_bits.py`, `_shifts.py`, `_bcd.py`, `_control.py` (branches, jumps,
returns, DBcc, Scc), `_system.py` (TRAP, STOP, RESET, MOVE to/from SR/CCR/
USP, RTE), `_dispatch.py` (the 16-bit decode into per-family tables built once at
import, in m6800-python's `build_table` shape; handlers never see the
table), `disasm.py`, `state.py`. Every handler
docstring starts with its Motorola mnemonic; every undocumented rule is a
comment on the line that encodes it, naming the tier from
`docs/undocumented-behavior.md`.

The host contract is the family's callables contract (z80-python 0.4.0,
`Z80CPU(read_byte, write_byte, *, read_port=None, write_port=None)`; m6800-python
`M6800(read_byte, write_byte, *, undocumented=...)`), not subclassing:
`M68000CPU(read_byte, read_word, write_byte, write_word, *, acknowledge=None)`
for a 24-bit address space (the core masks to 24 bits and passes function
codes as an optional keyword the host may ignore), `set_ipl(level)` called
from the host side, and an `acknowledge(level)` callback that returns a vector number, `AUTOVECTOR`, or `SPURIOUS`.
`step()` runs one instruction or one exception entry and returns its clock
total. Address errors and the double-fault halt are modeled; bus errors are
raised by the host through an exception type the core catches at the
access. Long accesses are two word accesses, high word first, in the order
the corpus transactions show.

### Milestones, each with its acceptance test, in oracle-tier order

1. **Skeleton, decoder, disassembler, corpus runner.** Decode all 65,536
   words to a handler or to the illegal/A-line/F-line entry; disassemble;
   a runner for `tests/68000_test_vectors/m68000/v1/*.json.bin` (the shape
   is in `docs/validation.md`; parse the binary directly, do not go through
   `decode.py`'s JSON) comparing registers, SR, USP/SSP, RAM words, the
   prefetch pair, the cycle total, and the ordered transaction list with
   kinds, addresses, sizes, values and strobes, plus a `680x0` adapter for
   the second corpus's JSON shape. Strip the T bit from `initial.sr` and
   `final.sr` or model trace as a separate boundary (corpus issue #2);
   decide and document. Acceptance: `NOP`, `MOVEQ`, `Bcc`, `RTS`,
   `MOVE.w` pass 2,500/2,500 each with transactions matched.
2. **BCD (T1).** Port flamewing's table generator, run `ABCD`, `SBCD`,
   `NBCD` over all inputs. Acceptance: 262,144 + 262,144 + all `NBCD`
   inputs agree on result and CCR. This is the first rung because it is the
   only judge-tier oracle and it is cheap.
3. **Full corpus (T3, microcode).** All 127 files. Acceptance: 317,500 /
   317,500 with the exceptions you can name: `TAS.json.bin` cycle counts
   (corpus README says its TAS timing is wrong; compare state only and pin
   the cycle disagreement), `TRAPV.json.bin` if the README's "strange
   issue" shows (diagnose before excluding). Every excluded case gets a
   line in `docs/validation.md` with the reason.
4. **MAME lockstep (T3).** A System 16B host (`altbeast`, or `goldnaxe`;
   ROMs in place from the myrient path, decrypt through MAME's tables or
   pick an unencrypted set) running against the `error.log` stream from
   `docs/mame-oracle.md` with `curpc`, `sr`, `d0`–`d7`, `a0`–`a6`, `usp`,
   `sp` per line. Acceptance: N million instructions identical, N stated;
   the first divergence diagnosed to a corpus case or an undocumented rule
   before the run is extended. The host is a separate package or example,
   not part of the core. Add a second lockstep on MAME's `genesis` driver
   (no BIOS needed; ROMs under `/data/emu/roms/megadrive`), because the
   Mega Drive is the board this core exists for (see "Why this core, and
   what comes after it" below). Only the 68000 side is compared; stub the
   VDP and Z80 bus reads with the values the trace shows.
5. **Second corpus as detector (T3).** SingleStepTests/680x0 with the
   adapter from rung 1. Acceptance: every disagreement explained by a
   higher-tier source or by the corpus's own issue tracker (the two
   `ASL.b` cases of issue #4 are known); none silently skipped.
6. **Interrupts and STOP.** Scenario tests for IPL level changes between
   instructions, level-7 edge behavior, autovector and spurious paths,
   trace-then-interrupt ordering (UM 6.3.8), `STOP` wake-up. No external
   oracle exists; cross-check against the MAME trace's vblank entries and
   state the claim as "consistent with the manual and with MAME", never
   "verified".

Do not skip a rung or reorder them; each one's failure is cheapest to
diagnose before the next.

## Constraints

- **Oracle tiers are not negotiable.** A T3 disagreement is a question; go
  up a tier or to the manual before changing a handler, and write down the
  answer in `docs/undocumented-behavior.md` with its tier.
- **Do not commit ROMs, traces, corpora, or third-party programs.**
  `tests/68000_test_vectors/` is fetched by `scripts/fetch_test_vectors.py`
  and ignored; MAME output stays under an ignored directory.
- **Do not touch other directories under `/data/emu`.** Read z80-python,
  6502-python and m6800-python; do not modify them. If a shared tool belongs in z80-python,
  propose it there as a PR rather than copying it here.
- **Pins in every claim**: corpus commit, MAME version, flamewing commit,
  Python versions, wall time. State exactly what was and was not run.
- Commit in reviewable units with `git -c user.name=alewman -c
  user.email=alewman@gmail.com commit`; do not push or create the GitHub
  repository until the user asks. Trailer on every commit:
  the `Co-Authored-By:` line for the model you are running as, and the
  session line the user supplies.
- Same readability discipline as m6800-python (`tests/test_readability.py`
  there): grep-able mnemonics, dispatch tables built in code at import
  from readable per-family rules, no generated tables checked into the
  source tree.

## Size, honestly

z80-python's core is about 9,000 lines of Python for 1,604 opcode/prefix
variants over an 8-bit opcode space with four prefixes, one addressing
temporary, and a three-word interrupt model. The 68000 is a different
order:

- 65,536 first words, of which 45,815 are defined (the 680x0 opcode map has
  19,721 `None`); about 80 mnemonics × up to 3 sizes × up to 12 EA modes,
  with the EA decode shared. Expect 60–70 handler groups, most of them
  parameterised by size and EA, and an EA module that every group calls.
- A prefetch queue that must be modeled for the transaction comparison to
  pass at all; nothing in z80-python corresponds to it.
- Supervisor/user mode, two stack pointers, a 256-entry vector table, three
  exception groups with different stack frames, address errors mid-
  instruction with an abort path, trace, and seven interrupt levels with an
  acknowledge cycle.
- Cycle counts that are data-dependent for multiply and divide, and per
  EA mode for everything else.

A realistic estimate is **2 to 3 times z80-python's core**: 18,000–25,000
lines including the disassembler, and a corpus gate of 317,500 cases that
runs in minutes on PyPy and tens of minutes on CPython (z80-python's 1.6
million cases take 28 s on CPython; each 68000 case carries more state and
a transaction list, so budget 10–20× per case). The disassembler alone is
comparable to z80-python's. Performance will be an order of magnitude below
the Z80 core per instruction on the same interpreter; that is acceptable
for a reference and is not a milestone.

## Why this core, and what comes after it

Decided 2026-09-18: the family's next boards are `sms-python` (SG-1000 →
Master System → Game Gear, on z80-python) and then a Mega Drive, whose main
CPU is this core. That puts two requirements on it beyond the arcade use:

- **Speed on PyPy matters.** A Mega Drive 68000 runs at 7.67 MHz. Hitting
  full speed is not a milestone, but record instructions/second on CPython
  and PyPy with every rung the way m6800-python does, and do not add
  per-access overhead the corpus does not need (function codes and the
  transaction log must cost nothing when the host does not ask for them).
- **The bus contract must admit a board with a second CPU.** The Mega
  Drive's Z80 and 68000 share a bus window with BUSREQ/RESET arbitration,
  and the VDP's DMA stalls the 68000. So `step()` returns cycles and the
  host decides everything else; the core must not assume it owns time.
  The `TAS` write-back that the Genesis bus drops
  (`docs/undocumented-behavior.md`) is the host's business, visible
  through the access kind the core passes.

## Tooling bar

m6800-python (`/data/emu/m6800-python`) raised the bar after this brief was
written: the core is not done until it also has `state.py` (CPUState
capture/restore), `disasm.py` sharing the dispatch table and matched against
MAME's disassembler on the traced instructions, `debug.py` (DebugSession,
watchpoints), `console.py` (CommandDebugger), `trace.py` (JSONL trace, the
schema in z80-python's `docs/trace-schema.md`), `py.typed`, and
`python -m m68000_python`. Copy those modules' shape, not their code.

## What done looks like

A `README.md` that states, with the pins above, which rungs pass and with
what counts; `docs/validation.md` rewritten from "the oracles found" to
"the certification record"; a CI job that reproduces rungs 1–3 (the corpus
is fetched in CI as z80-python's is) on every push; the MAME lockstep
recorded locally with its command line and instruction count, not in CI.

Before starting, tell the user in a few sentences how you read this brief
and what you will do first.
