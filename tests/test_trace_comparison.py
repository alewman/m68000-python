"""Traces: JSON Lines persistence, validation, and first-divergence diagnosis."""

from __future__ import annotations

from dataclasses import fields, replace
from io import StringIO

import pytest
from conftest import make

from m68000_python import (
    TRACE_SCHEMA_VERSION,
    BoundaryKind,
    CPUState,
    DebugSession,
    StepRecord,
    TraceDifference,
    compare_step_records,
    first_session_divergence,
    first_trace_divergence,
    iter_session_steps,
    iter_trace_divergences,
    read_trace,
    step_record_from_dict,
    step_record_to_dict,
    write_trace,
)

NOP = 0x4E71


def _history(program: list[int], *, steps: int = 2, **options) -> tuple[StepRecord, ...]:
    cpu, bus = make(program)
    debug = DebugSession(cpu, peek_word=bus.word, **options)
    debug.run(max_steps=steps)
    return debug.history


def test_equal_traces_ignore_session_local_sequence_numbers() -> None:
    left = _history([0x7005, NOP])
    right = tuple(replace(record, sequence=record.sequence + 100) for record in left)

    assert compare_step_records(left[0], right[0]) == ()
    assert first_trace_divergence(left, right) is None
    assert tuple(iter_trace_divergences(left, right)) == ()


def test_first_divergence_reports_instruction_bytes_and_state_fields() -> None:
    left = _history([0x7005, NOP])  # moveq #5, D0
    right = _history([0x7006, NOP])  # moveq #6, D0

    divergence = first_trace_divergence(left, right)

    assert divergence is not None
    assert divergence.position == 0
    differences = {item.path: (item.left, item.right) for item in divergence.differences}
    assert differences["instruction.data"] == ("7005", "7006")
    assert differences["after.d"] == ((5,) + (0,) * 7, (6,) + (0,) * 7)
    assert differences["before.ir"] == (0x7005, 0x7006)  # the queue already held the word
    assert divergence.as_dict()["position"] == 0
    assert divergence.as_dict()["differences"][0]["path"] == "instruction.data"


def test_comparison_reports_kind_cycles_and_each_state_side() -> None:
    record = _history([NOP, NOP])[0]
    changed = replace(
        record,
        kind=BoundaryKind.STOPPED_IDLE,
        cycles=7,
        before=replace(record.before, pc=0x1234),
        after=replace(record.after, stopped=True),
        instruction=None,
    )

    paths = {item.path for item in compare_step_records(record, changed)}

    assert paths == {"kind", "instruction", "cycles", "before.pc", "after.stopped"}


def test_every_cpu_state_field_participates_in_the_comparison() -> None:
    record = _history([NOP, NOP])[0]
    for field in fields(CPUState):
        current = getattr(record.before, field.name)
        if type(current) is bool:
            changed_value = not current
        elif type(current) is tuple:
            changed_value = (current[0] ^ 1, *current[1:])
        elif field.name == "ipl":
            changed_value = (current + 1) % 8
        else:
            changed_value = current ^ 1
        changed = replace(record, before=replace(record.before, **{field.name: changed_value}))
        assert [item.path for item in compare_step_records(record, changed)] == [
            f"before.{field.name}"
        ]


def test_one_sided_exhaustion_is_explicit_and_incremental() -> None:
    records = _history([NOP, NOP])

    divergences = tuple(iter_trace_divergences(records[:1], records))

    assert len(divergences) == 1
    assert (divergences[0].position, divergences[0].left, divergences[0].right) == (
        1,
        None,
        records[1],
    )
    assert divergences[0].differences == (TraceDifference("record", None, "present"),)
    assert divergences[0].as_dict()["right_sequence"] == 1


def test_first_divergence_stops_consuming_after_the_unequal_pair() -> None:
    records = _history([NOP, NOP])
    consumed: list[int] = []

    def right():
        consumed.append(0)
        yield replace(records[0], cycles=5)
        consumed.append(1)
        yield records[1]

    assert first_trace_divergence(records, right()) is not None
    assert consumed == [0]


def test_live_sessions_stop_at_the_first_divergence_and_keep_their_context() -> None:
    # The programs differ at $1006; the queue reads that word during the second
    # step, so the second boundary is where the processors first differ.
    left_cpu, left_bus = make([NOP, NOP, NOP, 0x7005])
    right_cpu, right_bus = make([NOP, NOP, NOP, 0x7006])
    left = DebugSession(left_cpu, peek_word=left_bus.word, history_limit=4)
    right = DebugSession(right_cpu, peek_word=right_bus.word, history_limit=4)

    divergence = first_session_divergence(left, right, max_steps=4)

    assert divergence is not None
    assert divergence.position == 1
    assert {item.path for item in divergence.differences} == {"after.irc"}
    assert (left.total_steps, right.total_steps) == (2, 2)
    assert compare_step_records(left.history[0], right.history[0]) == ()
    with pytest.raises(ValueError, match="max_steps"):
        first_session_divergence(left, right, max_steps=0)


def test_live_session_iteration_requires_a_finite_positive_budget() -> None:
    cpu, _ = make([NOP] * 4)
    debug = DebugSession(cpu)
    assert len(tuple(iter_session_steps(debug, max_steps=2))) == 2
    with pytest.raises(ValueError, match="max_steps"):
        tuple(iter_session_steps(debug, max_steps=0))


def test_trace_values_and_records_are_validated() -> None:
    record = _history([NOP, NOP])[0]
    with pytest.raises(ValueError, match="unequal"):
        TraceDifference("pc", 1, 1)
    with pytest.raises(ValueError, match="path"):
        TraceDifference("", 1, 2)
    with pytest.raises(TypeError, match="StepRecord"):
        compare_step_records(record, object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="traces"):
        tuple(iter_trace_divergences((record,), (object(),)))  # type: ignore[arg-type]


def test_json_lines_round_trip_is_deterministic_and_comparable() -> None:
    records = _history([0x7005, 0x5380, NOP], steps=3, track_accesses=True)
    first, second = StringIO(), StringIO()

    assert write_trace(iter(records), first) == 3
    assert write_trace(iter(records), second) == 3
    assert first.getvalue() == second.getvalue()
    assert f'"version":{TRACE_SCHEMA_VERSION}' in first.getvalue()
    first.seek(0)
    restored = tuple(read_trace(first))
    assert restored == records
    assert first_trace_divergence(restored, records) is None


def test_record_dictionary_round_trip_preserves_every_boundary_form() -> None:
    instruction = _history([0x7005, NOP], track_accesses=True)[0]
    idle = replace(instruction, kind=BoundaryKind.STOPPED_IDLE, instruction=None, cycles=4)
    untracked = replace(instruction, accesses=None)
    for record in (instruction, idle, untracked):
        assert step_record_from_dict(step_record_to_dict(record)) == record
    assert "accesses" not in step_record_to_dict(untracked)
    assert step_record_to_dict(instruction)["accesses"] == [["r", 0x1004, 0, 2]]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.pop("version"), "keys"),
        (lambda value: value.__setitem__("version", 999), "version"),
        (lambda value: value.__setitem__("unknown", 1), "keys"),
        (lambda value: value["before"].pop("pc"), "exactly the keys"),
        (lambda value: value.__setitem__("sequence", "1"), "integer"),
        (lambda value: value.__setitem__("kind", "sleep"), "sleep"),
        (lambda value: value["instruction"].__setitem__("data", "not hex"), "hexadecimal"),
        (lambda value: value["instruction"].__setitem__("data", "33c0"), "exactly one"),
        (lambda value: value["instruction"].pop("operands"), "come together"),
        (lambda value: value["instruction"].__setitem__("mnemonic", "nop"), "does not match"),
        (lambda value: value["instruction"].__setitem__("extra", 1), "instruction fields"),
        (lambda value: value.__setitem__("accesses", [["x", 0, 0, 1]]), "accesses"),
        (lambda value: value.__setitem__("accesses", "r"), "accesses"),
    ],
)
def test_persisted_schema_rejects_missing_unknown_and_invalid_fields(mutate, message) -> None:
    value = step_record_to_dict(_history([0x7005, NOP], track_accesses=True)[0])
    mutate(value)
    with pytest.raises(ValueError, match=message):
        step_record_from_dict(value)


def test_read_trace_reports_the_malformed_line_number_lazily() -> None:
    record = _history([NOP, NOP])[0]
    stream = StringIO()
    write_trace((record,), stream)
    stream.write("\n{bad json}\n")
    stream.seek(0)
    records = read_trace(stream)

    assert next(records) == record
    with pytest.raises(ValueError, match="line 3"):
        next(records)


# -- records written by another producer --------------------------------------

_STATE_FIELDS = [field.name for field in fields(CPUState)]


def _external_record(address: int, data: bytes, **overrides: object) -> dict[str, object]:
    """A record as a port in another language writes it: bytes, no disassembly text."""
    state = dict.fromkeys(_STATE_FIELDS, 0)
    state.update(d=[0] * 8, a=[0] * 7, sr=0x2700, pc=address, ir=int.from_bytes(data[:2], "big"))
    for name in ("nmi_edge", "trace_pending", "stopped", "halted"):
        state[name] = False
    after = {**state, "pc": address + len(data)}
    record: dict[str, object] = {
        "version": TRACE_SCHEMA_VERSION,
        "sequence": 0,
        "kind": "instruction",
        "cycles": 4,
        "instruction": {"address": address, "data": data.hex()},
        "before": state,
        "after": after,
    }
    record.update(overrides)
    return record


def test_external_record_without_text_is_decoded_from_its_bytes() -> None:
    record = step_record_from_dict(_external_record(0x1000, bytes((0x70, 0x05))))
    assert record.instruction is not None
    assert (record.instruction.mnemonic, record.instruction.operands) == ("moveq", ("#$5", "D0"))
    assert record.instruction.address == 0x1000


def test_external_record_compares_equal_to_a_native_record_of_the_same_bytes() -> None:
    external = step_record_from_dict(_external_record(0x1000, bytes((0x4E, 0x71))))
    native = step_record_from_dict(step_record_to_dict(external))
    assert step_record_to_dict(native)["instruction"]["mnemonic"] == "nop"
    assert compare_step_records(native, external) == ()


def test_accesses_are_compared_only_when_both_records_carry_them() -> None:
    tracked = _history([0x7005, NOP], track_accesses=True)[0]
    plain = _history([0x7005, NOP])[0]
    assert compare_step_records(tracked, plain) == ()
    altered = step_record_to_dict(tracked)
    altered["accesses"][0][2] = 0x4E70
    differences = compare_step_records(tracked, step_record_from_dict(altered))
    assert [item.path for item in differences] == ["accesses"]
