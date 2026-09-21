# m68000-python

A readable, dependency-free, pure-Python **Motorola 68000 instruction core**,
in the shape of [z80-python](https://github.com/alewman/z80-python) and
[6502-python](https://github.com/alewman/6502-python): the host owns a 24-bit
memory space and the devices, the core owns instruction semantics, the
status register, the prefetch queue, and the exception model, and `step()`
returns the clock total of what it ran.

**Status: the whole 68000 instruction set, up all six rungs of the plan,
not yet released.** What is claimed, at what strength, and what is
contested or not claimed at all is [docs/claims.md](docs/claims.md): read it
before relying on any corner of the exception model. Against **hardware-captured** values it passes
every input of flamewing's BCD verifier tables (`ABCD`, `SBCD`, `NBCD`:
525,312 cases, result and all five flags). Against the pinned,
**microcode-derived** SingleStepTests/m68000 corpus it passes **317,500 of
317,500** cases with no exclusions, compared on registers, SR, both stack
pointers, the prefetch queue, RAM, the clock total and every bus access in
order with its function code. In lockstep with MAME 0.285 it matched every
register before every instruction of **24.6 million instructions of System
16B Altered Beast** (every write and every instruction's clocks checked) and
**28.2 million of Genesis Altered Beast**. Against the second corpus
(SingleStepTests/680x0) 787,660 of 1,000,060 cases agree and every
disagreement is sorted into a named cause, most explained by WinUAE's
hardware-corrected rules. Interrupts and STOP are covered by scenario tests
consistent with the manual and with MAME. The record, with every pin, is
[docs/validation.md](docs/validation.md); what was run and what is open is
[docs/worklog.md](docs/worklog.md).

What that evidence reaches is mapped in [docs/coverage.md](docs/coverage.md):
the gate executes 38,019 of the 45,815 defined first words, and the suite now
runs all of them, the rest checked by register-renaming relations the manual
implies and by manual-derived tests. [docs/mutation.md](docs/mutation.md)
measures the suite: of 176 seeded mutants it kills 173; two of the three
survivors are equivalent to the core, and one (the flags after DIVS by zero,
undefined in the manual) is open.

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

## The embedding contract

The same shape as the sibling cores, callables rather than subclassing:

```python
from m68000_python import M68000CPU, AUTOVECTOR

cpu = M68000CPU(read_byte, read_word, write_byte, write_word)
cpu.reset()  # SSP and PC from $000000 and $000004
while running:
    clocks = cpu.step()  # one instruction or one exception entry
    ...  # the host advances its devices by `clocks`
    cpu.set_ipl(level)  # 0-7, between steps
```

The four callables see 24-bit addresses; a word access is always at an even
address (the core raises the address error itself), and a long is two word
accesses, high word first unless the microcode writes the low word first
(`-(An)` destinations, read-modify-write results). Optional keywords, each
free unless used: `acknowledge(level)` answers the interrupt-acknowledge
cycle with a vector, `AUTOVECTOR` or `SPURIOUS`; `function_codes=True`
passes `fc=` on every access; `tas_write(address, value)` receives TAS's
write half (the Genesis bus drops it); `address_error(address, write, fc)`
is told about an access an address error aborted. A host raises `BusError`
from a callable to assert BERR. The core never allocates memory, never
schedules a frame and never assumes it owns time: `step()` returns clocks and
the host decides everything else.

Speed, on the loop in `benchmarks/speed.py` (a shared, loaded machine):
about 0.6-0.7 million instructions per second on CPython 3.14 and about 20
million on PyPy 7.3.23 (the Mega Drive's 68000 runs about 1 million a
second); on real game code under the lockstep the core is far faster than
the trace parsing around it.

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
src/m68000_python/           the core: _core (bus, prefetch, exceptions), _ea,
                             _flags, _alu, _loads, _bits, _shifts, _bcd,
                             _control, _system, _dispatch (the opcode map),
                             cpu (M68000CPU), disasm
                             state, debug, trace, console, __main__ (tooling)
tests/                       corpus reader and harness, the gates, readability
validation/                  MAME lockstep host and trace reader (rung 4)
scripts/run_680x0.py         the second corpus as a detector (rung 5)
scripts/run_corpus.py        run corpus files and print failures
scripts/coverage_report.py   what the corpora and the suite reach (docs/coverage.md)
scripts/mutate.py            mutation testing of the suite (docs/mutation.md)
scripts/fetch_test_vectors.py
benchmarks/speed.py          instructions per second
docs/README.md               index of the documents
docs/start-here.md           the processor primer
docs/timing.md               cycle tables and host clocks
docs/undocumented-behavior.md
docs/validation.md           the certification record; oracles, tiers, pins
docs/coverage.md             what the evidence reaches, and the open gaps
docs/mutation.md             what the suite would notice: mutants and survivors
docs/mame-oracle.md          the MAME trace recipe
docs/worklog.md              what was run, when, with what result
docs/handoff-brief.md        the brief for the session that builds the core
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
