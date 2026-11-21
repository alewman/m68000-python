# Debugging: DebugSession, CommandDebugger, `python -m m68000_python`

`DebugSession` is a dependency-free controller around an existing
`M68000CPU`, or around a whole board. It does not subclass the host or
alter the instruction core, and it has the shape of z80-python's and
m6800-python's, so a debugger written for one family core reads like one
for another.

```python
session = DebugSession(
    cpu,
    peek_word=memory_word,  # side-effect-free; optional
    history_limit=256,
    track_accesses=True,
)
session.add_breakpoint(0x1006)
session.add_watchpoint(0x3001, "w")
result = session.run(max_steps=100_000, max_cycles=1_000_000)
```

To step through a binary without writing a host:

```text
python -m m68000_python --load program.bin@0x1000 --pc 0x1000 -c "break 0x1006" -c "run 1000"
python -m m68000_python --zip ROMPATH/altbeast.zip:epr-11907.a7,epr-11906.a5@0 --reset
```

The command line puts the images in a flat 16 MB RAM with no devices
(`--zip ZIP:EVEN,ODD@ADDRESS` interleaves a byte-wide ROM pair as 68000
boards wire them; one member loads as it is), starts from `--pc` or the
reset vectors with `--reset`, tracks accesses, runs the `-c` commands after
`registers` and `disassemble`, then reads more from stdin unless `--batch`
is given. Numbers are decimal, or hexadecimal with a `$` or `0x` prefix,
as in every console of this family.

## Boundaries

One `step()` is one boundary, and `BoundaryKind` says which, decided from
the state before the step exactly as `M68000CPU.step()` decides it
(`next_boundary(state)` is public):

| Kind | What the step was |
| --- | --- |
| `instruction` | the instruction in IR, with any exception it raised itself |
| `trace` | the trace exception left by the previous instruction |
| `interrupt` | an interrupt accepted: the acknowledge cycle, the frame, the entry |
| `stopped_idle` | 4 clocks inside STOP with nothing able to end it |
| `halted_idle` | 4 clocks halted by a double bus fault; only `reset()` leaves it |

## Bounded control

Every `run()` needs a positive `max_steps`; it may also take a positive
`max_cycles`. A boundary is atomic, so the returned clock total may exceed
that limit by the last boundary's cost. Runs return a `RunResult` with an
explicit `StopReason`:

- `BREAKPOINT`: before the instruction at a breakpoint executes (a
  breakpoint at the current PC does not stop a run before its first step);
- `WATCHPOINT`: after the step that read or wrote a watched byte, with the
  matching accesses in `RunResult.hits`;
- `STOPPED`: inside STOP with no interrupt able to end it (pass
  `stop_on_stop=False` to consume idle boundaries);
- `HALTED`: a double bus fault (`stop_on_halt=False` likewise);
- `STEP_LIMIT` and `CYCLE_LIMIT`: the budgets.

`session.step()` always advances exactly one boundary and ignores
breakpoints, so a debugger steps off a breakpoint without touching it.

## Records and history

Each `StepRecord` carries the boundary kind, immutable before and after
`CPUState` values, the clock total, the disassembled `Instruction` (when a
`peek_word` was given and the boundary is an instruction) and, when the
session tracks accesses, every bus access the step made, in order, as
`("r" | "w", address, value, size)` with size 1 or 2.

History is a bounded ring owned by the session, oldest first; a limit of
zero disables retention while records are still returned and totals kept.
It holds no memory or device state and is not rewind.

## Targets and the peek

The `DebugTarget` protocol needs only `step()` and `capture_state()`, so an
existing host works without a debugger-specific subclass. A target may be a
whole board: an object whose `step()` runs its devices around one CPU step
and whose `cpu` attribute is the processor (`session.cpu`). The optional
`peek_word` is separate because ordinary machine reads may have device side
effects; without it stepping and breakpoints work and records carry no
disassembly.

## Access tracking and watchpoints

Because the CPU takes its bus as callables, `track_accesses=True` sees every
access without the host's help: it re-attaches the CPU's four callables
through wrappers that log and call the originals (`M68000CPU.attach_bus`),
and `close()` puts the originals back. `add_watchpoint(address, "r" | "w" |
"rw")` needs a tracking session and watches one byte; a word access touches
two bytes, so a watchpoint on either stops the run.

## The command frontend

`CommandDebugger(session).execute("step 3")` returns the lines a terminal
would print, as an immutable `CommandResult`; `interact(stdin, stdout)` is
the prompt loop. The commands, with one-letter aliases where the family has
them:

| Command | Does |
| --- | --- |
| `registers`, `r`, `regs` | D0-D7, A0-A7, PC, SR with its flags and mask, USP, SSP, IPL, clock, STOPPED/HALTED |
| `step [n]`, `s` | run n boundaries (default 1), describing each |
| `run [n]`, `c`, `continue` | run until a breakpoint, watchpoint, STOP, halt or n steps (default 1,000,000) |
| `break ADDR`, `b` / `delete ADDR` | stop before the instruction at ADDR / remove it |
| `watch ADDR [r\|w\|rw]` / `unwatch ADDR` | stop after a step that touches ADDR (needs tracking) |
| `disassemble [ADDR] [N]`, `d`, `dis` | N instructions from ADDR (default: PC, 8) |
| `memory ADDR [N]`, `m` | N bytes from ADDR (default 64, at most 4,096) |
| `set REG VALUE` | d0-d7, a0-a7, usp, ssp, sr (through `set_sr`), pc (through `set_pc`) |
| `ipl LEVEL` | the interrupt level, 0-7 |
| `history [N]` | the last N boundaries (default 10) |
| `help` / `quit`, `q`, `exit` | |

Execution and breakpoint semantics stay in `DebugSession`; the frontend
keeps no competing model and has no terminal-framework dependency.
