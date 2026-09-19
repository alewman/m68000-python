"""Deterministic boundary traces: write, read, and compare them incrementally.

A trace is a JSON Lines file of :class:`~m68000_python.debug.StepRecord`
values, one processor boundary per line (docs/trace-schema.md).  Two cores
that produce equal traces for the same program and host behave identically
as far as software can tell; ``first_trace_divergence`` finds where they do
not without reading either trace to the end.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields
from itertools import zip_longest
from typing import TextIO

from m68000_python.debug import BoundaryKind, DebugSession, StepRecord
from m68000_python.disasm import disassemble_bytes
from m68000_python.state import CPUState

TRACE_SCHEMA_VERSION = 1
TraceValue = int | bool | str | tuple | None
_STATE_KEYS = tuple(field.name for field in fields(CPUState))
_RECORD_KEYS = {"version", "sequence", "kind", "cycles", "instruction", "before", "after"}
_MISSING = object()


@dataclass(frozen=True, slots=True)
class TraceDifference:
    """One unequal observation at an aligned trace position."""

    path: str
    left: TraceValue
    right: TraceValue

    def as_dict(self) -> dict[str, TraceValue]:
        return {"path": self.path, "left": self.left, "right": self.right}


@dataclass(frozen=True, slots=True)
class TraceDivergence:
    """All differences at one aligned position."""

    position: int
    left: StepRecord | None
    right: StepRecord | None
    differences: tuple[TraceDifference, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "position": self.position,
            "left_sequence": None if self.left is None else self.left.sequence,
            "right_sequence": None if self.right is None else self.right.sequence,
            "differences": [difference.as_dict() for difference in self.differences],
        }


# -- records <-> JSON ---------------------------------------------------------


def step_record_to_dict(record: StepRecord) -> dict[str, object]:
    """The JSON-compatible form of one record (docs/trace-schema.md)."""
    instruction = None
    if record.instruction is not None:
        instruction = {
            "address": record.instruction.address,
            "data": record.instruction.data.hex(),
            "mnemonic": record.instruction.mnemonic,
            "operands": list(record.instruction.operands),
        }
    out: dict[str, object] = {
        "version": TRACE_SCHEMA_VERSION,
        "sequence": record.sequence,
        "kind": record.kind.value,
        "cycles": record.cycles,
        "instruction": instruction,
        "before": _state_to_dict(record.before),
        "after": _state_to_dict(record.after),
    }
    if record.accesses is not None:
        out["accesses"] = [list(access) for access in record.accesses]
    return out


def step_record_from_dict(data: dict) -> StepRecord:
    """Validate one decoded JSON record and rebuild it."""
    if type(data) is not dict:
        raise ValueError("a trace record must be a JSON object")
    keys = set(data)
    if not _RECORD_KEYS <= keys or keys - _RECORD_KEYS - {"accesses"}:
        raise ValueError(f"trace record keys must be {sorted(_RECORD_KEYS)} (+ accesses)")
    if data["version"] != TRACE_SCHEMA_VERSION:
        raise ValueError(f"unsupported trace version {data['version']!r}")
    instruction = None
    if data["instruction"] is not None:
        spec = data["instruction"]
        instruction = disassemble_bytes(bytes.fromhex(spec["data"]), spec["address"])
    accesses = None
    if "accesses" in data:
        accesses = tuple(tuple(access) for access in data["accesses"])
    return StepRecord(
        sequence=data["sequence"],
        kind=BoundaryKind(data["kind"]),
        before=_state_from_dict(data["before"]),
        after=_state_from_dict(data["after"]),
        cycles=data["cycles"],
        instruction=instruction,
        accesses=accesses,
    )


def write_trace(records: Iterable[StepRecord], stream: TextIO) -> int:
    """Write records as JSON Lines with sorted keys; return how many."""
    count = 0
    for record in records:
        stream.write(json.dumps(step_record_to_dict(record), sort_keys=True, separators=(",", ":")))
        stream.write("\n")
        count += 1
    return count


def read_trace(stream: TextIO) -> Iterator[StepRecord]:
    """Read JSON Lines records lazily; blank lines are ignored."""
    for number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        try:
            yield step_record_from_dict(json.loads(line))
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"trace line {number}: {exc}") from exc


def iter_session_steps(session: DebugSession, *, max_steps: int) -> Iterator[StepRecord]:
    """Yield ``max_steps`` live boundaries from a session without buffering them."""
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")
    for _ in range(max_steps):
        yield session.step()


# -- comparison ---------------------------------------------------------------


def compare_step_records(left: StepRecord, right: StepRecord) -> tuple[TraceDifference, ...]:
    """Every differing field of two aligned records (sequence numbers are ignored).

    Bus accesses are compared only when both records carry them.
    """
    out: list[TraceDifference] = []
    _append(out, "kind", left.kind.value, right.kind.value)
    _append(out, "cycles", left.cycles, right.cycles)
    li, ri = left.instruction, right.instruction
    if (li is None) != (ri is None):
        _append(
            out, "instruction", None if li is None else li.text, None if ri is None else ri.text
        )
    elif li is not None and ri is not None:
        _append(out, "instruction.address", li.address, ri.address)
        _append(out, "instruction.data", li.data.hex(), ri.data.hex())
    for side in ("before", "after"):
        a, b = getattr(left, side), getattr(right, side)
        for key in _STATE_KEYS:
            _append(out, f"{side}.{key}", getattr(a, key), getattr(b, key))
    if left.accesses is not None and right.accesses is not None:
        _append(out, "accesses", tuple(left.accesses), tuple(right.accesses))
    return tuple(out)


def iter_trace_divergences(
    left: Iterable[StepRecord], right: Iterable[StepRecord]
) -> Iterator[TraceDivergence]:
    """Yield every unequal aligned position, lazily, until both traces end."""
    for position, (a, b) in enumerate(zip_longest(left, right, fillvalue=_MISSING)):
        if a is _MISSING:
            yield TraceDivergence(position, None, b, (TraceDifference("record", None, "present"),))
        elif b is _MISSING:
            yield TraceDivergence(position, a, None, (TraceDifference("record", "present", None),))
        else:
            differences = compare_step_records(a, b)
            if differences:
                yield TraceDivergence(position, a, b, differences)


def first_trace_divergence(
    left: Iterable[StepRecord], right: Iterable[StepRecord]
) -> TraceDivergence | None:
    """The first unequal aligned position, or ``None`` when the traces are equal."""
    return next(iter_trace_divergences(left, right), None)


def _append(out: list, path: str, left: TraceValue, right: TraceValue) -> None:
    if left != right:
        out.append(TraceDifference(path, left, right))


def _state_to_dict(state: CPUState) -> dict[str, object]:
    out: dict[str, object] = {}
    for key in _STATE_KEYS:
        value = getattr(state, key)
        out[key] = list(value) if isinstance(value, tuple) else value
    return out


def _state_from_dict(data: dict) -> CPUState:
    if type(data) is not dict or set(data) != set(_STATE_KEYS):
        raise ValueError(f"a state object must have exactly the keys {sorted(_STATE_KEYS)}")
    values = {
        key: tuple(value) if isinstance(value, list) else value for key, value in data.items()
    }
    return CPUState(**values)


__all__ = [
    "TRACE_SCHEMA_VERSION",
    "TraceDifference",
    "TraceDivergence",
    "TraceValue",
    "compare_step_records",
    "first_trace_divergence",
    "iter_session_steps",
    "iter_trace_divergences",
    "read_trace",
    "step_record_from_dict",
    "step_record_to_dict",
    "write_trace",
]
