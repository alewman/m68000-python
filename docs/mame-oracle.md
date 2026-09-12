# MAME 0.285 as an emulator-derived 68000 trace oracle

MAME's 68000 is the microcoded core (see [validation](validation.md), tier
T3). Running a real System 16 game under it and logging one line per
instruction gives a long-sequence oracle for the future core: the same ROM,
the same reset, the same vblank interrupts, compared instruction by
instruction. This page records the exact command line, the Lua script, the
register names, what came out, and the traps. Everything here was run on
2026-09-11/12 on this machine with `/usr/games/mame` = `0.285 (unknown)`.

ROMs are used in place from
`/data/emu/source/myrient.erista.me/files/MAME/ROMs (non-merged)/` through
`-rompath`; they are never copied, and neither ROMs nor traces are committed
(`.gitignore` covers `error.log`, `*.trace`, `validation/mame_runs/`).

## The recipe

Lua autoboot script (`trace.lua`; MAME's own Lua, no plugins):

```lua
local dbg = manager.machine.debugger
dbg.visible_cpu = manager.machine.devices[":maincpu"]
dbg:command('trace FILE,,noloop,{logerror "%X %X %X\n",pc,d0,sr}')
dbg:command("go")
```

Command line (one line; `$RUNDIR` is a fresh, empty directory):

```text
/usr/games/mame altbeast \
  -rompath "/data/emu/source/myrient.erista.me/files/MAME/ROMs (non-merged)" \
  -homepath "$RUNDIR" -video none -sound none -nothrottle -noreadconfig \
  -skip_gameinfo -debug -debugger none -log -autoboot_script "$RUNDIR/trace.lua" \
  -str 3
```

`-str N` (`-seconds_to_run`) stops after N emulated seconds; omit it for an
open-ended run. Run it with the current directory set to `$RUNDIR`: the
`-log` file `error.log` and the trace file named in the `trace` command are
written to the **current directory**, not to `-homepath` (which only takes
`cfg/`, `nvram/`, `snap/`). This is the one correction to the recipe as
handed over.

Two outputs appear:

- **`error.log`**: one line per executed instruction from the `logerror`
  action, after a `Soft reset` line and the driver's own log lines (`[:mcu]
  write of un-hooked port …` on `altbeast`, `[:upd] ROM region ':upd' not
  found`, netlist solver notes). This is the oracle stream.
- **`FILE`** (or whatever name the `trace` command's first argument gives):
  the debugger's own trace, one disassembled line per instruction
  (`000400: bra $40e`). Useful for reading, ~20 bytes per instruction.

## Verified runs

`shinobi` (System 16A), the brief's exact format, 2 emulated seconds, fresh
directory: exit 0, `Average speed: 35.71%`, 1,867,339 three-field lines in
`error.log`, 43.8 MB `FILE`. First lines:

```text
Soft reset
402 0 2700
410 0 2700
418 0 2708
41C 0 2708
420 0 2700
```

`altbeast` (System 16B), labelled format, 3 emulated seconds, fresh
directory: exit 0, 2,306,551 lines (152 MB) in `error.log`, 2,306,026 lines
(53.8 MB) in the trace file. The Lua line was

```lua
dbg:command('trace trace-altbeast.txt,,noloop,{logerror "PC=%06X SR=%04X D0=%08X D1=%08X A0=%08X A7=%08X\n",pc,sr,d0,d1,a0,a7}')
```

and the output:

```text
PC=000402 SR=2700 D0=00000000 D1=00000000 A0=00000000 A7=000000A7
PC=000410 SR=2700 D0=00000000 D1=00000000 A0=00000000 A7=000000A7
...
PC=000494 SR=2704 D0=00000EE5 D1=0000FF00 A0=FFFFC06C A7=000000A7
PC=000492 SR=2704 D0=00000EE4 D1=0000FF00 A0=FFFFC06C A7=000000A7
```

with the trace file beginning

```text
000400: bra     $40e
00040E: lea     $ff00.w, A7
000412: move    #$2700, SR
000416: nop
```

`A7=000000A7` is not the stack pointer: **MAME's 68000 does not register
a symbol named `A7`**, and the debugger's expression parser read `a7` as
the hexadecimal number `0xA7`. The active stack pointer is `sp`. Use the
names in the next section.

Throughput: 2–3 emulated seconds took roughly 7–10 wall seconds per run
(`Average speed` 30–36% of real time), dominated by `logerror`; a
100-million-instruction trace is about an hour and ~7 GB of `error.log` at
the labelled format, so pick the fields and the run length deliberately, or
trace in segments with save states.

One earlier `shinobi` run, started in a directory that already held cfg
and log files from unrelated MAME sessions, produced five-field lines
(`804 0 FFFF F002 0`) from the same three-field format. It was not
reproduced in a fresh directory and is not explained; always trace from an
empty directory.

## MAME's 68000 register names

From `src/devices/cpu/m68000/m68000.cpp` at `mame0285` (`state_add` calls),
usable in `logerror` expressions and the debugger, case-insensitive:

| Name | Meaning |
| --- | --- |
| `pc` | The debugger's PC (`m_pc`). In the microcoded core this is the address of the *next* word to enter the queue, not the executing instruction |
| `curpc` | `m_ipc`, the address of the instruction being executed. Use this one for a per-instruction trace when the value matters |
| `ir` | Instruction register (the executing opcode word) |
| `sr` | Status register, all 16 bits |
| `d0`–`d7` | Data registers |
| `a0`–`a6` | Address registers |
| `usp` | User stack pointer (`m_da[15]`) |
| `sp` | The other stack pointer slot (`m_da[16]`); with `usp`, one of them is the active A7 depending on the S bit. Log both when in doubt |

There is no `a7`, `ssp`, `ccr` or `vbr` symbol. In the runs above, `pc` in
the `logerror` line printed values such as `402` while the trace file's
first line was `000400`, consistent with `pc` being `curpc + 2` at the
moment the trace action runs; the future lockstep comparer must decide
which of the two it matches and record that choice. `curpc` is the safer
field.

## What the trace does and does not give

- One line per instruction *and* per exception entry the debugger counts
  as an instruction boundary; the interrupt at vblank shows as a jump to
  the vector's target with the mask raised in `sr`.
- Registers as the debugger reads them between instructions; no bus
  transactions, no cycle counts. For cycles, add `totalcycles` or the
  device's `cycles` symbol to the format (not verified here).
- Memory reads in the format (`{b@addr}`, `{w@addr}`) go through the
  debugger's side-effect-free path.

## Things that did not work, from the earlier session and confirmed here

- `tracelog` in Lua produced nothing; `trace … {logerror …}` is the working
  form.
- `focus` in the trace command broke the action list.
- `device.debug:bpset` from Lua segfaulted MAME 0.285; use `dbg:command`
  strings for breakpoints too.

## Boards and clocks for the future host

`altbeast` (`sega/segas16b.cpp`): 68000 at 10 MHz, level-4 vblank
interrupt (`irq4_line_hold`), 60.054 Hz, i8751 MCU. `shinobi`
(`sega/segas16a.cpp`): 68000 at 10 MHz, same interrupt, 4 MHz Z80. Details
in [timing](timing.md). The System 16 memory map and the 315-5195 mapper
are the host's problem; the oracle stream above is independent of them.
