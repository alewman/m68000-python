# Changelog

All notable changes to `m68000-python` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Open

- **The reset exception's clock total.** `reset()` returns 42 (16 internal
  clocks, the four vector reads, and the two-read refill with its 2 idle
  clocks, as every exception entry refills the queue); UM Table 8-14
  prints 40(6/0). No corpus has a reset-pin case and the referees were not
  run on one. Found on 2026-09-25 when the smoke test asserted the
  docstring's 40; the docstring now says 42 and the difference is listed
  under "Undecidable here" in docs/claims.md.

## [0.1.0] — unreleased

The first release: the whole 68000 instruction set and exception model,
verified up a ladder of oracles ordered by tier, with a claim boundary for
what no available evidence settles.

### Breaking (relative to the development tree megadrive-python and sms-python built against)

- **Console numbers are decimal, or hexadecimal with `$` or `0x`.** The
  console, `console.parse_number` and `python -m m68000_python`'s
  addresses treated a bare number as hexadecimal and `#` as decimal; they
  now follow the family's rule. Migration: write `break $1006` or
  `break 0x1006`, `--pc 0x1000`, and drop the `#`.
- **`reset_devices` is a constructor keyword.** The RESET instruction's
  pulse used to reach a `reset_devices` attribute found by `getattr`.
  Migration: `M68000CPU(..., reset_devices=callback)`.

### Added

- The core: every defined first word (45,815), the prefetch queue, address
  and bus errors with the seven-word frame, the interrupt lifecycle with
  the acknowledge cycle and the E-clock wait, trace, STOP, RESET, and
  `step_clocks` for the clock at which each access ends within a step.
- The claim boundary (docs/claims.md): every behaviour labelled verified,
  strong, provisional, contested, undecidable here or outside the contract,
  by the independent lineages that support it.
- Oracles and referees: flamewing's hardware-captured BCD tables (T1),
  WinUAE's CPU-tester core and Musashi built from pinned sources and run
  over the gate (docs/referees.md), the SingleStepTests/m68000 gate with
  every bus access compared and no case excluded, the MAME 0.285 lockstep
  on 52.8 million instructions of real code, the 680x0 corpus as a
  classified detector, and MAME's `m68000.lst` against the decoder.
- The suite measured: a coverage map over encodings, behavioural paths and
  source lines (docs/coverage.md) and 176 seeded mutants of which 174 are
  killed, the two survivors equivalent (docs/mutation.md).
- Every handler cites its manual page and names the corpus file, referee
  run or hardware tables that pin what the manual leaves open;
  `tests/test_readability.py` enforces it.
- Tooling in z80-python's shape: `CPUState`, a disassembler in MAME's
  spelling (checked against 1,300 instructions of MAME's own disassembly
  of real game code), `DebugSession` with breakpoints, watchpoints,
  bus-access tracking and board targets, versioned JSON Lines traces with
  first-divergence comparison of files and of live sessions,
  `CommandDebugger`, and `python -m m68000_python` with `--zip` for
  even/odd ROM pairs.
- Examples: `examples/minimal_m68000_host.py`, `examples/interrupt_host.py`
  and a committed reference trace; a benchmark harness with four named
  workloads and a same-process A/B of two revisions.
- CI on every push (CPython 3.11-3.14 and PyPy 3.11, the corpus gate on two
  interpreters, a wheel build and installed-API smoke test) and a weekly
  Oracles workflow that rebuilds the referees and fails when any recorded
  number moves.

### Changed

- **9% faster on CPython, 37% on PyPy** (the `base` workload): a speed
  ladder of five candidate rungs, one commit per rung, every oracle green
  at each and measured with `benchmarks/compare_revisions.py`. Kept:
  `MASK`/`MSB` as tuples (A) and the refills reading the program word
  themselves (C); reverted or not adopted: the A7 byte step inlined (B),
  flags computed inside `_add` (D), the function-code wrappers (E). The
  table is in docs/validation.md, "Speed".

### Fixed

Each as a failing test first, then the fix, in the verification rounds
before this release:

- A traced illegal, line A/F or privileged instruction was followed by a
  trace exception; UM 6.3.8, MAME's microcode and WinUAE say an
  instruction that was not executed is not traced (8760315).
- A fault while TRAPV's trap was processed stacked the next opcode as IR;
  WinUAE (run) and MAME's microcode keep TRAPV (e057279).
- A `BusError` raised on TAS's write half escaped `step()` instead of
  becoming the bus-error exception (36862e5).
- The I/N bit of a fault during group 2 exception processing was set; WinUAE
  (run) and MAME's microcode clear it (e395be9).
- The disassembler printed every undefined word as `illegal`; MAME prints
  `dc.w $xxxx; ILLEGAL` for all but `$4AFC`, and so does the core's now.
