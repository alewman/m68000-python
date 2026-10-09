# m68000-python

[![CI](https://github.com/alewman/m68000-python/actions/workflows/ci.yml/badge.svg)](https://github.com/alewman/m68000-python/actions/workflows/ci.yml)
[![Oracles](https://github.com/alewman/m68000-python/actions/workflows/oracles.yml/badge.svg)](https://github.com/alewman/m68000-python/actions/workflows/oracles.yml)

A readable, pure-Python Motorola MC68000 **instruction-core reference
implementation**.

`m68000-python` is a processor core built to be read, learned from, embedded
in real machines, and inspected by humans and AI tools. It implements the
68000 instruction set, the prefetch queue, and the exception model at
instruction boundaries, leaving memory maps, devices and machine scheduling
to the host, in the same shape as [z80-python](https://github.com/alewman/z80-python),
the family's reference core. Where z80-python could be checked exhaustively
against hardware-captured values, no such oracle exists for the 68000, so
this core carries a **claim boundary** instead: every behaviour is labelled
by how many independent lines of evidence support it and how close to
silicon the best of them is ([docs/claims.md](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/claims.md)).

The project is deliberately:

- **readable** — every instruction is an ordinary Python method; a table
  only routes each of the 65,536 first words to its method, which cites the
  manual page its rule comes from and the corpus file that pins what the
  manual leaves open;
- **pure Python** — no runtime dependencies; CPython and PyPy;
- **independently validated** — correctness claims come from external
  oracles ranked by tier, and from referees built and run from pinned
  sources, never from code-generation confidence;
- **embeddable** — a host passes in its bus as callables and controls when
  the processor advances; and
- **inspectable** — processor state, disassembly in MAME's spelling, bounded
  debugging with breakpoints, watchpoints and bus-access tracking,
  structured traces, and `python -m m68000_python` for stepping a binary.

## Validation

Each oracle is named with its tier: where its expected values came from. A
lower tier detects; the highest tier that checks a claim decides it
([oracle tiers](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/validation.md#the-tier-rule)). The core passes:

- **hardware-captured:** every input of flamewing's 68k BCD verifier tables,
  **525,312 cases** of `ABCD`, `SBCD` and `NBCD` recorded on two Sega Genesis
  models, result and all five flags (`tests/test_bcd.py`);
- **hardware-corrected, run:** WinUAE's CPU-tester core, whose 68000 its
  author corrects against real Amigas with `cputest`, built here from a
  pinned commit and run over the whole gate: **308,416 of 314,988** judged
  cases agree, and every residual is an address-error or 2-clock difference
  listed by name ([docs/referees.md](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/referees.md));
- **emulator-derived, the gate:** all **127 files, 317,500 cases** of the
  pinned SingleStepTests/m68000 corpus, generated from MAME's
  microcode-transcribed core, compared on registers, SR, both stack
  pointers, the prefetch queue, RAM, the clock total and every bus access in
  order with its function code, **no case excluded**; and the clock at which
  each access ends within its step, over the 261,894 cases without an
  address error (`tests/test_step_clocks.py`);
- **emulator-derived, real code:** MAME 0.285 in lockstep, every register
  before every instruction of **24,595,631 instructions** of System 16B
  Altered Beast (every write and every instruction's clocks checked) and
  **28,249,660** of Genesis Altered Beast;
- **emulator-derived, detector:** SingleStepTests/680x0, **787,660 of
  1,000,060** cases agree and every disagreement has a named cause, most
  decided in the core's favour by the WinUAE run; and Musashi, an
  independent hand-written core, run over the gate: 257,300 of 261,894
  judged cases, every difference decided by a higher tier;
- **documentation:** the interrupt and STOP scenarios, consistent with the
  manual and with MAME's 5,579 lockstep interrupts; and every handler's
  rule, cited to a page of Motorola's manuals in its docstring, with the
  SingleStepTests file named wherever the manual is silent.

Where the sources disagree the core follows the gate and the claim is
**contested**: six address-error behaviours, three 2-clock questions and
the double bus fault. Each is listed with what
would settle it ([docs/claims.md](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/claims.md)). The order of bus cycles
and the exact clock totals rest on MAME's lineage alone, and the pages say so.

What the evidence reaches is mapped: the suite executes all 45,815 defined
first words ([docs/coverage.md](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/coverage.md)), and of 176 seeded
mutants it kills 174, the two survivors provably equivalent
([docs/mutation.md](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/mutation.md)). Exact revisions, hashes, commands
and timings are in [the validation record](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/validation.md).

This is an instruction-level semantic and lifecycle claim. It is **not** a
claim of cycle-accurate bus-pin behaviour, of wait states, or of a complete
computer.

### CI coverage

The two badges cover different things, and neither covers everything:

| Badge | Runs | When |
| --- | --- | --- |
| **CI** | the fast suite (decoder, readability, BCD tables, manual-derived and referee-pinned tests, the tooling), Ruff check and format, both examples, on CPython 3.11-3.14 and PyPy 3.11; the SingleStepTests gate and the `step_clocks` claim on CPython 3.14 and PyPy 3.11; a wheel build and installed-API smoke test | every push and pull request |
| **Oracles** | the decoder against MAME's `m68000.lst`, the 680x0 detector, the WinUAE and Musashi referees built and calibrated, the coverage map and the mutation score, each failing if its number moves from the one the documents record | weekly, and on demand |

**The MAME lockstep is certified locally, not in CI.** It needs MAME 0.285
and the ROMs; its command lines, counts and timings are in
[the validation record](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/validation.md).

## Vibe coded, oracle validated

This core was written by an AI agent in one night from a brief, then taken
through three verification rounds: coverage and mutation testing, referees
built and run, and a claim boundary. That history is stated plainly because
the correctness claim does not rest on it. Generated emulator code can be
plausible and wrong, above all around the prefetch queue, address-error
frames and undefined flags; the feedback loop was made stronger than the
model's confidence, and four core bugs the gate could not see were found by
the coverage work and the referees and fixed as failing tests first. See
[AI-assisted development](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/ai-assisted-development.md).

## Version status

The current release is **`0.1.0`** (see its [release note](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/releases/0.1.0.md)
and the [changelog](https://github.com/alewman/m68000-python/blob/v0.1.0/CHANGELOG.md)).

### Install from PyPI

```text
python -m pip install m68000-python
```

### Install the source tree

```text
git clone https://github.com/alewman/m68000-python.git
cd m68000-python
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

Recent Debian, Ubuntu, Fedora and Homebrew Pythons refuse `pip install` into
the system interpreter (PEP 668); the virtual environment line above is the
supported way around that. The distribution is named `m68000-python`; its
import is `m68000_python`.

## Minimal host

The host owns memory and devices and passes the CPU its bus as four
callables over a 24-bit address space. A bytearray serves the byte accesses
as it is; two small functions assemble and split the words, big-endian as
the chip does. `reset()` fetches SSP and PC from addresses 0 and 4.

```python
from m68000_python import M68000CPU

memory = bytearray(1 << 16)


def read_word(address):
    return (memory[address] << 8) | memory[address + 1]


def write_word(address, value):
    memory[address] = value >> 8
    memory[address + 1] = value & 0xFF


memory[0:8] = (0x8000).to_bytes(4, "big") + (0x1000).to_bytes(4, "big")  # SSP, PC
memory[0x1000:0x1004] = bytes((0x70, 0x05, 0x52, 0x80))  # moveq #5,D0; addq.l #1,D0
cpu = M68000CPU(memory.__getitem__, read_word, memory.__setitem__, write_word)
cpu.reset()
assert cpu.step() == 4
assert cpu.step() == 8
assert cpu.R[0] == 6
```

`examples/minimal_m68000_host.py` is this program, run in CI;
`examples/interrupt_host.py` adds a device that raises level 4. This is the
embedding contract of the whole family: z80-python and m6800-python take
their buses the same way.

`step()` runs one instruction or one exception entry and returns its clock
total. Registers (`R[0:8]` D0-D7, `R[8:16]` A0-A7, `SR`) are directly
readable and writable; `PC` reads the address of the next instruction and
`set_pc()` starts execution somewhere else. Optional constructor keywords,
each free unless used: `acknowledge(level)` answers the interrupt-acknowledge
cycle with a vector number, `AUTOVECTOR` or `SPURIOUS`; `function_codes=True`
passes `fc=` on every access; `tas_write(address, value)` receives TAS's
write half, which the Genesis bus drops; `address_error(address, write, fc)`
is told about the access an address error aborted; `reset_devices()` sees
the RESET instruction's pulse. A host raises `BusError` from a callable to
assert BERR. Inside a callable, `cpu.step_clocks` says at which clock of the
step the access ends, which a board needs to stall the CPU at the right
point; the core models no wait states, so the host adds its own stall
clocks to the total. [The interrupt lifecycle](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/interrupt-lifecycle.md)
has the whole host protocol.

Speed, on the `base` workload of `benchmarks/m68000_core_benchmark.py`
(2026-09-25, a shared machine at load 12): about 1.4 million instructions
per second on CPython 3.14.4 and about 33 million on PyPy 7.3.20; a Mega
Drive's 68000 executes about 1 million a second. The four workloads and the
polish round's speed ladder are in [the validation record](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/validation.md#speed).

## Reference-core boundary

`m68000-python` owns:

- the 68000 instruction semantics, the two-word prefetch queue and the bus
  sequence of every instruction, and the clock total of every step;
- the registers, SR, both stack pointers, and the internal state that
  decides what the next step does;
- the exception model: group 0 (address error, and bus error when the host
  asserts it), group 1 (trace, interrupts, illegal, privilege) and group 2
  (TRAP, TRAPV, CHK, divide by zero), with their frames; and
- processor-level observation and debugging values.

A host machine owns:

- ROM, RAM, memory maps, mappers, devices and open-bus values;
- video, audio, input, DMA and a second processor's share of the bus;
- frame, scanline, clock and interrupt scheduling, and wait states;
- device resets and the RESET and HALT pins beyond the RESET instruction;
- side-effect-free memory peeking; and
- complete machine save states, deterministic replay and rewind.

Accordingly, the project does not claim:

- the contents of a bus-error frame (the vector is taken; the frame's
  stacked PC, IR and I/N bit are not checked by any oracle here);
- cycle placement inside an instruction beyond `step_clocks`, TAS's
  read-modify-write shape, wait states, or pin timing;
- the 68010 and later (VBR, loop mode, the 68010 frame, `MOVEC`, `MOVES`,
  the 68020's bus and addressing), or the 68008's timing; or
- a complete arcade board, console or computer.

These are scope boundaries, not unfinished promises; the claim boundary in
[docs/claims.md](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/claims.md) is exact about each.

## Learning and inspection

New to the 68000? Read [Start here](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/start-here.md) first: the register
file, the status register, how an opcode word splits into fields, the twelve
effective-address modes, the exception model and the prefetch queue, each
section naming the module that implements it.

The implementation is organised by instruction family behind a small public
`M68000CPU` facade. Every opcode handler's docstring starts with its
Motorola name, so `grep MOVEM src/` lands on the implementation, and ends
with where its rule comes from: a page of the *M68000 Programmer's Reference
Manual* or a table of the *User's Manual*, plus the SingleStepTests file,
the WinUAE run or the hardware tables that pin any rule the manuals do not
give (the PC an address error stacks, the order of bus cycles, an undefined
flag). A test (`tests/test_readability.py`) enforces the name, the citation
and the evidence line the same way the corpus gate enforces correctness.

The tree also provides immutable `CPUState` capture and restoration for
processor-owned state and a disassembler for every first word, in MAME's
spelling, checked against MAME's own disassembly of 1,300 instructions of
real game code. Disassembly requires an explicit side-effect-free word
reader: debugging must not accidentally acknowledge a device.

See [CPU state](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/cpu-state.md), [disassembly](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/disassembly.md),
[undocumented behaviour](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/undocumented-behavior.md) and
[timing](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/timing.md).

## Diagnostics and tooling

- `DebugSession` wraps an existing host with bounded execution, execute
  breakpoints, watchpoints and bus-access tracking, boundary-kind records
  and bounded history. It adds nothing to the hot path when unused.
- `CommandDebugger` is a dependency-free text-stream frontend; `python -m
  m68000_python --load FILE@ADDR --pc ADDR` or `--zip ROMS.zip:even,odd@0
  --reset` steps a binary without writing a host.
- Traces are versioned JSON Lines; `first_trace_divergence` and
  `first_session_divergence` stop at the first differing boundary of two
  files or two live machines, with every field named.
- `python -m m68000_python.conformance trace|diff` runs a manifest (memory,
  initial state, interrupt events, BERR ranges, replayed devices) on the
  reference and diffs another core's trace against it, bus accesses
  included: the kit and the certification ladder for a 68000 core in
  another language.

See [debug sessions](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/debug-session.md), [trace comparison](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/trace-comparison.md),
[the trace schema](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/trace-schema.md) and [conformance](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/conformance.md).

## Development

Run the ordinary quality gate:

```text
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python examples/minimal_m68000_host.py
```

The corpora are external artifacts and are not bundled. Fetch the pinned
gate corpus (138 MB) with:

```text
python scripts/fetch_test_vectors.py
python -m pytest -q tests/test_corpus.py tests/test_step_clocks.py
```

`--with-680x0` adds the second corpus (203 MB, unlicensed, detector only);
`--files NOP,ABCD` fetches a few files for a quick start. The referees,
the detector, the coverage map and the mutation run each have their command
in the document that records their result.

## Project records

- [The claim boundary](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/claims.md): every behaviour with its status
- [0.1.0 release notes](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/releases/0.1.0.md)
- [Validation evidence and scope](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/validation.md)
- [Referees: WinUAE and Musashi, built and run](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/referees.md)
- [Coverage: what the evidence reaches](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/coverage.md)
- [Mutation: what the suite would notice](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/mutation.md)
- [Public API stability](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/api-stability.md)
- [Interrupt lifecycle](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/interrupt-lifecycle.md)
- [CPU state](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/cpu-state.md)
- [Disassembly](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/disassembly.md)
- [Debug sessions](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/debug-session.md)
- [Trace comparison](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/trace-comparison.md)
- [Trace schema](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/trace-schema.md)
- [Conformance: proving another core is the same CPU](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/conformance.md)
- [Start here: 68000 primer](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/start-here.md)
- [Timing](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/timing.md)
- [Undocumented behaviour](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/undocumented-behavior.md)
- [MAME as a trace oracle](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/mame-oracle.md)
- [AI-assisted development](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/ai-assisted-development.md)
- [Contribution guidance](https://github.com/alewman/m68000-python/blob/v0.1.0/CONTRIBUTING.md)
- [History: the handoff brief and the worklog](https://github.com/alewman/m68000-python/blob/v0.1.0/docs/README.md)

## License

MIT. The Motorola manuals, MAME, WinUAE, Musashi, the SingleStepTests
corpora and the BCD verifier retain their own licenses and are cited, not
bundled.
