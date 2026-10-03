"""The conformance kit: manifests, the one host, stop rules, the CLI, the committed examples."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from m68000_python import BoundaryKind, read_trace, write_trace
from m68000_python.conformance import (
    ConformanceHost,
    load_manifest,
    main,
    manifest_from_dict,
    manifest_to_dict,
    trace_manifest,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "conformance"
NOP = "4e71"
STOP = "4e722700"  # stop #$2700


def _manifest(program: str, **fields) -> dict:
    """A flat manifest running ``program`` at $1000 in supervisor mode."""
    document = {
        "version": 1,
        "name": "test",
        "memory": [{"address": 0x1000, "data": program}],
        "initial": {"pc": 0x1000, "ssp": 0x8000},
        "stop": {"max_steps": 50},
    }
    document.update(fields)
    return document


def _run(document: dict, **options):
    result: list = []
    records = list(trace_manifest(manifest_from_dict(document, **options), result=result))
    return records, result[0]


# -- the committed examples ------------------------------------------------------


def _example_paths() -> list[Path]:
    return sorted(EXAMPLES.glob("*.json")) + sorted((EXAMPLES / "interrupts").glob("*.json"))


def test_the_examples_are_what_build_py_writes_today() -> None:
    from examples.conformance.build import manifest_text, manifests

    built = manifests()
    assert sorted(built) == sorted(_example_paths())
    for path, manifest in built.items():
        assert path.read_text(encoding="utf-8") == manifest_text(manifest), path.name


@pytest.mark.parametrize("path", _example_paths(), ids=lambda path: path.stem)
def test_each_committed_trace_is_what_the_reference_writes_today(path: Path) -> None:
    stream = io.StringIO()
    write_trace(trace_manifest(load_manifest(path)), stream)
    assert stream.getvalue() == path.with_suffix(".jsonl").read_text(encoding="utf-8")


# -- manifests -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"version": 2}, "unsupported manifest version"),
        ({"surprise": 1}, "unknown=\\['surprise'\\]"),
        ({"host": "board"}, "host must be one of"),
        ({"reset": True}, "reset and initial exclude each other"),
        ({"initial": {"pc": 0x1000, "ir": 0x4E71}}, "both ir and irc"),
        ({"initial": {"pc": 0x1001}}, "pc must be even"),
        ({"acknowledge": {"8": 64}}, "levels '1'..'7'"),
        ({"acknowledge": {"4": 256}}, "answers are 0-255"),
        ({"acknowledge": {"4": "never"}}, "answers are 0-255"),
        ({"bus_error": [{"address": 0xFFFFFF, "length": 2}]}, "does not fit"),
        ({"bus_error": [{"address": 0}]}, "missing=\\['length'\\]"),
        ({"tas_write": "maybe"}, "tas_write must be one of"),
        ({"replay": {"devices": [], "reads": {"data": ""}}}, "only a replay host"),
        ({"host": "replay"}, "a replay host needs replay"),
        ({"events": [{"at_step": 2, "kind": "reset"}, {"at_step": 1, "kind": "reset"}]},
         "ordered by at_step"),
        ({"events": [{"at_step": 1, "kind": "ipl"}]}, "level must be an integer"),
        ({"events": [{"at_step": 1, "kind": "reset", "level": 1}]}, "no level"),
        ({"memory": [{"address": 0xFFFFFF, "data": "0000"}]}, "does not fit"),
        ({"memory": [{"address": 0, "data": "00", "file": "x"}]}, "exactly one of"),
        ({"stop": {}}, "missing=\\['max_steps'\\]"),
    ],
)  # fmt: skip
def test_malformed_manifests_are_refused(change: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        manifest_from_dict(_manifest(NOP, **change))


def test_the_queue_is_filled_from_memory_when_initial_does_not_give_it() -> None:
    manifest = manifest_from_dict(_manifest("7005" + NOP))
    assert (manifest.initial.ir, manifest.initial.irc) == (0x7005, 0x4E71)
    given = manifest_from_dict(_manifest("7005", initial={"pc": 0x1000, "ir": 1, "irc": 2}))
    assert (given.initial.ir, given.initial.irc) == (1, 2)


def test_a_manifest_survives_its_dictionary_form() -> None:
    document = _manifest(
        NOP + STOP,
        acknowledge={"4": "spurious", "5": 64},
        bus_error=[{"address": 0xF00000, "length": 4}],
        tas_write="drop",
        events=[{"at_step": 1, "kind": "ipl", "level": 5}, {"at_step": 2, "kind": "reset"}],
    )
    manifest = manifest_from_dict(document)
    assert manifest_from_dict(manifest_to_dict(manifest)) == manifest


def test_file_segments_resolve_beside_the_manifest(tmp_path: Path) -> None:
    (tmp_path / "program.bin").write_bytes(bytes.fromhex("ffff7005" + NOP))
    document = _manifest("", memory=[{"address": 0x1000, "file": "program.bin", "offset": 2}])
    (tmp_path / "m.json").write_text(json.dumps(document))
    manifest = load_manifest(tmp_path / "m.json")
    assert manifest.memory[0].data == bytes.fromhex("7005" + NOP)


# -- the host ----------------------------------------------------------------------


def test_reset_reads_the_vectors_and_spends_its_clocks_outside_the_trace() -> None:
    document = _manifest(NOP + STOP, reset=True)
    del document["initial"]
    document["memory"].append({"address": 0, "data": "0000800000001000"})
    records, run = _run(document)
    assert records[0].before.pc == 0x1000 and records[0].before.clock == 40
    assert run.clocks == 4 + 4  # the NOP and the STOP; reset() is not a record


def test_a_bus_error_range_faults_reads_and_writes() -> None:
    # move.w $f00000.l, D0; the bus error vector points at a STOP.
    document = _manifest(
        "30390" + "0f00000",
        bus_error=[{"address": 0xF00000, "length": 2}],
        memory=[{"address": 0x1000, "data": "303900f00000"},
                {"address": 8, "data": "00002000"},
                {"address": 0x2000, "data": STOP}],
    )  # fmt: skip
    records, _ = _run(document)
    fault = records[0]
    assert fault.after.pc == 0x2000
    # The faulting read is not recorded (tracking appends after the read
    # returns); the frame's seven writes are.
    assert all(access[1] != 0xF00000 for access in fault.accesses)
    assert sum(access[0] == "w" for access in fault.accesses) == 7


def test_replay_windows_take_reads_from_the_stream_and_drop_writes() -> None:
    # move.w $100000.l, D0; move.b $100001.l, D1; move.w D0, $100000.l;
    # move.w $100000.l, D2 (stream exhausted)
    program = "30390010000012390010000133c000100000343900100000" + STOP
    document = _manifest(
        program,
        host="replay",
        replay={"devices": [{"address": 0x100000, "length": 0x100}],
                "reads": {"data": "1234abcd"}},
        memory=[{"address": 0x1000, "data": program}, {"address": 0x100000, "data": "5555"}],
    )  # fmt: skip
    records, _ = _run(document)
    after = records[3].after
    assert after.d[0] == 0x1234 and after.d[1] == 0xCD and after.d[2] == 0xFFFF
    host = ConformanceHost(manifest_from_dict(document))
    assert host.peek_word(0x100000) == 0x5555 and host.reads_consumed == 0


def test_tas_write_drop_discards_the_write_and_records_nothing() -> None:
    program = "4af83000" + STOP  # tas $3000.w
    for mode, value, writes in (("write", 0x85, 1), ("drop", 0x05, 0)):
        document = _manifest(
            program,
            tas_write=mode,
            memory=[{"address": 0x1000, "data": program}, {"address": 0x3000, "data": "05"}],
        )
        manifest = manifest_from_dict(document)
        host = ConformanceHost(manifest)
        host.cpu.step()
        assert host.memory[0x3000] == value
        records, _ = _run(document)
        assert sum(access[0] == "w" for access in records[0].accesses) == writes


def test_the_acknowledge_map_answers_listed_levels_and_autovectors_the_rest() -> None:
    vectors = bytearray(0x400)
    vectors[64 * 4 : 64 * 4 + 4] = (0x2000).to_bytes(4, "big")
    vectors[29 * 4 : 29 * 4 + 4] = (0x2100).to_bytes(4, "big")  # level 5 autovector
    for level, target in ((4, 0x2000), (5, 0x2100)):
        document = _manifest(
            NOP * 4,
            acknowledge={"4": 64},
            initial={"pc": 0x1000, "ssp": 0x8000, "sr": 0x2000},
            memory=[{"address": 0, "data": vectors.hex()},
                    {"address": 0x1000, "data": NOP * 4}],
            events=[{"at_step": 1, "kind": "ipl", "level": level}],
            stop={"max_steps": 2},
        )  # fmt: skip
        records, _ = _run(document)
        assert records[1].kind is BoundaryKind.INTERRUPT and records[1].after.pc == target


# -- stop rules and events -------------------------------------------------------


def test_stop_rules() -> None:
    _, run = _run(_manifest(NOP * 3 + STOP))
    assert (run.steps, run.reason) == (4, "idle")
    _, run = _run(_manifest(NOP * 3 + STOP, stop={"max_steps": 10, "on_idle": False}))
    assert (run.steps, run.reason) == (10, "max_steps")
    _, run = _run(_manifest(NOP * 3 + STOP, stop={"max_steps": 10, "at_pc": [0x1004]}))
    assert (run.steps, run.reason) == (2, "at_pc")


def test_an_idle_run_continues_while_an_event_remains() -> None:
    records, _ = _run(_manifest(STOP, events=[{"at_step": 5, "kind": "ipl", "level": 7}]))
    assert [record.kind for record in records[1:5]] == [BoundaryKind.STOPPED_IDLE] * 4
    assert records[5].kind is BoundaryKind.INTERRUPT


def test_a_reset_event_restarts_without_a_record() -> None:
    document = _manifest(NOP * 4, events=[{"at_step": 2, "kind": "reset"}],
                         stop={"max_steps": 3})  # fmt: skip
    document["memory"].append({"address": 0, "data": "0000800000001000"})
    records, _ = _run(document)
    assert records[2].before.pc == 0x1000 and records[2].before.clock == 8 + 40


# -- the command line -------------------------------------------------------------


def test_cli_trace_then_diff(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(_manifest("7005" + NOP + STOP)))
    trace = tmp_path / "t.jsonl"
    out = io.StringIO()
    assert main(["trace", str(manifest), "--out", str(trace)], stdout=out) == 0
    assert "3 records, 12 clocks, stopped on idle" in out.getvalue()
    out = io.StringIO()
    assert main(["diff", str(manifest), str(trace)], stdout=out) == 0
    assert out.getvalue() == "test: traces are identical\n"


def test_cli_reports_the_first_divergence(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(_manifest("7005" + NOP + STOP)))
    other = tmp_path / "other.json"
    other.write_text(json.dumps(_manifest("7006" + NOP + STOP)))
    trace = tmp_path / "t.jsonl"
    with trace.open("w") as handle:
        write_trace(trace_manifest(load_manifest(other)), handle)
    out = io.StringIO()
    assert main(["diff", str(manifest), str(trace)], stdout=out) == 1
    text = out.getvalue()
    assert "divergence at position 0, 001000: moveq #$5, D0" in text
    assert "instruction.data: reference='7005' external='7006'" in text


def test_cli_bad_input_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert main(["trace", str(bad)], stdout=io.StringIO()) == 2
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(_manifest(STOP)))
    trace = tmp_path / "t.jsonl"
    trace.write_text('{"version": 9}\n')
    assert main(["diff", str(manifest), str(trace)], stdout=io.StringIO()) == 2


def test_read_trace_reads_what_the_kit_writes() -> None:
    stream = io.StringIO()
    write_trace(trace_manifest(manifest_from_dict(_manifest(NOP + STOP))), stream)
    stream.seek(0)
    record = next(read_trace(stream))
    assert record.accesses == (("r", 0x1004, 0x2700, 2),)
