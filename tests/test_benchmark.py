"""The benchmark harness runs every workload and writes machine-readable results."""

import json

from benchmarks.m68000_core_benchmark import WORKLOADS, _write_json, run_benchmark


def test_all_workloads_execute_fixed_instruction_counts() -> None:
    for workload in WORKLOADS:
        result = run_benchmark(workload, instruction_count=64, repeats=2, warmup_instructions=8)
        assert result.name == workload.name
        assert result.instruction_count == 64
        assert len(result.samples) == 2
        assert all(sample.clocks > 0 for sample in result.samples)
        assert result.instructions_per_second > 0
        assert result.clocks_per_second > 0


def test_json_output_names_the_interpreter_and_platform(tmp_path) -> None:
    result = run_benchmark(WORKLOADS[0], instruction_count=8, repeats=1, warmup_instructions=0)
    output = tmp_path / "benchmark.json"
    _write_json(output, [result])
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["python_implementation"] and payload["python_version"] and payload["platform"]
    assert payload["results"][0]["instruction_count"] == 8
    assert len(payload["results"][0]["samples"]) == 1
