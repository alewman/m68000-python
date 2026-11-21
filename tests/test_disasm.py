"""The disassembler: every word, MAME's spelling, ranges, and the byte form's checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from m68000_python import Instruction, disassemble, disassemble_bytes, disassemble_range

GOLDEN = Path(__file__).resolve().parent / "disasm_mame.txt"


def _words(*words: int) -> bytes:
    return b"".join(word.to_bytes(2, "big") for word in words)


def test_every_first_word_disassembles_and_round_trips_through_its_bytes() -> None:
    memory: dict[int, int] = {}

    def read_word(address: int) -> int:
        return memory.get(address, 0x1234)

    for opcode in range(0x10000):
        memory[0x1000] = opcode
        instruction = disassemble(read_word, 0x1000)
        assert instruction.words[0] == opcode
        assert disassemble_bytes(instruction.data, 0x1000) == instruction


@pytest.mark.parametrize(
    ("words", "text"),
    [
        ((0x6000, 0x000C), "bra $40e"),
        ((0x4FF8, 0xFF00), "lea $ff00.w, A7"),
        ((0x46FC, 0x2700), "move #$2700, SR"),
        ((0x51C8, 0xFFFC), "dbra D0, $3fe"),
        ((0x48E7, 0xFFFE), "movem.l D0-D7/A0-A6, -(A7)"),
        ((0x4CDF, 0x7FFF), "movem.l (A7)+, D0-D7/A0-A6"),
        ((0x3030, 0x1804), "move.w ($4,A0,D1.l), D0"),
        ((0xE1A8,), "lsl.l D0, D0"),
        ((0x4AFC,), "illegal"),
        ((0x4AFA,), "dc.w $4afa; ILLEGAL"),  # undefined, though MAME's ILLEGAL set names it
        ((0xA123,), "dc.w $a123; opcode 1010"),
        ((0xF123,), "dc.w $f123; opcode 1111"),
        ((0x4E7A,), "dc.w $4e7a; ILLEGAL"),  # MOVEC is 68010+: one undefined word
    ],
)
def test_texts_follow_mame(words: tuple[int, ...], text: str) -> None:
    assert disassemble_bytes(_words(*words), 0x400).text == text


def test_instruction_value_exposes_words_bytes_length_and_text() -> None:
    instruction = disassemble_bytes(_words(0x33C0, 0x0000, 0x3000), 0x1006)
    assert instruction == Instruction(0x1006, (0x33C0, 0x0000, 0x3000), "move.w", ("D0", "$3000.l"))
    assert (instruction.length, instruction.data) == (6, bytes((0x33, 0xC0, 0, 0, 0x30, 0)))
    assert str(instruction) == instruction.text == "move.w D0, $3000.l"
    assert disassemble_bytes(_words(0x4E71)).operands == ()


def test_disassemble_range_walks_instruction_lengths() -> None:
    program = _words(0x7005, 0x5380, 0x66FC, 0x33C0, 0x0000, 0x3000, 0x4E72, 0x2700)
    memory = dict(zip(range(0x1000, 0x1000 + len(program), 2), (
        int.from_bytes(program[i : i + 2], "big") for i in range(0, len(program), 2)
    ), strict=True))  # fmt: skip

    instructions = disassemble_range(memory.__getitem__, 0x1000, 0x1000 + len(program))

    assert [instruction.address for instruction in instructions] == [
        0x1000, 0x1002, 0x1004, 0x1006, 0x100C
    ]  # fmt: skip
    assert [instruction.text for instruction in instructions] == [
        "moveq #$5, D0", "subq.l #1, D0", "bne $1002", "move.w D0, $3000.l", "stop #$2700"
    ]  # fmt: skip
    assert disassemble_range(memory.__getitem__, 0x1000, 0x1000) == []


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "non-empty whole number of words"),
        (b"\x4e", "non-empty whole number of words"),
        (_words(0x33C0), "shorter than the instruction"),
        (_words(0x4E71, 0x4E71), "longer than the instruction"),
    ],
)
def test_disassemble_bytes_requires_exactly_one_instruction(data: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        disassemble_bytes(data)


def _golden() -> list[tuple[int, bytes, str]]:
    rows = []
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        address, words, text = line.split("  ", 2)
        rows.append((int(address, 16), bytes.fromhex(words.replace(" ", "")), text))
    return rows


GOLDEN_ROWS = _golden()


def test_the_golden_file_is_large_enough_to_mean_something() -> None:
    assert len(GOLDEN_ROWS) >= 1000
    assert len({row[2].split()[0] for row in GOLDEN_ROWS}) >= 60  # distinct mnemonics


@pytest.mark.parametrize(
    ("address", "data", "text"), GOLDEN_ROWS, ids=[f"{row[0]:06X}" for row in GOLDEN_ROWS]
)
def test_spelling_matches_mame_on_real_code(address: int, data: bytes, text: str) -> None:
    """MAME 0.285's own disassembly of System 16B and Genesis Altered Beast.

    tests/disasm_mame.txt was written by validation/disasm_vs_mame.py
    --golden from the lockstep runs' debugger traces (docs/validation.md,
    rung 4); this checks the same spelling without MAME or the ROMs.
    """
    assert disassemble_bytes(data, address).text == text


def test_bytes_at_an_address_above_24_bits_decode_like_its_24_bit_alias() -> None:
    # A jump through a sign-extended short address leaves PC at $FFFFxxxx;
    # the bus sees A23-A1 only, so the words are read at the masked address.
    # Genesis Altered Beast runs code at $FFFFF200 (the conformance replay).
    instruction = disassemble_bytes(bytes.fromhex("4bf900c00004"), 0xFFFFF200)
    assert instruction.text == "lea $c00004.l, A5"
    assert instruction.address == 0xFFFFF200
