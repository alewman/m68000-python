# Conformance: proving another core is the same CPU

This page is for someone writing a 68000 core in another language who wants
to use `m68000-python` as the reference. It says what "the same CPU" means
here, how to check it after every instruction, which oracles to run in what
order, and what you may claim after each. The tooling is
`m68000_python.conformance`; the trace format is
[trace-schema.md](trace-schema.md). The shape is z80-python's, whose kit
z80-rust was certified with.

## What must match

At every processor boundary, all of:

- the boundary **kind** (instruction, trace, interrupt, stopped idle,
  halted idle);
- the **clock** total the boundary consumed;
- the instruction's **address and bytes**, when it is an instruction;
- all **fourteen fields of `CPUState`** before and after, the prefetch queue
  (`ir`, `irc`), `trace_pending`, `nmi_edge` and the running `clock`
  included;
- **every bus access** the boundary made, in order: read or write, the
  24-bit address, the value, the size.

Nothing less. A core that matches registers but not the queue, or the state
but not the bus order, is not equivalent for the purposes of this project,
and the tools here say so at the first boundary where it fails.

## The manifest: one machine for both cores

Traces are only comparable when both cores ran the same machine. A manifest
pins that down:

```json
{
  "version": 1,
  "name": "exceptions",
  "host": "flat",
  "memory": [{"address": 4096, "data": "70144e40..."}],
  "reset": false,
  "initial": {"pc": 4096, "ssp": 32768, "sr": 8192},
  "acknowledge": {"4": 64, "5": "spurious", "6": "autovector"},
  "bus_error": [{"address": 15728640, "length": 16}],
  "tas_write": "write",
  "events": [{"at_step": 2, "kind": "ipl", "level": 4}, {"at_step": 3, "kind": "ipl", "level": 0}],
  "stop": {"max_steps": 100, "on_idle": true, "at_pc": []}
}
```

| Key | Meaning |
| --- | --- |
| `memory` | Segments placed before the run. `data` is hex with no whitespace; or `file` (relative to the manifest) with optional `offset` and `length`. Everything else is zero. Segments must fit below `0x1000000`. |
| `reset` | `true`: after loading memory the host calls `reset()` (SSP and PC from the vectors at 0); its clocks land in `clock`; it produces no record. Excludes `initial`. |
| `initial` | Otherwise, any subset of the `CPUState` fields, restored with `restore_state`; the rest take `CPUState`'s defaults (`sr` `0x2700`, everything else zero or false). When neither `ir` nor `irc` is given they are read from memory at `pc` and `pc + 2`, as `set_pc` would, but not through the bus: no BERR, no device read, no clocks. Giving one without the other is an error. |
| `host` | `flat` or `replay`, defined below. |
| `acknowledge` | The interrupt acknowledge cycle's answer per level, keys `"1"` to `"7"`: a vector number 0-255, `"autovector"` or `"spurious"`. An unlisted level autovectors. (The reference passes an `acknowledge` callable only when the map is not empty; without one the core autovectors every level, which is the same machine.) An uninitialized device is `15`. |
| `bus_error` | Address ranges (`address`, `length`) where the bus asserts BERR. |
| `tas_write` | `"write"` (the default): TAS's write cycle is an ordinary byte write. `"drop"`: it never completes and nothing is stored, the Genesis behaviour. |
| `replay` | For the `replay` host only: `devices`, a list of address ranges, and `reads`, `{"file": ...}` or `{"data": hex}`, a sequence of big-endian 16-bit values. |
| `events` | Host actions applied immediately *before* the boundary numbered `at_step` (records count from 0, every kind included), ordered by step. `ipl` with `level` 0-7 calls `set_ipl(level)`; `reset` calls `reset()`, which produces no record and adds its clocks to `clock`. |
| `stop` | `max_steps` is mandatory. `at_pc` stops before a boundary whose state's `pc` (the address of the instruction in IR) is listed. `on_idle` (default `true`) stops before a boundary that would be `halted_idle` or `stopped_idle` when no event remains. |

The **host** a port must implement to be comparable:

- **`flat`**: 16 MiB of RAM over the 24-bit address space. Reads return its
  bytes (a word big-endian, high byte at the even address), writes store
  them. On every access (read or write, byte or word, program or data, and
  TAS's write), an address inside a `bus_error` range raises a bus error; a
  word access is checked at its address only, which is always even. The
  core masks addresses to 24 bits before the host sees them.
- **`replay`**: `flat`, plus device windows. After the BERR check, a read
  inside a window does not read memory: it takes the next value of the
  reads stream, a byte read its low 8 bits, and once the stream is exhausted
  every such read returns `0xFFFF` (`0xFF`). A write inside a window is
  discarded. This is how a recorded run of a real machine becomes a
  manifest: the reads its devices answered, in the order the CPU made them.

The order of each boundary is: due events, `at_pc`, `on_idle`, then the
step budget, then the boundary itself.

## Producing a trace from your core

Write one JSON Lines record per boundary as specified in
[trace-schema.md](trace-schema.md), **with `accesses`**: the reference's
traces always carry them, and the comparison checks them when both sides
do. Omit `mnemonic` and `operands`; give the instruction's address and
every byte it occupied, and the reader fills in the text with this
project's disassembler.

Record accesses exactly as the reference does, which follows from how
`DebugSession` wraps the host's four bus callables:

- a read is recorded when it returns, so a read that raises a bus error is
  **not** recorded;
- a write is recorded before it is made, so a write that raises a bus error
  **is** recorded;
- TAS's write goes through the host's `tas_write` when there is one. Under
  `"write"` there is none: the write is the ordinary (tracked) byte write,
  recorded like any other write. Under `"drop"` the host's callable checks
  the `bus_error` ranges, then discards the write, and nothing is recorded.
  (In a manifest a TAS operand inside a BERR range faults on TAS's read, so
  the write's check is never reached; it is specified for completeness.)
- an access that faults with an address error never reaches the bus and is
  not recorded;
- the interrupt acknowledge cycle is not an access.

## Comparing

```text
python -m m68000_python.conformance trace manifest.json --out reference.jsonl
python -m m68000_python.conformance diff  manifest.json yours.jsonl
```

`diff` runs the reference core in lockstep with your trace and stops at the
first differing field, printing the position, the instruction there, and
every differing path with both values. It reads lazily, so `yours.jsonl` can
be a pipe from a still-running core (`-` for stdin), and a long run stops at
the first bad instruction rather than the end. Exit status is 0 for
identical, 1 for a divergence, 2 for a malformed manifest or trace.

`examples/conformance/` holds three manifests with their committed
reference traces: `flags-and-branches` (arithmetic and flags, every
addressing mode, branches, DBcc, BSR/JSR, MOVEM, LINK, MULU/DIVU, shifts,
ABCD, TAS, then STOP), `exceptions` (TRAP, TRAPV, CHK, divide by zero,
ILLEGAL, line A and F, trace, an address error, a bus error from
`bus_error`, the RESET instruction, MOVE to SR into user mode and a
privilege violation there, STOP ended by an `ipl` event, and a double bus
fault that halts) and `tas-drop` (`tas_write: "drop"`).
`examples/conformance/interrupts/` holds the interrupt and STOP scenarios of
rung 6 ([validation](validation.md)) as manifests with events: a level above
the mask taken, one at the mask held until the mask is lowered, level 7's
edge, the vectored, spurious and uninitialized acknowledge answers, trace
before a pending interrupt, STOP waiting for a level above its new mask,
STOP in user mode, a traced STOP, and the autovector at each of the ten
E-clock phases (one manifest each: every bus access and internal step costs
an even number of clocks, and only the autovector wait can change the
clock's parity, so one run cannot reach every phase). `build.py` there
assembles them all, checking every instruction against the disassembler,
and the test suite regenerates both the manifests and the traces.

### Rung 3: real code, replayed

`validation/lockstep.py export` runs the MAME lockstep of rung 4
([validation](validation.md)) and writes it as a `replay` manifest in the
run's directory under `validation/mame_runs/` (never committed: it holds the
ROM): the program ROM as a `file` segment, the board's device window as
`replay.devices`, every value the core read from it as the reads stream,
the interrupt the lockstep asserts for one step as an `ipl` event pair, and
the state before the first instruction as `initial`. System 16B's i8751
resets the CPU once, 40 instructions in, and the lockstep resynchronises
the registers from MAME there; no event can express that, so its manifest
begins at the state after the reset.

The flat host is not the board: it has no RAM mirror, it stores writes
outside the window (the board ignores writes to ROM), and the lockstep's
clock resynchronisations after a board stall cannot be expressed (they move
only the E-clock phase, never the path). So an exported run follows the
game only as far as `validation/lockstep.py follow` measures, by comparing
the replay host's registers with MAME's before every instruction; for
these two runs that is the whole run. Even a run that left the game's path
would still be a long, deterministic run of real 68000 code with real
interrupts, which is all core-against-core equivalence needs: both cores
run the same machine.

Measured on PyPy 7.3.20 (`trace` to a pipe counting its bytes; `export`
takes about 100 s and `follow` about 110 s each). A trace this size is for
streaming into `diff`, not for keeping. `diff` of the Genesis run's first
300,000 records against their own reference trace took 3.7 s (about 80,000
records/s), so a single lockstep pipe over a whole run finishes in well
under an hour and the kit has no checkpoint command.

| Run | Records | Replayed reads | On MAME's path | Reference trace, PyPy |
| --- | ---: | ---: | --- | --- |
| Genesis Altered Beast, 40 s (`genesis-altbeast_md`) | 28,253,448 | 842,087 | every one of its 28,249,660 instructions | 426 s (66,000 records/s), 22.6 GB |
| System 16B `altbeast`, 30 s (`altbeast-altbeast-30s`) | 24,597,382 | 10,667,916 | every one of its 24,595,591 instructions, from MAME's 41st line | 372 s (66,000 records/s), 19.3 GB |

## Certification ladder

Run these in order. Each is cheaper than the next and each earns a specific
claim.

| Step | What | What you may then say |
| --- | --- | --- |
| 1 | Every manifest in `examples/conformance/` and `examples/conformance/interrupts/` diffs clean. | Your trace producer, access recording and host model are right. |
| 2 | SingleStepTests/m68000 natively: all 127 files, 317,500 cases at the pinned revision, comparing registers, SR, both stack pointers, the prefetch queue, RAM, the bus transactions in order with their function codes, and the clock total; and the clock at which each access ends within its step over the 261,894 cases without an address error, as `tests/test_step_clocks.py` checks `step_clocks`. `tests/corpus.py` is the reference runner and documents the case shape. | Instruction semantics, flags, prefetch, bus order, the stacked PC of every address error and timing match the gate. |
| 3 | The replay manifests of the MAME runs diffed in lockstep against the reference. | Equivalent to `m68000-python` over tens of millions of instructions of real code with real interrupts. |
| 4 | flamewing's BCD verifier tables natively: every input of ABCD, SBCD and NBCD, 525,312 cases, result and X N Z V C (`tests/test_bcd.py`). | ABCD, SBCD and NBCD, undefined flags included, agree with tables recorded on two Sega Genesis models (T1). |
| 5 | The interrupt scenarios in `examples/conformance/interrupts/`. | Interrupt, trace and STOP sequencing, and the E-clock wait at every phase, equivalent to the reference. |

State the exact `m68000-python` commit, the trace schema version, the
SingleStepTests/m68000 revision and the BCD verifier revision you certified
against. A claim without those four is not reproducible.

## What this does not cover

Wait states, bus arbitration (BR/BG), the function code of a completed
access (step 2 checks it against the corpus, but traces do not carry it),
the `address_error` and `reset_devices` hooks, and everything a board does
around the CPU are outside the trace and outside these claims, as they are
outside the core's own ([claims](claims.md)). The kit compares processor
observations; a board compares its own events separately
([trace comparison](trace-comparison.md)).
