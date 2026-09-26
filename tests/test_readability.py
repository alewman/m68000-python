"""Readability contract for the instruction core, enforced the way correctness is.

The correctness claim is checked mechanically against external oracles.
This module applies the same discipline to the property that makes the code
usable as a reference: every opcode handler must be findable by the name a
68000 programmer would grep for, must live in the module that owns that
instruction, and must say where its rule comes from, so a disagreement can
be settled by opening the cited page or corpus file rather than by trusting
the code.  Everything is derived from the source with :mod:`ast`: no import
of the handlers, no execution.

Five invariants:

1. Every ``_op_*`` method's docstring starts with one Motorola instruction
   name as PRM Sections 4 and 6 title it (``ADD``, ``ANDI to CCR``, ``MOVE
   USP``, ``ASd``), then `` -- `` and a description, and the headline ends
   with its sources in parentheses: a PRM page (``PRM 4-116``), a PRM or UM
   table (``UM Table 8-12: 20 clocks``, ``UM Tables 8-2, 8-3``), a UM
   section (``UM 6.3.6``) or figure, ``;``-separated.  docs/start-here.md
   pins both manuals.
2. The method is named after the instruction: ``_op_`` + the name in lower
   case with spaces as underscores (``_memory`` marks the one-bit memory
   form of a shift).
3. It lives in the module that owns that instruction (``OWNERS``), and no
   handler name is defined twice across the mixins (a duplicate would be
   shadowed by the MRO and never executed).
4. Every instruction has a handler, and every handler the dispatch table
   names exists: there is no fallback.
5. The manuals do not give the stacked PC of an address error, the order of
   bus cycles, the undefined flags of a divide by zero, or the N and V of the
   BCD instructions.  A handler that encodes such a rule, itself or through
   a helper it calls (``_commit_pc``, ``_prefetch_before_write``,
   ``_write_long_low_first``, a store to ``_fault_pc``, ``_divide_by_zero``,
   ``_set_bcd_flags``), names the evidence that pins it in its docstring:
   the SingleStepTests file(s) (``SST MOVE.b/.w/.l``, ``SST ILLEGAL_LINEA``),
   ``WinUAE run`` (docs/referees.md) or ``flamewing`` (the T1 BCD tables).
   When the corpus is fetched, every named file must exist.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from m68000_python._dispatch import NAMES

SRC = Path(__file__).resolve().parents[1] / "src" / "m68000_python"
CORPUS = Path(__file__).resolve().parent / "68000_test_vectors" / "m68000" / "v1"

#: Which module owns which instructions, by the name PRM titles them.
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

#: Headline grammar: ``NAME -- description (sources)``.
_HEADLINE = re.compile(
    r"^(?P<name>[A-Z][A-Za-z]*(?: (?:to|from) (?:CCR|SR)| USP| [AF])?) -- (?P<text>.+)$"
)
#: One source: ``PRM 4-116``, ``PRM Table 3-18``, ``PRM 2.2``, ``UM 6.3.6``,
#: ``UM Figure 6-7``, ``UM Table 8-12`` or ``UM Table 8-12: 20 clocks``,
#: ``UM Tables 8-2, 8-3``.
_SOURCE = (
    r"(?:PRM (?:Table \d+-\d+|\d+-\d+|\d+(?:\.\d+)+)"
    r"|UM (?:Tables? \d+-\d+(?:, \d+-\d+)*(?:: [^;)]+)?|Figure \d+-\d+|\d+(?:\.\d+)+))"
)
#: The headline's closing citation: one or more sources, ``;``-separated.
_CITATION = re.compile(rf"\((?P<sources>{_SOURCE}(?:; {_SOURCE})*)\)\.?$")
#: A corpus-file reference: ``SST ADD.b/.w/.l``, ``SST MOVEfromUSP, MOVEtoUSP``.
_SST_FILES = r"[A-Z][A-Za-z_]*(?:\.[bwlq])?(?:/\.[bwlq])*"
_EVIDENCE = re.compile(
    rf"\bSST (?P<files>{_SST_FILES}(?:, {_SST_FILES})*)|\bWinUAE run\b|\bflamewing\b"
)

#: Helpers that encode a rule only the corpus (or a referee) records.
CORPUS_RULES = frozenset(
    {
        "_commit_pc",
        "_prefetch_before_write",
        "_write_long_low_first",
        "_divide_by_zero",
        "_set_bcd_flags",
    }
)
#: Helpers every instruction ends or exits through; their rules are cited
#: once, in _core.py, and reaching them does not by itself pin a handler.
OPAQUE = frozenset(
    {
        "_prefetch",
        "_jump",
        "_jump_idle",
        "_exception",
        "_group_zero",
        "_not_executed",
        "_privilege_violation",
        "_refill_after_status",
        "_write_status",
        "_write_ccr",
    }
)


class Handler:
    """One ``_op_*`` method as found in the source."""

    def __init__(self, module: str, node: ast.FunctionDef) -> None:
        self.module = module
        self.name = node.name
        self.lineno = node.lineno
        self.docstring = ast.get_docstring(node, clean=True) or ""

    @property
    def location(self) -> str:
        return f"{self.module}:{self.lineno} {self.name}"

    @property
    def headline(self) -> str:
        """The docstring's first paragraph, as one line."""
        return " ".join(self.docstring.split("\n\n", 1)[0].split())

    def parse(self) -> tuple[str, str]:
        """Return ``(instruction name, description)`` from the headline."""
        match = _HEADLINE.match(self.headline)
        assert match, (
            f"{self.location}: docstring must start 'NAME -- description (sources)', "
            f"got {self.headline[:60]!r}"
        )
        return match.group("name"), match.group("text")


def _modules() -> dict[str, ast.Module]:
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in sorted(SRC.glob("_*.py"))
    }


def _handlers() -> list[Handler]:
    found: list[Handler] = []
    for module, tree in _modules().items():
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            found.extend(
                Handler(module, node)
                for node in cls.body
                if isinstance(node, ast.FunctionDef) and node.name.startswith("_op_")
            )
    assert found, f"no _op_* handlers found under {SRC}"
    return found


def _methods() -> dict[str, ast.FunctionDef]:
    """Every method of every mixin, by name (the MRO makes names unique)."""
    methods: dict[str, ast.FunctionDef] = {}
    for tree in _modules().values():
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            for node in cls.body:
                if isinstance(node, ast.FunctionDef):
                    methods[node.name] = node
    return methods


def _pinned_by_corpus() -> set[str]:
    """Methods that encode a corpus-only rule, directly or through the helpers they call.

    Direct: a call to one of ``CORPUS_RULES`` or a store to ``self._fault_pc``.
    Reachability does not pass through ``OPAQUE`` helpers.
    """
    methods = _methods()
    direct: set[str] = set()
    calls: dict[str, set[str]] = {}
    for name, node in methods.items():
        calls[name] = set()
        for inner in ast.walk(node):
            if not (isinstance(inner, ast.Attribute) and isinstance(inner.value, ast.Name)):
                continue
            if inner.value.id != "self":
                continue
            stores_fault_pc = inner.attr == "_fault_pc" and isinstance(inner.ctx, ast.Store)
            if stores_fault_pc or inner.attr in CORPUS_RULES:
                direct.add(name)
            elif inner.attr in methods and inner.attr not in OPAQUE:
                calls[name].add(inner.attr)
    pinned = {name for name in direct if name not in OPAQUE}
    changed = True
    while changed:
        changed = False
        for name, callees in calls.items():
            if name not in pinned and name not in OPAQUE and callees & pinned:
                pinned.add(name)
                changed = True
    return pinned


def _method_name(instruction: str) -> str:
    return "_op_" + instruction.lower().replace(" ", "_")


HANDLERS = _handlers()
PINNED = _pinned_by_corpus()


@pytest.mark.parametrize("handler", HANDLERS, ids=lambda h: f"{h.module}::{h.name}")
def test_handler_headline_names_one_motorola_instruction(handler: Handler) -> None:
    assert handler.docstring, f"{handler.location}: opcode handler has no docstring"
    name, _ = handler.parse()
    assert name in MOTOROLA, f"{handler.location}: {name!r} is not a 68000 instruction name"
    assert handler.name in (_method_name(name), _method_name(name) + "_memory"), (
        f"{handler.location}: a handler for {name} is named {_method_name(name)}"
    )


@pytest.mark.parametrize("handler", HANDLERS, ids=lambda h: f"{h.module}::{h.name}")
def test_handler_headline_cites_its_source(handler: Handler) -> None:
    assert _CITATION.search(handler.headline), (
        f"{handler.location}: the headline must end with its sources in parentheses, "
        f"e.g. (PRM 4-116; UM Table 8-2) or (UM 6.3.6); got {handler.headline!r}"
    )


@pytest.mark.parametrize(
    "handler", [h for h in HANDLERS if h.name in PINNED], ids=lambda h: f"{h.module}::{h.name}"
)
def test_handler_encoding_a_corpus_rule_names_the_evidence(handler: Handler) -> None:
    matches = list(_EVIDENCE.finditer(handler.docstring))
    assert matches, (
        f"{handler.location}: encodes a rule the manuals do not give (a stacked PC, a bus "
        "order, an undefined flag); name what pins it: 'SST <file>[/.w/.l]', 'WinUAE run' "
        "or 'flamewing'"
    )
    if not CORPUS.is_dir():
        return
    for match in matches:
        if not match.group("files"):
            continue
        for reference in match.group("files").split(", "):
            stem, _, sizes = reference.partition(".")
            names = [f"{stem}.{size}" for size in sizes.split("/.")] if sizes else [stem]
            for name in names:
                assert (CORPUS / f"{name}.json.bin").is_file(), (
                    f"{handler.location}: cites SST {name}, which is not a corpus file"
                )


@pytest.mark.parametrize("handler", HANDLERS, ids=lambda h: f"{h.module}::{h.name}")
def test_handler_lives_in_owning_module(handler: Handler) -> None:
    name, _ = handler.parse()
    owned = OWNERS.get(handler.module)
    assert owned is not None, (
        f"{handler.location}: {handler.module} is not a registered owner; add it to OWNERS"
    )
    assert name in owned, f"{handler.location}: {name} is misfiled; it belongs in " + ", ".join(
        module for module, names in OWNERS.items() if name in names
    )


def test_every_instruction_has_a_handler_and_every_table_name_resolves() -> None:
    names = {handler.parse()[0] for handler in HANDLERS}
    assert names == MOTOROLA, (
        f"unclaimed: {sorted(MOTOROLA - names)}; unknown: {sorted(names - MOTOROLA)}"
    )
    methods = {handler.name for handler in HANDLERS}
    assert {"_op_" + name for name in set(NAMES)} <= methods, (
        f"the dispatch table names handlers that do not exist: "
        f"{sorted({'_op_' + n for n in set(NAMES)} - methods)}"
    )


def test_handler_names_are_unique_across_mixins() -> None:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for handler in HANDLERS:
        if handler.name in seen:
            duplicates.append(f"{handler.name} in {seen[handler.name]} and {handler.module}")
        seen[handler.name] = handler.module
    assert not duplicates, "handlers shadowed by the mixin MRO: " + "; ".join(duplicates)


def test_owner_tables_partition_the_vocabulary() -> None:
    claimed: set[str] = set()
    for module, owned in OWNERS.items():
        overlap = claimed & owned
        assert not overlap, f"{module} claims instructions owned elsewhere: {sorted(overlap)}"
        claimed |= owned


def test_the_corpus_rule_helpers_exist() -> None:
    """The reachability rule is only as good as the names it looks for."""
    methods = _methods()
    missing = sorted((CORPUS_RULES | OPAQUE) - set(methods))
    assert not missing, f"CORPUS_RULES/OPAQUE name methods that no longer exist: {missing}"
