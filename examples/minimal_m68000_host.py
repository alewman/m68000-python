"""The smallest complete host: RAM, the two reset vectors, and nothing else on the bus.

The CPU takes its bus as four callables over a 24-bit address space.  A
bytearray's ``__getitem__`` and ``__setitem__`` serve the byte accesses as
they are, because the core always passes an address inside the space and an
8-bit value; two small functions assemble and split the words (big-endian,
as the chip does).  ``reset()`` fetches SSP and PC from addresses 0 and 4.
"""

from m68000_python import M68000CPU


def main() -> None:
    memory = bytearray(1 << 16)  # 64 KiB is enough here; a board would map 16 MB

    def read_word(address: int) -> int:
        return (memory[address] << 8) | memory[address + 1]

    def write_word(address: int, value: int) -> None:
        memory[address] = value >> 8
        memory[address + 1] = value & 0xFF

    memory[0:8] = (0x8000).to_bytes(4, "big") + (0x1000).to_bytes(4, "big")  # SSP, PC
    memory[0x1000:0x1004] = bytes((0x70, 0x05, 0x52, 0x80))  # moveq #5,D0; addq.l #1,D0

    cpu = M68000CPU(memory.__getitem__, read_word, memory.__setitem__, write_word)
    cpu.reset()
    first = cpu.step()
    second = cpu.step()

    assert (first, second, cpu.R[0]) == (4, 8, 6)
    print(f"D0={cpu.R[0]}; clocks={first}+{second}; PC=${cpu.PC:06X}")


if __name__ == "__main__":
    main()
