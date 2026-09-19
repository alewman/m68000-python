# Trace schema (version 1)

A trace is the observable behavior of a 68000 core written down one
processor boundary at a time, in z80-python's shape (its
`docs/trace-schema.md`), so two cores can be compared by
`first_trace_divergence`. `src/m68000_python/trace.py` implements it; if the
two disagree, the code is the specification.

JSON Lines, one object per boundary, written with sorted keys. Keys:

| Key | Type | Meaning |
| --- | --- | --- |
| `version` | integer | `1` |
| `sequence` | integer | producer-local counter, informational |
| `kind` | string | `instruction`, `trace`, `interrupt`, `stopped_idle` or `halted_idle` |
| `cycles` | integer > 0 | clocks, exactly as `step()` returned them |
| `instruction` | object or null | `address`, `data` (the instruction's bytes as lowercase hex), and optionally `mnemonic` and `operands` together; null for every other kind |
| `before`, `after` | state object | every `CPUState` field (docs/cpu-state.md); `d` and `a` are arrays |
| `accesses` | array, optional | `[kind, address, value, size]` per bus access, `kind` `r` or `w`, size 1 or 2; absent means not recorded |

A reader decodes `data` at `address` with this package's disassembler and
rejects a record whose bytes are not exactly one instruction, so a producer
in another language need only get the bytes right.
