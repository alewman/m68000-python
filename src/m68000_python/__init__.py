"""A readable, pure-Python Motorola MC68000 instruction core."""

from m68000_python._core import AUTOVECTOR, SPURIOUS, BusError
from m68000_python.console import CommandDebugger, CommandError, CommandResult
from m68000_python.cpu import M68000CPU
from m68000_python.debug import (
    Access,
    BoundaryKind,
    DebugSession,
    DebugTarget,
    RunResult,
    StepRecord,
    StopReason,
    next_boundary,
)
from m68000_python.disasm import (
    Instruction,
    WordReader,
    disassemble,
    disassemble_bytes,
    disassemble_range,
)
from m68000_python.state import CPUState
from m68000_python.trace import (
    TRACE_SCHEMA_VERSION,
    TraceDifference,
    TraceDivergence,
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

__all__ = [
    "AUTOVECTOR",
    "M68000CPU",
    "SPURIOUS",
    "TRACE_SCHEMA_VERSION",
    "Access",
    "BoundaryKind",
    "BusError",
    "CPUState",
    "CommandDebugger",
    "CommandError",
    "CommandResult",
    "DebugSession",
    "DebugTarget",
    "Instruction",
    "RunResult",
    "StepRecord",
    "StopReason",
    "TraceDifference",
    "TraceDivergence",
    "WordReader",
    "compare_step_records",
    "disassemble",
    "disassemble_bytes",
    "disassemble_range",
    "first_session_divergence",
    "first_trace_divergence",
    "iter_session_steps",
    "iter_trace_divergences",
    "next_boundary",
    "read_trace",
    "step_record_from_dict",
    "step_record_to_dict",
    "write_trace",
]
