"""Conformance kit: run a manifest on the reference core, or diff a foreign trace against it.

A **manifest** is a small JSON document that fully determines a run: what is
in memory, the initial processor state, how the host answers the interrupt
acknowledge cycle, where the bus asserts BERR, which reads come from a
recorded device stream, when the interrupt level changes, and when to stop.
Two cores given the same manifest see the same machine, so any difference
between their traces is a difference between the CPUs.  The trace format
itself is docs/trace-schema.md; this module is the part that makes traces
comparable (docs/conformance.md).

Two entry points, also exposed as ``python -m m68000_python.conformance``:

* :func:`trace_manifest` runs the manifest on :class:`M68000CPU` and yields
  one :class:`StepRecord` per boundary, bus accesses included: the
  reference trace.
* :func:`diff_manifest` runs the same manifest in lockstep against an
  external trace and returns the first :class:`TraceDivergence`, or ``None``.

The module depends only on the standard library and the rest of this package.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import TextIO

from m68000_python._core import AUTOVECTOR, SPURIOUS, BusError
from m68000_python.cpu import M68000CPU
from m68000_python.debug import BoundaryKind, DebugSession, StepRecord, next_boundary
from m68000_python.state import CPUState
from m68000_python.trace import TraceDivergence, first_trace_divergence, read_trace, write_trace

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "MEMORY_SIZE",
    "AddressRange",
    "ConformanceHost",
    "Event",
    "Manifest",
    "MemorySegment",
    "Replay",
    "StopRule",
    "TraceRun",
    "diff_manifest",
    "load_manifest",
    "main",
    "manifest_from_dict",
    "manifest_to_dict",
    "trace_manifest",
]

MANIFEST_SCHEMA_VERSION = 1

#: The flat host's memory: the whole 24-bit address space the 68000 drives (UM 3.1).
MEMORY_SIZE = 0x1000000

#: Host profiles.  ``flat``: 16 MiB of RAM.  ``replay``: the same, plus device
#: windows whose reads come from a recorded stream, see :class:`ConformanceHost`.
HOST_PROFILES = ("flat", "replay")
EVENT_KINDS = ("ipl", "reset")
TAS_WRITES = ("write", "drop")
#: The acknowledge answers a manifest may name, and the core's value for each.
ACKNOWLEDGE_NAMES = {"autovector": AUTOVECTOR, "spurious": SPURIOUS}


@dataclass(frozen=True, slots=True)
class MemorySegment:
    """Bytes to place at ``address`` before the run starts."""

    address: int
    data: bytes

    def __post_init__(self) -> None:
        if type(self.address) is not int or not 0 <= self.address < MEMORY_SIZE:
            raise ValueError("segment address must be an integer in range 0..0xFFFFFF")
        if type(self.data) is not bytes or not self.data:
            raise ValueError("segment data must be non-empty bytes")
        if self.address + len(self.data) > MEMORY_SIZE:
            raise ValueError("segment does not fit below 0x1000000")


@dataclass(frozen=True, slots=True)
class AddressRange:
    """``length`` bytes from ``address``: a BERR range or a device window."""

    address: int
    length: int

    def __post_init__(self) -> None:
        if type(self.address) is not int or not 0 <= self.address < MEMORY_SIZE:
            raise ValueError("range address must be an integer in range 0..0xFFFFFF")
        if type(self.length) is not int or self.length <= 0:
            raise ValueError("range length must be a positive integer")
        if self.address + self.length > MEMORY_SIZE:
            raise ValueError("range does not fit below 0x1000000")

    def __contains__(self, address: object) -> bool:
        return type(address) is int and self.address <= address < self.address + self.length


@dataclass(frozen=True, slots=True)
class Replay:
    """The ``replay`` host's device windows and the recorded values their reads return.

    ``reads`` is a sequence of big-endian 16-bit values, consumed one per
    read inside a window, in the order the CPU makes the reads.
    """

    devices: tuple[AddressRange, ...]
    reads: bytes

    def __post_init__(self) -> None:
        if type(self.devices) is not tuple or not all(
            type(window) is AddressRange for window in self.devices
        ):
            raise ValueError("replay devices must be a tuple of AddressRange values")
        if type(self.reads) is not bytes or len(self.reads) % 2:
            raise ValueError("replay reads must be bytes holding whole 16-bit values")


@dataclass(frozen=True, slots=True)
class Event:
    """A host action applied immediately before boundary ``at_step``.

    Steps count every record (instruction, trace, interrupt, idle) from 0.
    ``ipl`` sets the interrupt level through ``set_ipl(level)``, so the
    boundary at ``at_step`` is the first that can observe it; ``reset`` calls
    ``reset()``, which produces no record (its clocks land in ``clock``).
    """

    at_step: int
    kind: str
    level: int | None = None

    def __post_init__(self) -> None:
        if type(self.at_step) is not int or self.at_step < 0:
            raise ValueError("event at_step must be a non-negative integer")
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"event kind must be one of {EVENT_KINDS}, got {self.kind!r}")
        if self.kind == "ipl":
            if type(self.level) is not int or not 0 <= self.level <= 7:
                raise ValueError("an ipl event's level must be an integer in range 0..7")
        elif self.level is not None:
            raise ValueError("a reset event has no level")


@dataclass(frozen=True, slots=True)
class StopRule:
    """When the run ends.  ``max_steps`` is mandatory so every run is finite.

    The run stops *before* a boundary when the state's ``pc`` is one of
    ``at_pc``; when the next boundary would be an idle one (halted, or inside
    STOP with nothing able to end it) and no event remains (``on_idle``); or
    when the step budget is spent.  A stopped run's trace ends; the boundary
    that would have followed is not recorded.
    """

    max_steps: int
    on_idle: bool = True
    at_pc: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if type(self.max_steps) is not int or self.max_steps <= 0:
            raise ValueError("stop.max_steps must be a positive integer")
        if type(self.on_idle) is not bool:
            raise ValueError("stop.on_idle must be a bool")
        if type(self.at_pc) is not tuple or not all(
            type(pc) is int and 0 <= pc <= 0xFFFFFFFF for pc in self.at_pc
        ):
            raise ValueError("stop.at_pc must be a tuple of 32-bit addresses")


@dataclass(frozen=True, slots=True)
class Manifest:
    """A complete, deterministic description of one conformance run.

    ``initial`` is the state restored before the first boundary, its queue
    already filled (see :func:`manifest_from_dict`); with ``reset`` the host
    calls ``reset()`` instead and ``initial`` is unused.  ``acknowledge`` is
    ``(level, answer)`` pairs, the answer a vector number 0-255 or the core's
    ``AUTOVECTOR`` or ``SPURIOUS``; unlisted levels autovector.
    """

    name: str
    memory: tuple[MemorySegment, ...]
    initial: CPUState
    stop: StopRule
    host: str = "flat"
    reset: bool = False
    acknowledge: tuple[tuple[int, int], ...] = ()
    bus_error: tuple[AddressRange, ...] = ()
    tas_write: str = "write"
    replay: Replay | None = None
    events: tuple[Event, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name:
            raise ValueError("manifest name must be a non-empty string")
        if type(self.memory) is not tuple or not all(
            type(segment) is MemorySegment for segment in self.memory
        ):
            raise ValueError("manifest memory must be a tuple of MemorySegment values")
        if type(self.initial) is not CPUState:
            raise ValueError("manifest initial must be a CPUState")
        if type(self.stop) is not StopRule:
            raise ValueError("manifest stop must be a StopRule")
        if self.host not in HOST_PROFILES:
            raise ValueError(f"manifest host must be one of {HOST_PROFILES}, got {self.host!r}")
        if type(self.reset) is not bool:
            raise ValueError("manifest reset must be a bool")
        if type(self.acknowledge) is not tuple or not all(
            type(pair) is tuple
            and len(pair) == 2
            and type(pair[0]) is int
            and 1 <= pair[0] <= 7
            and type(pair[1]) is int
            and (0 <= pair[1] <= 0xFF or pair[1] in (AUTOVECTOR, SPURIOUS))
            for pair in self.acknowledge
        ):
            raise ValueError("manifest acknowledge must be (level 1-7, answer) pairs")
        levels = [level for level, _ in self.acknowledge]
        if levels != sorted(set(levels)):
            raise ValueError("manifest acknowledge levels must be distinct and ordered")
        if type(self.bus_error) is not tuple or not all(
            type(item) is AddressRange for item in self.bus_error
        ):
            raise ValueError("manifest bus_error must be a tuple of AddressRange values")
        if self.tas_write not in TAS_WRITES:
            raise ValueError(f"manifest tas_write must be one of {TAS_WRITES}")
        if (self.host == "replay") != (self.replay is not None):
            raise ValueError("a replay host needs replay, and only a replay host has it")
        if self.replay is not None and type(self.replay) is not Replay:
            raise ValueError("manifest replay must be a Replay")
        if type(self.events) is not tuple or not all(type(event) is Event for event in self.events):
            raise ValueError("manifest events must be a tuple of Event values")
        steps = [event.at_step for event in self.events]
        if steps != sorted(steps):
            raise ValueError("manifest events must be ordered by at_step")


class ConformanceHost:
    """The one host every conformance run uses, so hosts cannot differ between cores.

    16 MiB of RAM over the 24-bit address space, zero but for the manifest's
    segments; reads return its bytes (words big-endian) and writes store
    them.  On every access, in this order:

    * an address inside a ``bus_error`` range raises :class:`BusError` (a word
      access is checked at its address only, which is even);
    * with the ``replay`` profile, a read inside a device window takes the
      next 16-bit value of the reads stream (a byte read its low 8 bits), or
      0xFFFF (0xFF) once the stream is exhausted, and a write inside one is
      discarded;
    * otherwise memory.

    The interrupt acknowledge answers with the manifest's ``acknowledge``
    map, autovectoring an unlisted level; ``tas_write: "drop"`` discards
    TAS's write cycle (after the BERR check), as the Genesis bus does.
    A port must implement exactly this to be comparable.
    """

    def __init__(self, manifest: Manifest) -> None:
        self.memory = memory = bytearray(MEMORY_SIZE)
        for segment in manifest.memory:
            memory[segment.address : segment.address + len(segment.data)] = segment.data
        self._reads = manifest.replay.reads if manifest.replay is not None else b""
        self.reads_consumed = 0
        read_byte, read_word, write_byte, write_word = self._bus(manifest)
        answers = dict(manifest.acknowledge)
        acknowledge: Callable[[int], int] | None = None
        if answers:

            def acknowledge(level: int) -> int:
                return answers.get(level, AUTOVECTOR)

        tas_write = None
        if manifest.tas_write == "drop":
            faults = self._faults(manifest.bus_error)

            def tas_write(address: int, value: int) -> None:
                if faults(address):
                    raise BusError
                # The write cycle never completes: nothing reaches memory.

        self.cpu = M68000CPU(
            read_byte,
            read_word,
            write_byte,
            write_word,
            acknowledge=acknowledge,
            tas_write=tas_write,
        )
        if manifest.reset:
            self.cpu.reset()
        else:
            self.cpu.restore_state(manifest.initial)

    def peek_word(self, address: int) -> int:
        """Side-effect-free word read for disassembly: memory, never the reads stream."""
        address &= 0xFFFFFF
        return (self.memory[address] << 8) | self.memory[(address + 1) & 0xFFFFFF]

    @staticmethod
    def _faults(ranges: tuple[AddressRange, ...]) -> Callable[[int], bool]:
        spans = tuple((item.address, item.address + item.length) for item in ranges)
        return lambda address: any(start <= address < end for start, end in spans)

    def _next_read(self) -> int:
        index = self.reads_consumed * 2
        if index >= len(self._reads):
            return 0xFFFF
        self.reads_consumed += 1
        return (self._reads[index] << 8) | self._reads[index + 1]

    def _bus(self, manifest: Manifest) -> tuple[Callable, Callable, Callable, Callable]:
        memory = self.memory
        if not manifest.bus_error and manifest.replay is None:
            # The common case pays for nothing it does not use.
            def read_word(address: int) -> int:
                return (memory[address] << 8) | memory[address + 1]

            def write_word(address: int, value: int) -> None:
                memory[address] = value >> 8
                memory[address + 1] = value & 0xFF

            return memory.__getitem__, read_word, memory.__setitem__, write_word

        faults = self._faults(manifest.bus_error)
        devices = self._faults(manifest.replay.devices if manifest.replay else ())
        next_read = self._next_read

        def read_byte(address: int) -> int:
            if faults(address):
                raise BusError
            if devices(address):
                return next_read() & 0xFF
            return memory[address]

        def read_word(address: int) -> int:
            if faults(address):
                raise BusError
            if devices(address):
                return next_read()
            return (memory[address] << 8) | memory[address + 1]

        def write_byte(address: int, value: int) -> None:
            if faults(address):
                raise BusError
            if not devices(address):
                memory[address] = value

        def write_word(address: int, value: int) -> None:
            if faults(address):
                raise BusError
            if not devices(address):
                memory[address] = value >> 8
                memory[address + 1] = value & 0xFF

        return read_byte, read_word, write_byte, write_word


@dataclass(frozen=True, slots=True)
class TraceRun:
    """Why a reference run ended: records, the clocks they spent, and the reason.

    ``clocks`` is the sum of the records' ``cycles``; a ``reset()`` (the
    manifest's or an event's) is not a record and is not in it.
    """

    steps: int
    clocks: int
    reason: str


class _Stop:
    """Why :func:`_boundaries` stopped; filled in when the generator ends."""

    reason = "max_steps"


_IDLE = (BoundaryKind.HALTED_IDLE, BoundaryKind.STOPPED_IDLE)


def _boundaries(manifest: Manifest, host: ConformanceHost, stopped: _Stop) -> Iterator[int]:
    """Yield the index of every boundary the run executes, in order.

    Before each index the events due at it are applied and the stop checks
    run in the reference order: events, ``at_pc``, ``on_idle``, then the
    step budget.  The caller performs the boundary itself.
    """
    events = list(manifest.events)
    stop = manifest.stop
    cpu = host.cpu
    steps = 0
    while steps < stop.max_steps:
        while events and events[0].at_step == steps:
            _apply_event(cpu, events.pop(0))
        state = cpu.capture_state()
        if state.pc in stop.at_pc:
            stopped.reason = "at_pc"
            return
        if stop.on_idle and not events and next_boundary(state) in _IDLE:
            stopped.reason = "idle"
            return
        yield steps
        steps += 1
    stopped.reason = "max_steps"


def _apply_event(cpu: M68000CPU, event: Event) -> None:
    if event.kind == "ipl":
        cpu.set_ipl(event.level)
    else:
        cpu.reset()


def trace_manifest(
    manifest: Manifest, *, result: list[TraceRun] | None = None
) -> Iterator[StepRecord]:
    """Run ``manifest`` on the reference core, yielding one record per boundary.

    Every record carries its bus accesses (a session with
    ``track_accesses=True``).  Records are produced lazily so a long run can
    be written or compared without buffering.  When the iterator is
    exhausted, a :class:`TraceRun` is appended to ``result`` if one is given.
    """
    host = ConformanceHost(manifest)
    session = DebugSession(host.cpu, peek_word=host.peek_word, history_limit=0, track_accesses=True)
    stopped = _Stop()
    steps = 0
    for index in _boundaries(manifest, host, stopped):
        yield session.step()
        steps = index + 1
    if result is not None:
        result.append(TraceRun(steps, session.total_cycles, stopped.reason))


def diff_manifest(manifest: Manifest, external: Iterable[StepRecord]) -> TraceDivergence | None:
    """Run the reference in lockstep against ``external`` and return the first divergence."""
    return first_trace_divergence(trace_manifest(manifest), external)


# --- manifest serialization --------------------------------------------------

_STATE_FIELD_NAMES = tuple(item.name for item in fields(CPUState))
_MANIFEST_KEYS = {
    *("version", "name", "host", "memory", "reset", "initial", "acknowledge"),
    *("bus_error", "tas_write", "replay", "events", "stop"),
}


def manifest_to_dict(manifest: Manifest) -> dict[str, object]:
    """Return the versioned JSON-compatible form of a manifest (data inline, as hex)."""
    if type(manifest) is not Manifest:
        raise TypeError("manifest must be a Manifest")
    out: dict[str, object] = {
        "version": MANIFEST_SCHEMA_VERSION,
        "name": manifest.name,
        "host": manifest.host,
        "memory": [
            {"address": segment.address, "data": segment.data.hex()} for segment in manifest.memory
        ],
    }
    if manifest.reset:
        out["reset"] = True
    else:
        out["initial"] = {
            name: list(value) if isinstance(value, tuple) else value
            for name in _STATE_FIELD_NAMES
            for value in (getattr(manifest.initial, name),)
        }
    names = {value: name for name, value in ACKNOWLEDGE_NAMES.items()}
    out["acknowledge"] = {
        str(level): names.get(answer, answer) for level, answer in manifest.acknowledge
    }
    out["bus_error"] = [_range_to_dict(item) for item in manifest.bus_error]
    out["tas_write"] = manifest.tas_write
    if manifest.replay is not None:
        out["replay"] = {
            "devices": [_range_to_dict(item) for item in manifest.replay.devices],
            "reads": {"data": manifest.replay.reads.hex()},
        }
    out["events"] = [
        {"at_step": event.at_step, "kind": event.kind}
        | ({"level": event.level} if event.kind == "ipl" else {})
        for event in manifest.events
    ]
    out["stop"] = {
        "max_steps": manifest.stop.max_steps,
        "on_idle": manifest.stop.on_idle,
        "at_pc": list(manifest.stop.at_pc),
    }
    return out


def manifest_from_dict(value: object, *, base_dir: Path | None = None) -> Manifest:
    """Build a validated manifest from its JSON form.

    ``initial`` may list any subset of CPUState fields; the rest take
    CPUState's defaults.  When it gives neither ``ir`` nor ``irc``, they are
    read from the loaded memory at ``pc`` and ``pc + 2`` (not through the
    bus: no BERR, no device read, no clocks); giving one without the other
    is an error.  ``reset: true`` and ``initial`` exclude each other.  A
    memory segment, and the replay reads, carry either ``data`` (hex) or
    ``file`` (a path relative to ``base_dir``, with optional ``offset`` and
    ``length``).
    """
    root = _object(value, "manifest")
    _allowed(
        root,
        "manifest",
        _MANIFEST_KEYS,
        required={"version", "name", "memory", "stop"},
    )
    if root["version"] != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"unsupported manifest version: {root['version']!r}")
    memory = tuple(
        _segment(_object(item, f"memory[{index}]"), index, base_dir)
        for index, item in enumerate(_list(root["memory"], "memory"))
    )
    reset = root.get("reset", False)
    if reset is True and "initial" in root:
        raise ValueError("manifest reset and initial exclude each other")
    initial = _initial(_object(root.get("initial", {}), "initial"), memory)
    acknowledge = _acknowledge(_object(root.get("acknowledge", {}), "acknowledge"))
    bus_error = tuple(
        _range(_object(item, f"bus_error[{index}]"), f"bus_error[{index}]")
        for index, item in enumerate(_list(root.get("bus_error", []), "bus_error"))
    )
    replay = None
    if "replay" in root:
        replay = _replay(_object(root["replay"], "replay"), base_dir)
    stop_dict = _object(root["stop"], "stop")
    _allowed(stop_dict, "stop", {"max_steps", "on_idle", "at_pc"}, required={"max_steps"})
    at_pc = _list(stop_dict.get("at_pc", []), "stop.at_pc")
    events = tuple(
        _event(_object(item, f"events[{index}]"), index)
        for index, item in enumerate(_list(root.get("events", []), "events"))
    )
    try:
        return Manifest(
            name=root["name"],
            memory=memory,
            initial=initial,
            stop=StopRule(
                max_steps=stop_dict["max_steps"],
                on_idle=stop_dict.get("on_idle", True),
                at_pc=tuple(at_pc),
            ),
            host=root.get("host", "flat"),
            reset=reset,
            acknowledge=acknowledge,
            bus_error=bus_error,
            tas_write=root.get("tas_write", "write"),
            replay=replay,
            events=events,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid manifest: {exc}") from exc


def load_manifest(path: str | Path) -> Manifest:
    """Read and validate a manifest file; ``file`` entries resolve beside it."""
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        try:
            value = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: not valid JSON: {exc}") from exc
    return manifest_from_dict(value, base_dir=path.parent)


def _initial(item: dict[str, object], memory: tuple[MemorySegment, ...]) -> CPUState:
    _allowed(item, "initial", set(_STATE_FIELD_NAMES), required=set())
    if ("ir" in item) != ("irc" in item):
        raise ValueError("initial must give both ir and irc, or neither")
    values = {key: tuple(value) if type(value) is list else value for key, value in item.items()}
    try:
        state = CPUState(**values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid initial state: {exc}") from exc
    if "ir" in item:
        return state

    def byte(address: int) -> int:
        value = 0  # a later segment overwrites an earlier one, as loading does
        for segment in memory:
            if segment.address <= address < segment.address + len(segment.data):
                value = segment.data[address - segment.address]
        return value

    def word(address: int) -> int:
        address &= 0xFFFFFF
        return (byte(address) << 8) | byte((address + 1) & 0xFFFFFF)

    return replace(state, ir=word(state.pc), irc=word(state.pc + 2))


def _acknowledge(item: dict[str, object]) -> tuple[tuple[int, int], ...]:
    pairs = []
    for key, answer in item.items():
        if key not in tuple("1234567"):
            raise ValueError(f"acknowledge keys are the levels '1'..'7', got {key!r}")
        if type(answer) is str:
            if answer not in ACKNOWLEDGE_NAMES:
                raise ValueError(f"acknowledge answers are 0-255, {sorted(ACKNOWLEDGE_NAMES)}")
            answer = ACKNOWLEDGE_NAMES[answer]
        elif type(answer) is not int or not 0 <= answer <= 0xFF:
            raise ValueError(f"acknowledge answers are 0-255, {sorted(ACKNOWLEDGE_NAMES)}")
        pairs.append((int(key), answer))
    return tuple(sorted(pairs))


def _range(item: dict[str, object], name: str) -> AddressRange:
    _allowed(item, name, {"address", "length"}, required={"address", "length"})
    try:
        return AddressRange(item["address"], item["length"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: {exc}") from exc


def _range_to_dict(item: AddressRange) -> dict[str, int]:
    return {"address": item.address, "length": item.length}


def _replay(item: dict[str, object], base_dir: Path | None) -> Replay:
    _allowed(item, "replay", {"devices", "reads"}, required={"devices", "reads"})
    devices = tuple(
        _range(_object(window, f"replay.devices[{index}]"), f"replay.devices[{index}]")
        for index, window in enumerate(_list(item["devices"], "replay.devices"))
    )
    reads_dict = _object(item["reads"], "replay.reads")
    reads = _bytes(reads_dict, "replay.reads", base_dir, allow_empty=True)
    try:
        return Replay(devices, reads)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"replay: {exc}") from exc


def _segment(item: dict[str, object], index: int, base_dir: Path | None) -> MemorySegment:
    name = f"memory[{index}]"
    if "address" not in item:
        raise ValueError(f"{name} fields do not match schema (missing=['address'])")
    rest = {key: value for key, value in item.items() if key != "address"}
    data = _bytes(rest, name, base_dir, allow_empty=False)
    try:
        return MemorySegment(item["address"], data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: {exc}") from exc


def _bytes(
    item: dict[str, object], name: str, base_dir: Path | None, *, allow_empty: bool
) -> bytes:
    """The bytes of a ``data`` (hex) or ``file`` (+ ``offset``, ``length``) entry."""
    _allowed(item, name, {"data", "file", "offset", "length"}, required=set())
    if ("data" in item) == ("file" in item):
        raise ValueError(f"{name} must have exactly one of 'data' or 'file'")
    if "data" in item:
        if type(item["data"]) is not str:
            raise ValueError(f"{name}.data must be a hexadecimal string")
        try:
            data = bytes.fromhex(item["data"])
        except ValueError as exc:
            raise ValueError(f"{name}.data must be a hexadecimal string") from exc
        if "offset" in item or "length" in item:
            raise ValueError(f"{name}: offset and length go with file")
    else:
        if type(item["file"]) is not str:
            raise ValueError(f"{name}.file must be a path string")
        file_path = Path(item["file"])
        if not file_path.is_absolute():
            file_path = (base_dir or Path.cwd()) / file_path
        data = file_path.read_bytes()
        offset = item.get("offset", 0)
        length = item.get("length", len(data) - offset)
        if type(offset) is not int or type(length) is not int or offset < 0 or length < 0:
            raise ValueError(f"{name}.offset/length must be non-negative integers")
        data = data[offset : offset + length]
    if not data and not allow_empty:
        raise ValueError(f"{name}: segment data must be non-empty bytes")
    return data


def _event(item: dict[str, object], index: int) -> Event:
    name = f"events[{index}]"
    _allowed(item, name, {"at_step", "kind", "level"}, required={"at_step", "kind"})
    try:
        return Event(item["at_step"], item["kind"], item.get("level"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: {exc}") from exc


def _object(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return value


def _list(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise ValueError(f"{name} must be a list")
    return value


def _allowed(value: dict[str, object], name: str, keys: set[str], *, required: set[str]) -> None:
    unknown = sorted(set(value) - keys)
    missing = sorted(required - set(value))
    if unknown or missing:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if unknown:
            details.append(f"unknown={unknown}")
        raise ValueError(f"{name} fields do not match schema ({', '.join(details)})")


# --- command line --------------------------------------------------------------


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    """``trace`` writes the reference trace; ``diff`` reports the first divergence.

    Exit status: 0 on success or equal traces, 1 on divergence, 2 on bad input.
    """
    out = stdout or sys.stdout
    parser = argparse.ArgumentParser(
        prog="python -m m68000_python.conformance",
        description="Run a conformance manifest on the reference core or diff a trace against it.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    trace_cmd = commands.add_parser("trace", help="write the reference trace for a manifest")
    trace_cmd.add_argument("manifest")
    trace_cmd.add_argument("--out", help="JSON Lines output path (default: stdout)")
    diff_cmd = commands.add_parser("diff", help="compare an external trace against the reference")
    diff_cmd.add_argument("manifest")
    diff_cmd.add_argument("trace", help="JSON Lines trace path, or '-' for stdin")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=out)
        return 2

    if args.command == "trace":
        result: list[TraceRun] = []
        records = trace_manifest(manifest, result=result)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                count = write_trace(records, handle)
        else:
            count = write_trace(records, out)
        run = result[0]
        print(
            f"{manifest.name}: {count} records, {run.clocks} clocks, stopped on {run.reason}",
            file=sys.stderr if not args.out else out,
        )
        return 0

    try:
        if args.trace == "-":
            divergence = diff_manifest(manifest, read_trace(sys.stdin))
        else:
            with open(args.trace, encoding="utf-8") as handle:
                divergence = diff_manifest(manifest, read_trace(handle))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=out)
        return 2
    if divergence is None:
        print(f"{manifest.name}: traces are identical", file=out)
        return 0
    record = divergence.left or divergence.right
    where = "(end of trace)"
    if record is not None:
        if record.instruction is not None:
            where = f"{record.instruction.address:06X}: {record.instruction.text}"
        else:
            where = record.kind.value
    print(f"{manifest.name}: divergence at position {divergence.position}, {where}", file=out)
    for difference in divergence.differences:
        print(
            f"  {difference.path}: reference={difference.left!r} external={difference.right!r}",
            file=out,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
