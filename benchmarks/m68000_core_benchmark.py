"""Reproducible microbenchmarks for the pure-Python 68000 instruction core.

    python benchmarks/m68000_core_benchmark.py [--workload base] [--json out.json]

Each workload is a short program in the shape of real 68000 code, assembled
below as words and run through ``step()`` for a fixed instruction count;
the rate is instructions per second over the median of the timed samples.
The host is a flat 16 MB RAM with the reset vectors and one exception
vector set, and nothing else on the bus.  Absolute rates depend on the
machine and its load; ``compare_revisions.py`` is the load-independent A/B.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m68000_python import M68000CPU

START = 0x1000
HANDLER = 0x4000  # every exception vector points here: an RTE


class BenchmarkHost:
    """Flat 16 MB RAM, vectors set, the CPU reset and at ``START``."""

    def __init__(self, program: tuple[int, ...]) -> None:
        memory = self.memory = bytearray(1 << 24)

        def read_word(address: int) -> int:
            return (memory[address] << 8) | memory[address + 1]

        def write_word(address: int, value: int) -> None:
            memory[address] = value >> 8
            memory[address + 1] = value & 0xFF

        for vector in range(256):
            write_word(vector * 4, HANDLER >> 16)
            write_word(vector * 4 + 2, HANDLER & 0xFFFF)
        write_word(0, 0)
        write_word(2, 0x8000)  # SSP
        write_word(4, 0)
        write_word(6, START)  # PC
        write_word(HANDLER, 0x4E73)  # rte
        for index, word in enumerate(program):
            write_word(START + 2 * index, word)
        for offset in range(0, 0x400, 2):  # data the memory workload reads
            write_word(0x2000 + offset, (offset * 17 + 3) & 0xFFFF)
        self.cpu = M68000CPU(memory.__getitem__, read_word, memory.__setitem__, write_word)
        self.cpu.reset()


@dataclass(frozen=True)
class Workload:
    """Named deterministic program executed through :meth:`M68000CPU.step`."""

    name: str
    description: str
    program: tuple[int, ...]


@dataclass(frozen=True)
class Sample:
    """One timed benchmark sample."""

    elapsed_seconds: float
    clocks: int


@dataclass(frozen=True)
class BenchmarkResult:
    """All samples and derived rates for one workload."""

    name: str
    description: str
    instruction_count: int
    samples: tuple[Sample, ...]
    median_seconds: float
    instructions_per_second: float
    clocks_per_second: float


BASE = (
    0x41F9, 0x0000, 0x2000,  # lea     $2000.l, A0
    0x43F9, 0x0000, 0x3000,  # lea     $3000.l, A1
    0x303C, 0x00FF,          # move.w  #$ff, D0
    0x3218,                  # move.w  (A0)+, D1          loop:
    0xD241,                  # add.w   D1, D1
    0x32C1,                  # move.w  D1, (A1)+
    0x0C41, 0x1234,          # cmpi.w  #$1234, D1
    0x6702,                  # beq.s   +2
    0x5282,                  # addq.l  #1, D2
    0x51C8, 0xFFF0,          # dbf     D0, loop
    0x60E2,                  # bra.s   start
)  # fmt: skip
MEMORY = (
    0x41F9, 0x0000, 0x2000,  # lea     $2000.l, A0        start:
    0x43F9, 0x0000, 0x3000,  # lea     $3000.l, A1
    0x22D8,                  # move.l  (A0)+, (A1)+
    0x22D8,                  # move.l  (A0)+, (A1)+
    0x2368, 0x0004, 0x0008,  # move.l  ($4,A0), ($8,A1)
    0x48E7, 0xFF00,          # movem.l D0-D7, -(A7)
    0x4CDF, 0x00FF,          # movem.l (A7)+, D0-D7
    0x4868, 0x0010,          # pea     ($10,A0)
    0x245F,                  # movea.l (A7)+, A2
    0x60E0,                  # bra.s   start
)  # fmt: skip
ARITHMETIC = (
    0x203C, 0x1234, 0x5678,  # move.l  #$12345678, D0     start:
    0xC0FC, 0x1234,          # mulu.w  #$1234, D0
    0x80FC, 0x0056,          # divu.w  #$56, D0
    0xE781,                  # asl.l   #3, D1
    0xEA5A,                  # ror.w   #5, D2
    0xC903,                  # abcd    D3, D4
    0x4842,                  # swap    D2
    0x60EA,                  # bra.s   start
)  # fmt: skip
EXCEPTIONS = (
    0x4E40,                  # trap    #0                 start:
    0x4E71,                  # nop
    0x60FA,                  # bra.s   start
)  # fmt: skip

WORKLOADS: Final[tuple[Workload, ...]] = (
    Workload("base", "a copy loop: word moves through (An)+, add, compare, branch, DBF", BASE),
    Workload("memory", "long moves, MOVEM to and from the stack, LEA and PEA", MEMORY),
    Workload("arithmetic", "multiply, divide, shifts and rotates, BCD", ARITHMETIC),
    Workload("exceptions", "TRAP #0 and RTE: exception entry and return", EXCEPTIONS),
)


def _execute(host: BenchmarkHost, instruction_count: int) -> int:
    step = host.cpu.step
    clocks = 0
    for _ in range(instruction_count):
        clocks += step()
    return clocks


def run_benchmark(
    workload: Workload,
    *,
    instruction_count: int,
    repeats: int,
    warmup_instructions: int,
) -> BenchmarkResult:
    """Run one workload with all host and program setup outside the timed loops."""
    if instruction_count < 1 or repeats < 1 or warmup_instructions < 0:
        raise ValueError("instruction_count/repeats must be positive and warmup non-negative")
    if warmup_instructions:
        _execute(BenchmarkHost(workload.program), warmup_instructions)
    samples: list[Sample] = []
    for _ in range(repeats):
        host = BenchmarkHost(workload.program)
        started = time.perf_counter()
        clocks = _execute(host, instruction_count)
        samples.append(Sample(time.perf_counter() - started, clocks))
    median_seconds = statistics.median(sample.elapsed_seconds for sample in samples)
    median_clocks = statistics.median(sample.clocks for sample in samples)
    return BenchmarkResult(
        name=workload.name,
        description=workload.description,
        instruction_count=instruction_count,
        samples=tuple(samples),
        median_seconds=median_seconds,
        instructions_per_second=instruction_count / median_seconds,
        clocks_per_second=median_clocks / median_seconds,
    )


def _metadata() -> dict[str, str]:
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def _print_results(results: list[BenchmarkResult]) -> None:
    metadata = _metadata()
    print(f"Python: {metadata['python_implementation']} {metadata['python_version']}")
    print(f"Platform: {metadata['platform']}")
    for result in results:
        print(f"\n{result.name}: {result.description}")
        print(f"  instructions: {result.instruction_count:,} per sample")
        print(f"  samples (s): [{', '.join(f'{s.elapsed_seconds:.6f}' for s in result.samples)}]")
        print(f"  median (s): {result.median_seconds:.6f}")
        print(f"  instructions/s: {result.instructions_per_second:,.0f}")
        megahertz = result.clocks_per_second / 1e6
        print(f"  clocks/s: {result.clocks_per_second:,.0f} ({megahertz:.2f} emulated MHz)")


def _write_json(path: Path, results: list[BenchmarkResult]) -> None:
    payload = {**_metadata(), "results": [asdict(result) for result in results]}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--instructions",
        type=int,
        default=2_000_000 if sys.implementation.name == "pypy" else 200_000,
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup-instructions", type=int, default=20_000)
    parser.add_argument(
        "--workload", choices=("all", *(workload.name for workload in WORKLOADS)), default="all"
    )
    parser.add_argument("--json", type=Path, help="also write machine-readable results")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    selected = [w for w in WORKLOADS if args.workload == "all" or w.name == args.workload]
    try:
        results = [
            run_benchmark(
                workload,
                instruction_count=args.instructions,
                repeats=args.repeats,
                warmup_instructions=args.warmup_instructions,
            )
            for workload in selected
        ]
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print_results(results)
    if args.json is not None:
        _write_json(args.json, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
