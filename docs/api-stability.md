# Public API stability

`m68000-python` uses semantic versioning for the public names exported from
the package root (`m68000_python.__all__`) and listed in each public
module's `__all__` (`cpu`, `state`, `debug`, `trace`, `console`, `disasm`,
`conformance`).

## Public contracts

The supported surface is:

- `M68000CPU` and its constructor
  `M68000CPU(read_byte, read_word, write_byte, write_word, *,
  acknowledge=None, function_codes=False, tas_write=None,
  address_error=None, reset_devices=None)`, the embedding contract
  ([README](../README.md), [interrupt lifecycle](interrupt-lifecycle.md));
  `AUTOVECTOR`, `SPURIOUS` and `BusError`;
- the execution and lifecycle methods `step()`, `reset()`, `set_ipl()`,
  `set_sr()`, `set_pc()`, `attach_bus()`, `capture_state()` and
  `restore_state()`, and the read-only properties `PC` and `step_clocks`;
- the processor's registers and state as plain attributes a host reads and
  writes between steps: `R` (a list of sixteen 32-bit values, D0-D7 then
  A0-A7 with A7 the active stack pointer), `SR`, `usp`, `ssp`, `ir`, `irc`
  (the prefetch queue), `ipl`, `clock` (the running count `step()` adds
  to), `stopped`, `halted` and `last_acknowledge_phase`; the four bus
  callables as `read_byte`, `read_word`, `write_byte`, `write_word`; and
  `function_codes` and `tas_write` as given to the constructor. The program
  counter has three spellings for three purposes: `cpu.PC` reads the
  address of the next instruction, `cpu.set_pc(address)` starts execution
  there (it refills the queue, as a jump does), and `CPUState.pc` is the
  same address in a captured state;
- `CPUState` capture and restoration;
- `Instruction`, `disassemble`, `disassemble_bytes`, `disassemble_range`
  and the `WordReader` type;
- `DebugSession`, `DebugTarget`, `BoundaryKind`, `StopReason`, `StepRecord`,
  `RunResult`, `Access` and `next_boundary`, including access tracking
  (`track_accesses=`, `StepRecord.accesses`) and watchpoints
  (`add_watchpoint`, `StopReason.WATCHPOINT`, `RunResult.hits`);
- `CommandDebugger`, `CommandResult`, `CommandError`, the console's number
  grammar (`console.parse_number`: decimal, or `$`/`0x` hexadecimal) and
  the `python -m m68000_python` command line; and
- the trace values and functions: `TRACE_SCHEMA_VERSION`, `TraceDifference`,
  `TraceDivergence`, `step_record_to_dict`, `step_record_from_dict`,
  `write_trace`, `read_trace`, `iter_session_steps`, `compare_step_records`,
  `iter_trace_divergences`, `first_trace_divergence` and
  `first_session_divergence`, and the JSON Lines format of
  [the trace schema](trace-schema.md); and
- the conformance kit, `m68000_python.conformance`'s `__all__` and its
  command line, and the manifest format and host behaviour of
  [conformance](conformance.md) (`MANIFEST_SCHEMA_VERSION` 1).

The package ships a `py.typed` marker, so these annotations are available to
static type checkers. Public dataclass field names, enum values, function
signatures and documented behaviour follow semantic-versioning rules.

Public immutable values validate their fields when constructed.
`DebugTarget` is a runtime-checkable structural protocol, so a board need
not inherit a debugger-specific base class.

## Not public

Underscore-prefixed modules, methods and attributes are implementation
details: `_pc` (the fetch address, four bytes ahead of `PC`), `_fault_pc`,
`_table`, the mixins, the helpers. `tests/`, `validation/`, `scripts/` and
`benchmarks/` are development tools, not the package. JSON produced by the
trace writer is public and versioned; an arbitrary `dataclasses.asdict()`
of a `CPUState` is not a permanent save-file format.

## Compatibility policy

- Patch releases fix defects without intentional public incompatibilities.
- Minor releases may add fields or APIs while preserving existing consumers.
- Breaking public changes require a major release and migration notes, with
  one exception: before 1.0, a minor release may break the public surface
  when `CHANGELOG.md` says so under a **Breaking** heading with the
  migration. The family's other cores use the same clause.
- Hardware-fidelity claims remain bounded by [claims](claims.md); API
  stability does not expand them, and a recertification after a core fix
  is expected, not avoided: the boards built on this core exist partly to
  find such corners.

Development snapshots use a `.dev0` version and are not release promises.
