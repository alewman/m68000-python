# m68000-python

A readable, dependency-free, pure-Python **Motorola 68000 instruction core**,
in the shape of [z80-python](https://github.com/alewman/z80-python) and
[6502-python](https://github.com/alewman/6502-python): the host owns a 24-bit
memory space and the devices, the core owns instruction semantics, the
status register, the prefetch queue, and the exception model, and `step()`
returns the clock total of what it ran.

**Status: documents and oracles only.** There is no core code in this
repository yet. What is here is the groundwork a later session builds from:
a primer on the processor, the cycle tables, the undefined-but-deterministic
behaviors with their evidence, every 68000 oracle found ranked by tier with
pinned revisions, a fetch script that has been run once, a working recipe
for MAME traces, and a handoff brief with milestones. See
[docs/README.md](docs/README.md).

## Scope

The MC68000 (and its electrically different, behaviorally identical
MC68HC000 and MC68EC000 siblings): 16-bit data bus, 24-bit address bus, the
68000 instruction set and exception model. It is the main processor of much
of the 1985–1995 arcade: Sega System 16 and System 18, Capcom CPS-1, SNK
Neo Geo, Atari System 1, Williams/Midway Y-unit, Toaplan, and the Sega
Genesis/Mega Drive, Amiga, Atari ST and 68k Macintosh outside the arcade.

Out of scope, and said here so nobody waits for it: the 68010 (VBR, loop
mode, the 29-word bus-error frame, `MOVEC`/`MOVES`, privileged `MOVE from
SR`), the 68EC020/68020 and later (32-bit bus, full extension words,
memory-indirect addressing, bit fields, `DIVS.L`, caches). The 68008's 8-bit
bus is a host matter but its timing is not modeled.

## What a pure-Python 68000 is

Larger than the two sibling cores by a clear margin, and the documents say
so rather than hide it:

- a 16-bit opcode space (65,536 first words, 45,815 defined) decoded by
  family bits and then by size and effective-address fields, rather than
  256 opcodes and four prefixes;
- twelve effective-address modes with extension words, shared by about 80
  instruction families;
- supervisor and user modes with separate stack pointers, and a 256-entry
  vector table;
- three groups of exceptions with two stack-frame shapes, including
  address errors that abort an instruction mid-way and push a seven-word
  frame whose contents the manual calls unpredictable;
- a two-word prefetch queue that determines the bus-transaction pattern the
  test corpora record and that self-modifying code can observe;
- seven interrupt levels with an acknowledge cycle that may return a vector,
  an autovector, or a spurious-interrupt indication.

The [handoff brief](docs/handoff-brief.md) estimates the core at two to
three times z80-python's size and orders the work by oracle tier.

## The embedding contract (planned)

The same shape as the sibling cores. A host subclasses the CPU and supplies
byte and word memory accessors for a 24-bit space, drives the interrupt
priority level between steps, and answers the interrupt-acknowledge
callback; the core never allocates memory, never schedules a frame, and
never knows what a scanline is. Cycle totals returned by `step()` are the
documented per-instruction totals restated in [docs/timing.md](docs/timing.md)
and checked, case by case, against the corpus.

## Oracles

Ranked by where their expected values came from (hardware-captured >
hardware-corrected > emulator-derived; a low-tier oracle is a detector,
never a judge). The short version; the pins, sizes and limits are in
[docs/validation.md](docs/validation.md):

| Oracle | Tier | What it covers |
| --- | --- | --- |
| flamewing's 68k BCD verifier | hardware-captured | `ABCD`/`SBCD`/`NBCD`, every input, every flag, two Genesis models |
| WinUAE's 68000 and its `cputest` | hardware-corrected | integer instructions, undefined flags, address-error frames, cycles; run on real Amigas by its author |
| SingleStepTests/m68000 | emulator-derived (MAME's microcode-transcribed core) | 127 files, 317,500 cases with prefetch and bus transactions; **fetched, counted, pinned** |
| MAME 0.285 traces | emulator-derived | whole-game instruction streams from System 16; **recipe verified** |
| SingleStepTests/680x0 | emulator-derived, no license | 124 files, 1,000,060 cases; detector only |

No hardware-captured single-step corpus for the 68000 exists as of
2026-09-11; the documents say what that means for every claim.

## Repository layout

```text
README.md                    this file
LICENSE                      MIT, copyright 2026 alewman
docs/README.md               index of the documents
docs/start-here.md           the processor primer
docs/timing.md               cycle tables and host clocks
docs/undocumented-behavior.md
docs/validation.md           oracles, tiers, pins, corpus shapes
docs/mame-oracle.md          the MAME trace recipe
docs/handoff-brief.md        the brief for the session that builds the core
scripts/fetch_test_vectors.py
tests/68000_test_vectors/    fetched corpora, ignored by git
```

Fetch the pinned corpus (138 MB) with:

```text
python3 scripts/fetch_test_vectors.py
```

`--with-680x0` adds the second corpus (203 MB, unlicensed, detector only);
`--files NOP,ABCD` fetches a few files for a quick start.

## License

MIT. The Motorola manuals, MAME, WinUAE, Musashi, the SingleStepTests
corpora and the BCD verifier retain their own licenses and are cited, not
bundled.
