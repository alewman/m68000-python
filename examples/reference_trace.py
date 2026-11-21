"""Write the committed reference trace: examples/reference_trace.jsonl.

    python examples/reference_trace.py

A short program (a counting loop, a store, STOP) run through a DebugSession
with bus-access tracking, written in the trace schema (docs/trace-schema.md).
A core in another language that runs the same program on the same flat host
can diff its own trace against this one with ``first_trace_divergence``;
tests/test_trace_comparison.py checks that the file is what this package
writes today, so it never goes stale.
"""

from __future__ import annotations

import io
from pathlib import Path

from m68000_python import M68000CPU, DebugSession, StepRecord, write_trace

PROGRAM = bytes.fromhex(
    "7005"  # $1000 moveq #5, D0
    "5380"  # $1002 subq.l #1, D0
    "66FC"  # $1004 bne $1002
    "33C000003000"  # $1006 move.w D0, $3000.l
    "4E722700"  # $100C stop #$2700
)
STEPS = 15  # thirteen instructions (the loop runs five times), then two idle boundaries inside STOP
OUTPUT = Path(__file__).with_name("reference_trace.jsonl")


def records() -> list[StepRecord]:
    """The reference program's boundaries, from reset, on a flat 64 KiB host."""
    memory = bytearray(1 << 16)

    def read_word(address: int) -> int:
        return (memory[address] << 8) | memory[address + 1]

    def write_word(address: int, value: int) -> None:
        memory[address] = value >> 8
        memory[address + 1] = value & 0xFF

    memory[0:8] = (0x8000).to_bytes(4, "big") + (0x1000).to_bytes(4, "big")
    memory[0x1000 : 0x1000 + len(PROGRAM)] = PROGRAM
    cpu = M68000CPU(memory.__getitem__, read_word, memory.__setitem__, write_word)
    cpu.reset()
    session = DebugSession(cpu, peek_word=read_word, history_limit=STEPS, track_accesses=True)
    session.run(max_steps=STEPS, stop_on_stop=False)
    return list(session.history)


def text() -> str:
    stream = io.StringIO()
    write_trace(records(), stream)
    return stream.getvalue()


if __name__ == "__main__":
    OUTPUT.write_text(text(), encoding="utf-8")
    print(f"{STEPS} records written to {OUTPUT}")
