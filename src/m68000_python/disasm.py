"""Disassemble 68000 code, from the same opcode map the core dispatches on.

``disassemble(read_word, address)`` decodes the instruction at ``address``
and returns an :class:`Instruction`: its address, its words, and its text.
Which instruction a first word is comes from ``_dispatch.NAMES``, the table
the core itself runs, so the disassembler and the core cannot disagree about
what a word means.  The text follows MAME's 68000 disassembler (m68kdasm.cpp
at mame0285: lowercase mnemonics with a size suffix, ``$`` hex, ``D0``/``A0``
registers, PC-relative operands shown as their target address), so a
disassembly can be diffed against a MAME trace line by line.
"""

from collections.abc import Callable
from dataclasses import dataclass

from m68000_python._dispatch import NAMES
from m68000_python._flags import CONDITION_NAMES

WordReader = Callable[[int], int]

SIZE_SUFFIX = {0: ".b", 1: ".w", 2: ".l"}
MOVE_SUFFIX = {1: ".b", 3: ".w", 2: ".l"}


@dataclass(frozen=True, slots=True)
class Instruction:
    """One disassembled instruction."""

    address: int
    words: tuple[int, ...]
    mnemonic: str
    operands: tuple[str, ...]

    @property
    def length(self) -> int:
        return 2 * len(self.words)

    @property
    def data(self) -> bytes:
        """The instruction's bytes, big-endian."""
        return b"".join(word.to_bytes(2, "big") for word in self.words)

    @property
    def text(self) -> str:
        if not self.operands:
            return self.mnemonic
        return f"{self.mnemonic} {', '.join(self.operands)}"

    def __str__(self) -> str:
        return self.text


def _signed_hex_8(value: int) -> str:
    value &= 0xFF
    if value & 0x80:
        return f"-${(0x100 - value):x}"
    return f"${value:x}"


def _signed_hex_16(value: int) -> str:
    value &= 0xFFFF
    if value & 0x8000:
        return f"-${(0x10000 - value):x}"
    return f"${value:x}"


def _signed_hex_32(value: int) -> str:
    value &= 0xFFFFFFFF
    if value & 0x80000000:
        return f"-${(0x100000000 - value):x}"
    return f"${value:x}"


def _sign_16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


class _Reader:
    """Reads the words after the opcode, remembering them."""

    def __init__(self, read_word: WordReader, address: int) -> None:
        self.read_word = read_word
        self.pc = address + 2
        self.words: list[int] = []

    def word(self) -> int:
        value = self.read_word(self.pc & 0xFFFFFF) & 0xFFFF
        self.words.append(value)
        self.pc += 2
        return value

    def long(self) -> int:
        high = self.word()
        return (high << 16) | self.word()

    def ea(self, field: int, size: int) -> str:
        """Format the operand of a 6-bit EA field; ``size`` 0/1/2 for immediates."""
        mode, register = field >> 3, field & 7
        if mode == 0:
            return f"D{register}"
        if mode == 1:
            return f"A{register}"
        if mode == 2:
            return f"(A{register})"
        if mode == 3:
            return f"(A{register})+"
        if mode == 4:
            return f"-(A{register})"
        if mode == 5:
            return f"({_signed_hex_16(self.word())},A{register})"
        if mode == 6:
            return self._index(f"A{register}")
        if register == 0:
            return f"${self.word():x}.w"
        if register == 1:
            return f"${self.long():x}.l"
        if register == 2:
            base = self.pc
            return f"(${(base + _sign_16(self.word())) & 0xFFFFFFFF:x},PC)"
        if register == 3:
            return self._index("PC")
        if register == 4:
            if size == 0:
                return f"#${self.word() & 0xFF:x}"
            if size == 1:
                return f"#${self.word():x}"
            return f"#${self.long():x}"
        return "?"

    def _index(self, base: str) -> str:
        extension = self.word()
        kind = "A" if extension & 0x8000 else "D"
        register = (extension >> 12) & 7
        width = "l" if extension & 0x0800 else "w"
        displacement = extension & 0xFF
        if displacement:
            return f"({_signed_hex_8(displacement)},{base},{kind}{register}.{width})"
        return f"({base},{kind}{register}.{width})"


def _register_list(mask: int, reverse: bool) -> str:
    """MOVEM's register mask as ``D0-D3/A6``; reversed for -(An) (PRM 4, MOVEM)."""
    if reverse:
        mask = int(f"{mask:016b}"[::-1], 2)
    parts = []
    for bank, offset in (("D", 0), ("A", 8)):
        index = 0
        while index < 8:
            if mask & (1 << (offset + index)):
                start = index
                while index + 1 < 8 and mask & (1 << (offset + index + 1)):
                    index += 1
                if start == index:
                    parts.append(f"{bank}{start}")
                else:
                    parts.append(f"{bank}{start}-{bank}{index}")
            index += 1
    return "/".join(parts)


QUICK = (8, 1, 2, 3, 4, 5, 6, 7)


def _decode(name: str, opcode: int, reader: _Reader) -> tuple[str, tuple[str, ...]]:
    """Mnemonic and operands of one instruction; extension words come from ``reader``."""
    size_bits = (opcode >> 6) & 3
    suffix = SIZE_SUFFIX.get(size_bits, "")
    ea = opcode & 0x3F
    rx = (opcode >> 9) & 7
    ry = opcode & 7
    cc = CONDITION_NAMES[(opcode >> 8) & 0xF].lower()

    if name in ("subi", "addi", "cmpi"):
        # Arithmetic immediates print signed, logical ones unsigned (MAME's
        # get_imm_str_s / get_imm_str_u).
        if size_bits == 0:
            immediate = "#" + _signed_hex_8(reader.word())
        elif size_bits == 1:
            immediate = "#" + _signed_hex_16(reader.word())
        else:
            immediate = "#" + _signed_hex_32(reader.long())
        return name + suffix, (immediate, reader.ea(ea, size_bits))
    if name in ("ori", "andi", "eori"):
        immediate = reader.ea(0x3C, size_bits)
        return name + suffix, (immediate, reader.ea(ea, size_bits))
    if name.endswith(("_to_ccr", "_to_sr")) and name[:4] in ("ori_", "andi", "eori"):
        base = name.split("_")[0]
        target = "CCR" if name.endswith("ccr") else "SR"
        width = 0 if target == "CCR" else 1
        return base, (reader.ea(0x3C, width), target)
    if name in ("btst", "bchg", "bclr", "bset"):
        if opcode & 0x0100:
            return name, (f"D{rx}", reader.ea(ea, 0))
        return name, (f"#${reader.word() & 0xFF:x}", reader.ea(ea, 0))
    if name == "movep":
        displacement = _signed_hex_16(reader.word())
        width = ".l" if opcode & 0x40 else ".w"
        if opcode & 0x80:
            return "movep" + width, (f"D{rx}", f"({displacement},A{ry})")
        return "movep" + width, (f"({displacement},A{ry})", f"D{rx}")
    if name == "move":
        size = MOVE_SUFFIX[opcode >> 12]
        source = reader.ea(ea, {".b": 0, ".w": 1, ".l": 2}[size])
        destination = reader.ea(((opcode >> 3) & 0x38) | rx, 0)
        return "move" + size, (source, destination)
    if name == "movea":
        size = ".w" if opcode >> 12 == 3 else ".l"
        return "movea" + size, (reader.ea(ea, 1 if size == ".w" else 2), f"A{rx}")
    if name == "move_from_sr":
        return "move", ("SR", reader.ea(ea, 1))
    if name == "move_to_ccr":
        return "move", (reader.ea(ea, 1), "CCR")
    if name == "move_to_sr":
        return "move", (reader.ea(ea, 1), "SR")
    if name in ("negx", "clr", "neg", "not", "tst"):
        return name + suffix, (reader.ea(ea, size_bits),)
    if name in ("nbcd", "tas", "pea", "jsr", "jmp"):
        return name, (reader.ea(ea, 2),)
    if name == "swap":
        return "swap", (f"D{ry}",)
    if name == "ext":
        return "ext.l" if opcode & 0x40 else "ext.w", (f"D{ry}",)
    if name == "movem":
        width = ".l" if opcode & 0x40 else ".w"
        mask = reader.word()
        if opcode & 0x0400:
            return "movem" + width, (reader.ea(ea, 1), _register_list(mask, False))
        predecrement = (ea >> 3) == 4
        return "movem" + width, (_register_list(mask, predecrement), reader.ea(ea, 1))
    if name == "trap":
        return "trap", (f"#${opcode & 0xF:x}",)
    if name == "link":
        return "link", (f"A{ry}", f"#{_signed_hex_16(reader.word())}")
    if name == "unlk":
        return "unlk", (f"A{ry}",)
    if name == "move_usp":
        if opcode & 8:
            return "move", ("USP", f"A{ry}")
        return "move", (f"A{ry}", "USP")
    if name == "stop":
        return "stop", ("#" + _signed_hex_16(reader.word()),)
    if name in ("reset", "nop", "rte", "rts", "trapv", "rtr"):
        return name, ()
    if name == "illegal" and opcode == 0x4AFC:
        return "illegal", ()  # the one word that is ILLEGAL by name (PRM 4-107)
    if name == "chk":
        return "chk.w", (reader.ea(ea, 1), f"D{rx}")
    if name == "lea":
        return "lea", (reader.ea(ea, 2), f"A{rx}")
    if name in ("addq", "subq"):
        return name + suffix, (f"#{QUICK[rx]}", reader.ea(ea, size_bits))
    if name == "dbcc":
        base = reader.pc
        target = (base + _sign_16(reader.word())) & 0xFFFFFFFF
        # DBF is written DBRA, the assembler's name for it, as MAME writes it.
        return "dbra" if cc == "f" else f"db{cc}", (f"D{ry}", f"${target:x}")
    if name == "scc":
        return f"s{cc}", (reader.ea(ea, 0),)
    if name in ("bra", "bsr", "bcc"):
        mnemonic = name if name != "bcc" else f"b{cc}"
        base = reader.pc
        displacement = opcode & 0xFF
        if displacement:
            offset = displacement - 0x100 if displacement & 0x80 else displacement
            return mnemonic, (f"${(base + offset) & 0xFFFFFFFF:x}",)
        return mnemonic, (f"${(base + _sign_16(reader.word())) & 0xFFFFFFFF:x}",)
    if name == "moveq":
        return "moveq", (f"#{_signed_hex_8(opcode)}", f"D{rx}")
    if name in ("divu", "divs", "mulu", "muls"):
        return name + ".w", (reader.ea(ea, 1), f"D{rx}")
    if name in ("sbcd", "abcd", "addx", "subx"):
        width = suffix if name in ("addx", "subx") else ""
        if opcode & 8:
            return name + width, (f"-(A{ry})", f"-(A{rx})")
        return name + width, (f"D{ry}", f"D{rx}")
    if name in ("or", "and", "sub", "add", "eor", "cmp"):
        if opcode & 0x0100 and name != "cmp":
            return name + suffix, (f"D{rx}", reader.ea(ea, size_bits))
        return name + suffix, (reader.ea(ea, size_bits), f"D{rx}")
    if name in ("suba", "adda", "cmpa"):
        width = ".l" if opcode & 0x0100 else ".w"
        return name + width, (reader.ea(ea, 2 if width == ".l" else 1), f"A{rx}")
    if name == "cmpm":
        return "cmpm" + suffix, (f"(A{ry})+", f"(A{rx})+")
    if name == "exg":
        mode = (opcode >> 3) & 0x1F
        if mode == 0x08:
            return "exg", (f"D{rx}", f"D{ry}")
        if mode == 0x09:
            return "exg", (f"A{rx}", f"A{ry}")
        return "exg", (f"D{rx}", f"A{ry}")
    if name.endswith("_memory"):
        base = name.split("d_")[0]
        direction = "l" if opcode & 0x0100 else "r"
        return f"{base}{direction}.w", (reader.ea(ea, 1),)
    if name in ("asd", "lsd", "roxd", "rod"):
        base = name[:-1]
        direction = "l" if opcode & 0x0100 else "r"
        count = f"D{rx}" if opcode & 0x20 else f"#{QUICK[rx]}"
        return f"{base}{direction}{suffix}", (count, f"D{ry}")
    if name == "line_a":
        return "dc.w", (f"${opcode:04x}; opcode 1010",)
    if name == "line_f":
        return "dc.w", (f"${opcode:04x}; opcode 1111",)
    return "dc.w", (f"${opcode:04x}; ILLEGAL",)


def disassemble(read_word: WordReader, address: int) -> Instruction:
    """Disassemble the instruction at ``address``; ``read_word`` reads memory."""
    opcode = read_word(address & 0xFFFFFF) & 0xFFFF
    reader = _Reader(read_word, address)
    mnemonic, operands = _decode(NAMES[opcode], opcode, reader)
    return Instruction(address, (opcode, *reader.words), mnemonic, operands)


def disassemble_bytes(data: bytes, address: int = 0) -> Instruction:
    """Disassemble one instruction from ``data`` (big-endian) placed at ``address``.

    Raises ValueError unless ``data`` holds exactly that one instruction.
    """
    if len(data) % 2 or not data:
        raise ValueError("instruction data must be a non-empty whole number of words")
    words = {address + i: (data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)}

    def read_word(where: int) -> int:
        if where not in words:
            raise ValueError("instruction data is shorter than the instruction")
        return words[where]

    instruction = disassemble(read_word, address)
    if instruction.length != len(data):
        raise ValueError("instruction data is longer than the instruction")
    return instruction


def disassemble_range(read_word: WordReader, start: int, end: int) -> list[Instruction]:
    """Disassemble every instruction from ``start`` up to (not including) ``end``."""
    result = []
    address = start
    while address < end:
        instruction = disassemble(read_word, address)
        result.append(instruction)
        address += instruction.length
    return result


__all__ = [
    "Instruction",
    "WordReader",
    "disassemble",
    "disassemble_bytes",
    "disassemble_range",
]
