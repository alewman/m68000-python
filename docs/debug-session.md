# Debugging: DebugSession, CommandDebugger, `python -m m68000_python`

`DebugSession(cpu, peek_word=..., track_accesses=True)` steps any target with
`step()` and `capture_state()` one boundary at a time and records each as a
`StepRecord`: the boundary kind, the state before and after, the clocks, the
disassembled instruction (when `peek_word`, a side-effect-free word reader,
is given) and, when tracking, every bus access as `(kind, address, value,
size)`. Tracking re-attaches the CPU's four bus callables through wrappers
(`M68000CPU.attach_bus`); `close()` gives the originals back.

Boundary kinds, decided from the state before the step exactly as `step()`
decides: `halted_idle`, `trace`, `interrupt`, `stopped_idle`, `instruction`.

`run(max_steps=...)` stops before a breakpoint's instruction, after the step
that touched a watched byte (a word access touches two), inside STOP, when
halted, or at the step or clock budget. The result says which.

`CommandDebugger(session)` is a line-command frontend (`help` lists the
commands); `python -m m68000_python` puts it on a flat 16 MB RAM host:

```text
python -m m68000_python --zip altbeast.zip:epr-11907.a7,epr-11906.a5@0 --reset -c "step 5"
```

Numbers are hexadecimal (`$`, `0x` or bare); `#` makes one decimal.
