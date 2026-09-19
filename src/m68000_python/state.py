"""Immutable values for capturing and restoring MC68000 processor state."""

from dataclasses import dataclass


def _require_int(name: str, value: object, maximum: int) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in range 0..{maximum:#x}")


def _require_bool(name: str, value: object) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a bool")


@dataclass(frozen=True, slots=True)
class CPUState:
    """Complete CPU-owned state at an instruction boundary.

    Registers, the prefetch queue, the interrupt input as the core last saw
    it, and the internal state that decides what the next ``step()`` does.
    Host memory, devices and scheduling are excluded: restoring this value
    restores the processor, not a machine.

    ``pc`` is the address of the instruction in ``ir``; the queue has read
    ``irc`` from ``pc + 2`` and will next read ``pc + 4`` (the SingleStepTests
    corpus's ``pc``).  Stopped by STOP, ``pc`` is the STOP's own address and
    execution resumes at ``pc + 4``.
    """

    d: tuple[int, ...] = (0,) * 8
    a: tuple[int, ...] = (0,) * 7
    usp: int = 0
    ssp: int = 0
    sr: int = 0x2700
    pc: int = 0
    ir: int = 0
    irc: int = 0
    # Inputs, as the host has set them.
    ipl: int = 0
    # Internal state.
    nmi_edge: bool = False  # a level 7 edge seen and not yet taken
    trace_pending: bool = False  # the last instruction ran with T set
    stopped: bool = False  # inside STOP
    halted: bool = False  # double bus fault: only reset leaves it
    clock: int = 0  # clocks run so far (the E-clock phase comes from it)

    def __post_init__(self) -> None:
        if len(self.d) != 8 or len(self.a) != 7:
            raise ValueError("d must hold 8 values and a 7 (A7 is usp or ssp)")
        for index, value in enumerate(self.d):
            _require_int(f"d{index}", value, 0xFFFFFFFF)
        for index, value in enumerate(self.a):
            _require_int(f"a{index}", value, 0xFFFFFFFF)
        for name in ("usp", "ssp", "pc"):
            _require_int(name, getattr(self, name), 0xFFFFFFFF)
        for name in ("ir", "irc"):
            _require_int(name, getattr(self, name), 0xFFFF)
        _require_int("sr", self.sr, 0xFFFF)
        if self.sr & ~0xA71F:
            raise ValueError("sr bits 14, 12, 11 and 7-5 read as zero on the 68000")
        _require_int("ipl", self.ipl, 7)
        _require_int("clock", self.clock, (1 << 64) - 1)
        for name in ("nmi_edge", "trace_pending", "stopped", "halted"):
            _require_bool(name, getattr(self, name))

    @property
    def a7(self) -> int:
        """The active stack pointer: ``ssp`` in supervisor mode, else ``usp``."""
        return self.ssp if self.sr & 0x2000 else self.usp


__all__ = ["CPUState"]
