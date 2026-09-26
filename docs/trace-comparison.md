# Trace comparison

`first_trace_divergence()` compares two deterministic streams of
`StepRecord` values and returns the first unequal processor boundary.
`iter_trace_divergences()` yields every unequal aligned position without
loading either complete trace.

```python
divergence = first_trace_divergence(first_session.history, second_session.history)
if divergence is not None:
    for difference in divergence.differences:
        print(difference.path, difference.left, difference.right)
```

For live targets, `first_session_divergence()` advances two `DebugSession`
values in lockstep under a mandatory finite budget and stops at the first
boundary whose processor observations differ:

```python
divergence = first_session_divergence(first, second, max_steps=1_000_000)
```

Each session keeps its own bounded history, which supplies the instructions
immediately before the divergence without the comparator buffering the run.

## What is compared

- the boundary kind;
- the instruction's address and bytes (its text follows from the bytes);
- the clock total `step()` returned; and
- every one of the fourteen fields of the before and after `CPUState`
  values, the prefetch queue included: two cores that read a different word
  into IRC differ one instruction *before* they execute anything different,
  and the comparison says so.

Bus accesses are compared only when both records carry them, so a trace
written without tracking diffs cleanly against one written with it. The
session-local `StepRecord.sequence` is excluded from equality: traces are
aligned by position, so independently captured windows compare even when
their counters differ. If one trace ends first, the divergence's path is
`record` with `present` on the remaining side. `TraceDivergence.as_dict()`
is compact, deterministic, JSON-compatible evidence: the position, both
sequence numbers and the field-level differences, without duplicating the
states.

## Machine events

This API compares processor observations only. Memory contents, device
events, frames and scheduler boundaries are the host's; a board compares
its own event stream separately and combines the two first divergences in
its own evidence. That keeps device policy out of the core. The MAME
lockstep in `validation/lockstep.py` is the model: it compares the
processor before every instruction and checks the board's writes beside it.

## Memory behaviour

Inputs are consumed incrementally. `first_trace_divergence()` stops reading
as soon as it finds an unequal position; `iter_trace_divergences()` retains
nothing beyond the current aligned pair, so both work on generators and on
large files.

## Persisted traces

`write_trace(records, stream)` writes deterministic, versioned JSON Lines
without buffering; `read_trace(stream)` validates and yields one record at a
time, naming the line of a malformed one, so two large files compare
directly:

```python
with open("first.jsonl") as first, open("second.jsonl") as second:
    divergence = first_trace_divergence(read_trace(first), read_trace(second))
```

The format is [the trace schema](trace-schema.md): `TRACE_SCHEMA_VERSION`,
exact instruction bytes, enum string values, every state field, and the
accesses when tracked. Readers reject unknown, missing or invalid fields
rather than silently changing the meaning of evidence; a schema change is a
new version. A producer in another language writes the instruction's
address and bytes only; this package's disassembler supplies the text.
