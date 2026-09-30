"""The documented consumer-facing API: exports, the embedding contract, CPUState."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, replace

import pytest
from conftest import make

import m68000_python
from m68000_python import AUTOVECTOR, M68000CPU, CPUState, console, cpu, debug, disasm, state, trace

#: Names a public module keeps to itself: helpers for its own callers, not contracts.
MODULE_ONLY = {"parse_number", "TraceValue", "EA_KIND"}


def _host(size: int = 0x10000) -> tuple[bytearray, M68000CPU]:
    memory = bytearray(size)

    def read_word(address: int) -> int:
        return (memory[address] << 8) | memory[address + 1]

    def write_word(address: int, value: int) -> None:
        memory[address] = value >> 8
        memory[address + 1] = value & 0xFF

    return memory, M68000CPU(memory.__getitem__, read_word, memory.__setitem__, write_word)


def test_root_exports_are_unique_and_resolve() -> None:
    names = m68000_python.__all__
    assert len(set(names)) == len(names)
    for name in names:
        getattr(m68000_python, name)


@pytest.mark.parametrize("module", [console, cpu, debug, disasm, state, trace])
def test_every_public_module_name_is_exported_from_the_root(module) -> None:
    missing = set(module.__all__) - MODULE_ONLY - set(m68000_python.__all__)
    assert not missing, f"{module.__name__} exports {sorted(missing)} that the root does not"
    for name in module.__all__:
        if name not in MODULE_ONLY:
            assert getattr(m68000_python, name) is getattr(module, name)


def test_four_callables_over_a_bytearray_are_a_complete_host() -> None:
    memory, processor = _host()
    memory[0:8] = (0x8000).to_bytes(4, "big") + (0x1000).to_bytes(4, "big")
    memory[0x1000:0x1004] = bytes((0x70, 0x05, 0x52, 0x80))  # moveq #5,D0; addq.l #1,D0

    assert processor.reset() == 40  # UM Table 8-14: 40(6/0)
    assert processor.step() == 4
    assert processor.step() == 8
    assert (processor.R[0], processor.PC, processor.R[15]) == (6, 0x1004, 0x8000)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ((None, None, None, None), "read_byte must be callable"),
        ((bytearray(2).__getitem__, 5, print, print), "read_word must be callable"),
        ((print, print, print, "x"), "write_word must be callable"),
    ],
)
def test_bus_callables_are_validated(arguments, message: str) -> None:
    with pytest.raises(TypeError, match=message):
        M68000CPU(*arguments)


@pytest.mark.parametrize(
    ("keyword", "message"),
    [
        ({"acknowledge": 5}, "acknowledge must be callable or None"),
        ({"tas_write": "no"}, "tas_write must be callable or None"),
        ({"address_error": 1}, "address_error must be callable or None"),
        ({"function_codes": 1}, "function_codes must be a bool"),
    ],
)
def test_optional_keywords_are_validated(keyword, message: str) -> None:
    _, processor = _host()
    memory = bytearray(16)
    with pytest.raises(TypeError, match=message):
        M68000CPU(memory.__getitem__, memory.__getitem__, memory.__setitem__, memory.__setitem__,
                  **keyword)  # fmt: skip
    del processor


def test_bus_callables_are_readable_and_replaceable() -> None:
    processor, bus = make([0x4E71, 0x4E71])
    assert (processor.read_byte, processor.read_word) == (bus.read_byte, bus.read_word)
    reads: list[int] = []

    def logging_read_word(address: int) -> int:
        reads.append(address)
        return bus.read_word(address)

    processor.attach_bus(bus.read_byte, logging_read_word, bus.write_byte, bus.write_word)
    processor.step()  # NOP: the closing prefetch reads the word two ahead
    assert reads == [0x1004]
    with pytest.raises(TypeError, match="read_word must be callable"):
        processor.attach_bus(bus.read_byte, None, bus.write_byte, bus.write_word)  # type: ignore[arg-type]


def test_set_ipl_and_the_acknowledge_answers_are_the_lifecycle_api() -> None:
    processor, _ = make([0x4E71])
    with pytest.raises(ValueError, match="0-7"):
        processor.set_ipl(8)
    processor.set_ipl(7)
    assert processor.ipl == 7
    assert AUTOVECTOR == -1  # a documented answer of acknowledge(level)


def test_set_pc_refuses_an_odd_address() -> None:
    processor, _ = make([0x4E71])
    with pytest.raises(ValueError, match="even"):
        processor.set_pc(0x1001)
    processor.set_pc(0x1002)
    assert processor.PC == 0x1002


def test_step_clocks_is_read_only() -> None:
    processor, _ = make([0x4E71])
    assert processor.step_clocks == 40  # the reset's total, between steps
    processor.step()
    assert processor.step_clocks == 4
    with pytest.raises(AttributeError):
        processor.step_clocks = 0  # type: ignore[misc]


def test_cpu_state_is_immutable_comparable_and_serializable() -> None:
    value = CPUState(d=(5, 0, 0, 0, 0, 0, 0, 0), pc=0x1000, sr=0x2700, stopped=True)

    assert value == CPUState(d=(5, 0, 0, 0, 0, 0, 0, 0), pc=0x1000, sr=0x2700, stopped=True)
    assert asdict(value)["pc"] == 0x1000
    assert value.a7 == value.ssp  # S is set in 0x2700
    with pytest.raises(FrozenInstanceError):
        value.pc = 0  # type: ignore[misc]


def test_capture_and_restore_cover_every_field_without_touching_the_host() -> None:
    processor, bus = make([0x4E71] * 8)
    processor.step()
    captured = processor.capture_state()
    changed = replace(
        captured,
        d=tuple(range(1, 9)),
        a=tuple(range(11, 18)),
        usp=0x1234,
        ssp=0x5678,
        sr=0x0015,  # user mode, X Z C
        pc=0x1004,
        ir=0x7005,
        irc=0x1234,
        ipl=3,
        nmi_edge=True,
        trace_pending=True,
        stopped=True,
        halted=True,
        clock=999,
    )
    for name in changed.__dataclass_fields__:
        assert getattr(changed, name) != getattr(captured, name), name
    memory = bytes(bus.memory)
    bus.log.clear()

    processor.restore_state(changed)

    assert processor.capture_state() == changed
    assert processor.R[15] == 0x1234  # user mode: A7 is the USP
    assert processor.ssp == 0x5678
    assert bus.log == [] and bytes(bus.memory) == memory
    processor.restore_state(captured)
    assert processor.capture_state() == captured


def test_restore_puts_each_stack_pointer_in_its_place() -> None:
    processor, _ = make([0x4E71])
    processor.restore_state(replace(processor.capture_state(), sr=0, usp=0x1234, ssp=0x5678))
    assert (processor.R[15], processor.ssp) == (0x1234, 0x5678)
    processor.set_sr(0x2000)
    assert (processor.R[15], processor.usp) == (0x5678, 0x1234)


@pytest.mark.parametrize(
    "change",
    [
        {"sr": 0x4000},
        {"ipl": 8},
        {"d": (0,) * 7},
        {"a": (0,) * 8},
        {"ir": 0x10000},
        {"pc": -1},
        {"pc": 0x1001},
        {"stopped": 1},
        {"clock": -1},
        {"d": (0.5,) + (0,) * 7},
    ],
)
def test_cpu_state_rejects_values_outside_its_contract(change) -> None:
    with pytest.raises(ValueError):
        CPUState(**change)


def test_restore_requires_a_cpu_state() -> None:
    processor, _ = make([0x4E71])
    with pytest.raises(TypeError, match="CPUState"):
        processor.restore_state({})  # type: ignore[arg-type]


def test_a_restored_state_continues_deterministically() -> None:
    processor, bus = make([0x7005, 0x5380, 0x66FC, 0x4E72, 0x2700])
    processor.step()
    saved = processor.capture_state()
    memory = bytes(bus.memory)
    first = [processor.step() for _ in range(6)] + [processor.capture_state()]
    bus.memory[:] = memory
    processor.restore_state(saved)
    second = [processor.step() for _ in range(6)] + [processor.capture_state()]
    assert first == second
