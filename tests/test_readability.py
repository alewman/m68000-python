"""Readability contract for the instruction core, enforced the way correctness is.

Following m6800-python's and z80-python's tests/test_readability.py: every
opcode handler must be findable by the Motorola name a 68000 programmer would
grep for, and must live in the module the brief assigns that instruction to
(docs/handoff-brief.md).  Checked from the source with :mod:`ast`:

1. Every ``_op_*`` method's docstring starts with one Motorola instruction
   name as PRM Sections 4 and 6 title it (``ADD``, ``ANDI to CCR``, ``MOVE
   USP``, ``ASd``), then `` -- `` and a description citing PRM or UM.
2. The method is named after it: ``_op_`` + the name in lower case with
   spaces as underscores (a ``_memory`` suffix marks the one-bit memory
   form of a shift).
3. It lives in the module that owns that instruction.
4. Every instruction has a handler, and every handler the dispatch table
   names exists: there is no fallback.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from m68000_python._dispatch import NAMES

SRC = Path(__file__).resolve().parents[1] / "src" / "m68000_python"

OWNERS: dict[str, frozenset[str]] = {
    "_alu.py": frozenset(
        "ADD ADDA ADDI ADDQ ADDX SUB SUBA SUBI SUBQ SUBX AND ANDI OR ORI EOR EORI "
        "CMP CMPA CMPI CMPM NEG NEGX NOT CLR TST TAS MULU MULS DIVU DIVS".split()
    ),
    "_loads.py": frozenset("MOVE MOVEA MOVEQ MOVEM MOVEP LEA PEA LINK UNLK EXG SWAP EXT".split()),
    "_bits.py": frozenset("BTST BCHG BCLR BSET".split()),
    "_shifts.py": frozenset("ASd LSd ROXd ROd".split()),
    "_bcd.py": frozenset("ABCD SBCD NBCD".split()),
    "_control.py": frozenset("Bcc BRA BSR DBcc Scc JMP JSR RTS RTR NOP".split()),
    "_system.py": frozenset(
        [
            *"TRAP TRAPV CHK ILLEGAL STOP RESET RTE".split(),
            "LINE A",
            "LINE F",
            "MOVE to SR",
            "MOVE from SR",
            "MOVE to CCR",
            "MOVE USP",
            "ANDI to CCR",
            "ANDI to SR",
            "ORI to CCR",
            "ORI to SR",
            "EORI to CCR",
            "EORI to SR",
        ]
    ),
}
MOTOROLA = frozenset().union(*OWNERS.values())
HEADLINE = re.compile(
    r"^(?P<name>[A-Z][A-Za-z]*(?: (?:to|from) (?:CCR|SR)| USP| [AF])?) -- (?P<text>.+)$"
)
CITATION = re.compile(r"\((PRM|UM) ")


def handlers() -> list[tuple[str, ast.FunctionDef]]:
    found = []
    for path in sorted(SRC.glob("_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            found += [
                (path.name, node)
                for node in cls.body
                if isinstance(node, ast.FunctionDef) and node.name.startswith("_op_")
            ]
    assert found
    return found


HANDLERS = handlers()


def headline(node: ast.FunctionDef) -> re.Match:
    doc = ast.get_docstring(node) or ""
    match = HEADLINE.match(doc.splitlines()[0] if doc else "")
    assert match, f"{node.name}: docstring must start 'NAME -- ...', got {doc[:50]!r}"
    return match


def method_name(name: str) -> str:
    return "_op_" + name.lower().replace(" ", "_")


@pytest.mark.parametrize("module,node", HANDLERS, ids=lambda x: getattr(x, "name", x))
def test_docstring_names_one_motorola_instruction_and_cites_the_manual(module, node) -> None:
    match = headline(node)
    name = match.group("name")
    assert name in MOTOROLA, f"{node.name}: {name!r} is not a 68000 instruction name"
    assert node.name in (method_name(name), method_name(name) + "_memory"), node.name
    assert CITATION.search(match.group("text")), f"{node.name}: no manual section cited"


@pytest.mark.parametrize("module,node", HANDLERS, ids=lambda x: getattr(x, "name", x))
def test_handler_lives_in_owning_module(module, node) -> None:
    name = headline(node).group("name")
    assert name in OWNERS[module], f"{name} is misfiled in {module}"


def test_every_instruction_has_a_handler_and_every_table_name_resolves() -> None:
    names = [headline(node).group("name") for _, node in HANDLERS]
    assert set(names) == MOTOROLA
    methods = {node.name for _, node in HANDLERS}
    assert len(methods) == len(HANDLERS), "a handler is defined twice"
    assert {"_op_" + name for name in set(NAMES)} <= methods
