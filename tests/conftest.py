"""Shared fixtures: a flat 16 MB bus that records every access."""

from __future__ import annotations

from m68000_python import M68000CPU


class Bus:
    """Flat RAM with an access log, standing in for a host."""

    def __init__(self) -> None:
        self.memory = bytearray(1 << 24)
        self.log: list[tuple[str, int, int]] = []

    def read_byte(self, address: int) -> int:
        self.log.append(("rb", address, self.memory[address]))
        return self.memory[address]

    def read_word(self, address: int) -> int:
        value = (self.memory[address] << 8) | self.memory[address + 1]
        self.log.append(("rw", address, value))
        return value

    def write_byte(self, address: int, value: int) -> None:
        self.memory[address] = value
        self.log.append(("wb", address, value))

    def write_word(self, address: int, value: int) -> None:
        self.memory[address] = value >> 8
        self.memory[address + 1] = value & 0xFF
        self.log.append(("ww", address, value))

    def word(self, address: int) -> int:
        return (self.memory[address] << 8) | self.memory[address + 1]

    def long(self, address: int) -> int:
        return (self.word(address) << 16) | self.word(address + 2)

    def set_word(self, address: int, value: int) -> None:
        self.memory[address] = value >> 8
        self.memory[address + 1] = value & 0xFF

    def set_long(self, address: int, value: int) -> None:
        self.set_word(address, value >> 16)
        self.set_word(address + 2, value & 0xFFFF)

    def load(self, address: int, words: list[int]) -> None:
        for index, word in enumerate(words):
            self.set_word(address + 2 * index, word)


def make(program: list[int], *, at: int = 0x1000, ssp: int = 0x8000, **kwargs):
    """A CPU with ``program`` at ``at`` after a reset through vectors 0 and 1."""
    bus = Bus()
    bus.set_long(0, ssp)
    bus.set_long(4, at)
    bus.load(at, program)
    cpu = M68000CPU(bus.read_byte, bus.read_word, bus.write_byte, bus.write_word, **kwargs)
    cpu.reset()
    bus.log.clear()
    return cpu, bus
