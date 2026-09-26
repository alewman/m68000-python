"""A host that raises an interrupt: the level on IPL, the acknowledge, the handler, RTE.

The processor sees interrupts as a level the host sets between steps with
``set_ipl(level)``.  When the level exceeds the mask in SR (or is 7, once per
0-to-7 edge), the next ``step()`` is the interrupt entry: it asks the host's
``acknowledge(level)`` callable for the vector -- a number, ``AUTOVECTOR``
(vector 24 + level, what nearly every arcade board answers) or ``SPURIOUS`` --
pushes PC and SR, and enters the handler.  The host clears the level when its
device is satisfied; here the handler's own write to the device does it.
"""

from m68000_python import AUTOVECTOR, M68000CPU

DEVICE = 0xC00000  # a write here acknowledges the device, as a real board's would


def main() -> None:
    memory = bytearray(1 << 24)
    log: list[str] = []

    def read_word(address: int) -> int:
        return (memory[address] << 8) | memory[address + 1]

    def write_word(address: int, value: int) -> None:
        if address == DEVICE:
            log.append(f"device acknowledged with ${value:04X}")
            cpu.set_ipl(0)  # the device drops its request
            return
        memory[address] = value >> 8
        memory[address + 1] = value & 0xFF

    def acknowledge(level: int) -> int:
        log.append(f"acknowledge cycle for level {level}: autovector")
        return AUTOVECTOR

    def load(address: int, words: list[int]) -> None:
        for index, word in enumerate(words):
            write_word(address + 2 * index, word)

    load(0, [0x0000, 0x8000, 0x0000, 0x1000])  # SSP $8000, PC $1000
    load(0x70, [0x0000, 0x2000])  # vector 28, the level 4 autovector: handler at $2000
    load(0x1000, [0x4E71, 0x60FC])  # nop; bra.s *-2: a program waiting for the interrupt
    load(0x2000, [0x33FC, 0x00FF, 0x00C0, 0x0000, 0x4E73])  # move.w #$ff,DEVICE; rte

    cpu = M68000CPU(memory.__getitem__, read_word, memory.__setitem__, write_word,
                    acknowledge=acknowledge)  # fmt: skip
    cpu.reset()
    cpu.set_sr(0x2000)  # supervisor, mask 0: any level is accepted
    cpu.step()  # nop
    cpu.set_ipl(4)  # the device raises level 4 between instructions
    entry = cpu.step()  # the interrupt entry, not an instruction
    log.append(
        f"entered the handler at ${cpu.PC:06X} in {entry} clocks, mask now {cpu.SR >> 8 & 7}"
    )
    cpu.step()  # move.w #$ff,DEVICE: the write clears the request
    cpu.step()  # rte
    log.append(f"back at ${cpu.PC:06X} with SR ${cpu.SR:04X}")

    assert cpu.PC == 0x1002 and cpu.ipl == 0 and 44 + 5 <= entry <= 44 + 14
    print("\n".join(log))


if __name__ == "__main__":
    main()
