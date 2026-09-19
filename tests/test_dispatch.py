"""The opcode map: every first word decodes to exactly one handler."""

from collections import Counter

from m68000_python import M68000CPU
from m68000_python._dispatch import COMPILED, NAMES, decode


def test_defined_word_count_matches_the_opcode_map() -> None:
    # 45,815 defined first words: SingleStepTests/680x0's map/68000.official.json
    # has 19,721 None of 65,536 (docs/validation.md); MAME 0.285's m68000.lst
    # agrees word for word (checked when the table was written, docs/worklog.md).
    defined = sum(name not in ("illegal", "line_a", "line_f") for name in NAMES)
    assert defined == 45815
    counts = Counter(NAMES)
    assert counts["line_a"] == counts["line_f"] == 4096
    assert counts["illegal"] == 65536 - 45815 - 8192  # includes ILLEGAL itself ($4AFC)


def test_no_word_matches_two_rules() -> None:
    for opcode in range(0x10000):
        decode(opcode)  # raises on an overlap


def test_every_rule_is_reachable() -> None:
    names = set(NAMES)
    assert {name for _, _, name, _ in COMPILED} <= names


def test_table_is_built_once_per_class() -> None:
    first = M68000CPU(None, None, None, None)
    second = M68000CPU(None, None, None, None)
    assert first._table is second._table
    assert len(first._table) == 0x10000


def test_known_words() -> None:
    assert NAMES[0x4E71] == "nop"
    assert NAMES[0x4AFC] == "illegal"
    assert NAMES[0x61FF] == "bsr"  # a byte displacement of -1 on the 68000
    assert NAMES[0x0108] == "movep"
    assert NAMES[0x4E7A] == "illegal"  # MOVEC is 68010+
    assert NAMES[0x42C0] == "illegal"  # MOVE from CCR is 68010+
    assert NAMES[0x303C] == "move"
    assert NAMES[0x307C] == "movea"
    assert NAMES[0x13FC] == "move"
    assert NAMES[0x107C] == "illegal"  # MOVEA.B does not exist
