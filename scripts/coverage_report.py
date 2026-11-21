"""What the test corpora actually reach, in encodings and in behaviour.

"317,500 cases pass" is a count, not a map.  This script builds the map, in
three views, each a subcommand:

    python scripts/coverage_report.py encodings          # which opcode words run
    python scripts/coverage_report.py paths              # which behaviours run
    python scripts/coverage_report.py lines --limit 200  # which source lines run
    python scripts/coverage_report.py paths --suite      # ... over the whole test suite

``encodings`` is static plus one pass over each corpus file's first words: of
the 45,815 defined opcode words, which are executed as an instruction's own
first word, broken down per handler, per rule of ``_dispatch.RULES``, and per
field of each rule (size, effective address, register numbers, condition,
displacement, ...).  ``paths`` runs every case with a probed subclass of
:class:`M68000CPU` and records which of a declared list of behavioural paths
(exception kinds, supervisor transitions, flag outcomes, operand boundaries,
shift counts, condition-code inputs) each corpus reaches.  ``lines`` traces
execution of ``src/m68000_python`` and reports the source lines no case runs.

Nothing here changes the core or any gate: it only measures them.  The
findings, and the gaps that follow from them, are written up in
docs/coverage.md.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from corpus import read_680x0, read_m68000  # noqa: E402

from m68000_python._dispatch import COMPILED, NAMES, RULES  # noqa: E402
from m68000_python._ea import EA_KIND, KIND_NAMES  # noqa: E402

M68000_VECTORS = ROOT / "tests" / "68000_test_vectors" / "m68000" / "v1"
HARTE_VECTORS = ROOT / "tests" / "68000_test_vectors" / "680x0" / "68000" / "v1"

UNDEFINED = ("illegal", "line_a", "line_f")

# -- which rule each opcode word comes from -----------------------------------


def _rule_of(opcode: int) -> int | None:
    """Index into :data:`RULES` of the rule this word matches, or None."""
    for index, (mask, value, _name, check) in enumerate(COMPILED):
        if opcode & mask == value and check(opcode):
            return index
    return None


#: RULE_INDEX[opcode] is the rule that defines it, or None (illegal / line A/F).
RULE_INDEX: tuple[int | None, ...] = tuple(_rule_of(opcode) for opcode in range(0x10000))

#: Letter and width of a pattern field -> the name the manuals use for it.
FIELD_NAMES = {
    ("e", 6): "ea",
    ("s", 2): "size",
    ("s", 1): "size/direction bit",
    ("r", 3): "register",
    ("a", 3): "An",
    ("R", 3): "destination register",
    ("M", 3): "destination mode",
    ("q", 3): "quick data",
    ("v", 4): "vector",
    ("c", 4): "condition",
    ("c", 3): "count or Dx",
    ("d", 8): "displacement",
    ("d", 1): "direction",
    ("o", 2): "opmode",
    ("m", 1): "R/M",
    ("x", 3): "Rx",
    ("y", 3): "Ry",
    ("i", 1): "count source",
}


def fields_of(pattern: str) -> dict[str, list[int]]:
    """Letter -> the bit numbers (15..0) it occupies, in pattern order."""
    bits = pattern.replace(" ", "")
    found: dict[str, list[int]] = {}
    for position, character in enumerate(bits):
        if character not in "01":
            found.setdefault(character, []).append(15 - position)
    return found


def field_value(opcode: int, bit_numbers: list[int]) -> int:
    value = 0
    for bit in bit_numbers:
        value = (value << 1) | ((opcode >> bit) & 1)
    return value


def field_label(letter: str, bit_numbers: list[int]) -> str:
    name = FIELD_NAMES.get((letter, len(bit_numbers)), letter)
    return f"{name} ({letter}{len(bit_numbers)})"


# -- reading the corpora ------------------------------------------------------


def corpus_first_words(which: str) -> tuple[Counter, int, int]:
    """(first word -> case count, cases, files) for one corpus.

    The first word of a case is ``initial.prefetch[0]``: IR, the opcode the
    step executes.  Extension words and any word a case happens to leave in
    memory are not counted -- only what is executed as an instruction.
    """
    counts: Counter = Counter()
    cases = files = 0
    for path in sorted(directory_of(which).glob(pattern_of(which))):
        files += 1
        for case in reader_of(which)(path):
            counts[case.initial.prefetch[0]] += 1
            cases += 1
    return counts, cases, files


def directory_of(which: str) -> Path:
    return M68000_VECTORS if which == "m68000" else HARTE_VECTORS


def pattern_of(which: str) -> str:
    return "*.json.bin" if which == "m68000" else "*.json.gz"


def reader_of(which: str):
    return read_m68000 if which == "m68000" else read_680x0


# -- the encoding report ------------------------------------------------------


def suite_first_words() -> Counter:
    """First word -> times executed, over the whole committed test suite.

    Every dispatch-table entry of the real class is wrapped to count the
    opcode it is called with, then ``pytest tests`` runs: the corpus gate and
    every hand-written test.  Only instructions count, as in the corpus view.
    """
    import pytest

    from m68000_python._dispatch import build_table
    from m68000_python.cpu import M68000CPU

    counts: Counter = Counter()

    def recording(handler):
        def run(cpu, opcode):
            counts[opcode] += 1
            return handler(cpu, opcode)

        return run

    M68000CPU._table = [recording(handler) for handler in build_table(M68000CPU)]
    pytest.main(["-q", "-p", "no:cacheprovider", str(ROOT / "tests")])
    return counts


def report_encodings(which: str, out, suite: bool = False) -> None:
    if suite:
        counts = suite_first_words()
        heading = "the whole test suite (python -m pytest tests)"
        scope = "every test module, the 127-file corpus gate included"
    else:
        counts, cases, files = corpus_first_words(which)
        heading = f"SingleStepTests/{which}"
        scope = f"{files} files, {cases:,} cases"
    defined = [opcode for opcode in range(0x10000) if NAMES[opcode] not in UNDEFINED]
    executed = {opcode for opcode in counts if NAMES[opcode] not in UNDEFINED}
    undefined_executed = {opcode for opcode in counts if NAMES[opcode] in UNDEFINED}

    print(f"# Encoding coverage: {heading}", file=out)
    print(f"\n{scope}.\n", file=out)
    print(f"defined opcode words              {len(defined):,}", file=out)
    print(f"  executed as a first word        {len(executed):,}", file=out)
    print(f"  never executed                  {len(defined) - len(executed):,}", file=out)
    print(f"undefined words executed          {len(undefined_executed):,}", file=out)
    print(f"  (illegal / line A / line F, of {65536 - len(defined):,})", file=out)

    # Per handler.
    by_handler_defined: Counter = Counter()
    by_handler_executed: Counter = Counter()
    for opcode in defined:
        by_handler_defined[NAMES[opcode]] += 1
        if opcode in executed:
            by_handler_executed[NAMES[opcode]] += 1
    print("\n## Per handler\n", file=out)
    print(f"{'handler':16} {'defined':>8} {'run':>8} {'unrun':>8}  {'%':>5}", file=out)

    def unrun(handler: str) -> int:
        return by_handler_executed[handler] - by_handler_defined[handler]

    for handler in sorted(by_handler_defined, key=unrun):
        total = by_handler_defined[handler]
        run = by_handler_executed[handler]
        print(
            f"{handler:16} {total:8,} {run:8,} {total - run:8,}  {100 * run / total:5.1f}",
            file=out,
        )

    if which == "m68000" and not suite:
        report_transfer(executed, [op for op in defined if op not in executed], out)

    # Per rule, with every field broken out.
    print("\n## Per rule and field\n", file=out)
    print(
        "Each rule of _dispatch.RULES with the values of each of its fields that\n"
        "no case executes.  A field value is 'run' when at least one executed\n"
        "word carries it; 'unrun' values are listed in full where there are few.\n",
        file=out,
    )
    for index, (pattern, handler, _check) in enumerate(RULES):
        words = [opcode for opcode in defined if RULE_INDEX[opcode] == index]
        if not words:
            continue
        run = [opcode for opcode in words if opcode in executed]
        print(f"### {handler}  `{pattern}`", file=out)
        print(
            f"    words {len(words):,}  run {len(run):,}  unrun {len(words) - len(run):,}", file=out
        )
        for letter, bit_numbers in fields_of(pattern).items():
            seen = {field_value(opcode, bit_numbers) for opcode in run}
            possible = {field_value(opcode, bit_numbers) for opcode in words}
            missing = sorted(possible - seen)
            label = field_label(letter, bit_numbers)
            if letter == "e":
                print(f"    {label}: {ea_summary(possible, seen)}", file=out)
                continue
            if not missing:
                print(f"    {label}: all {len(possible)} values run", file=out)
            else:
                shown = ", ".join(str(value) for value in missing[:32])
                more = "" if len(missing) <= 32 else f", ... ({len(missing)} in all)"
                print(
                    f"    {label}: {len(seen)}/{len(possible)} run; missing {shown}{more}", file=out
                )
        for line in combinations(pattern, words, set(run)):
            print(f"    {line}", file=out)
        print(file=out)


def report_transfer(executed: set[int], unrun: list[int], out) -> None:
    """For the words the gate never runs: what evidence in the suite reaches each.

    The renaming relations and the manual-derived tests are in
    tests/test_register_renaming.py and tests/test_coverage_gaps.py; a word
    whose renamed twin the gate *does* run inherits the gate's evidence
    through a symmetry the manual states (PRM 2.2).
    """
    from test_coverage_gaps import LAST_WORDS
    from test_register_renaming import PLAIN, canonical_twin, seven_to_zero_twin

    direct = {"bcc", "bra", "moveq"}  # every word run by test_coverage_gaps.py
    twins_of_others = set()
    for opcode in range(0x10000):
        if NAMES[opcode] not in UNDEFINED and NAMES[opcode] != "movem":
            twin = canonical_twin(opcode)[0]
            if twin == opcode and NAMES[opcode] in PLAIN:
                twin = seven_to_zero_twin(opcode)[0]
            if twin != opcode:
                twins_of_others.add(twin)
    tally: Counter = Counter()
    for opcode in unrun:
        name = NAMES[opcode]
        if name in direct:
            tally["every word of its family run by a manual-derived test"] += 1
            continue
        if opcode in LAST_WORDS:
            tally["checked against the PRM 2.2 effective-address model"] += 1
            continue
        twin = opcode
        if name != "movem":
            twin = canonical_twin(opcode)[0]
            if twin == opcode and name in PLAIN:
                twin = seven_to_zero_twin(opcode)[0]
        if twin == opcode and opcode in twins_of_others:
            tally["its own twin, compared as the twin of other words"] += 1
        elif twin == opcode:
            tally["no renamed twin: run by the direct manual-derived tests"] += 1
        elif twin in executed:
            tally["renamed twin run by the gate: the gate's evidence transfers"] += 1
        else:
            tally["renamed twin not run by the gate: symmetry only"] += 1
    print("\n## The words the gate never runs, by the evidence that now reaches them\n", file=out)
    for key, count in tally.most_common():
        print(f"{count:6,}  {key}", file=out)


def combinations(pattern: str, words: list[int], run: set[int]) -> list[str]:
    """Unrun combinations of the categorical axes of one rule.

    A field-by-field report hides the interesting gap: every size and every
    addressing mode may be sampled somewhere and still leave whole (size,
    mode) pairs -- or, for MOVE, (size, source mode, destination mode)
    triples -- unrun.  Those pairs are what a family's tests are organised by,
    so they are reported by name.
    """
    fields = fields_of(pattern)
    axes: list[tuple[str, callable]] = []
    if "s" in fields and len(fields["s"]) == 2:
        bits = fields["s"]
        axes.append(("size", lambda opcode, bits=bits: "bwl?"[field_value(opcode, bits)]))
    if "e" in fields:
        bits = fields["e"]
        axes.append(("ea", lambda opcode, bits=bits: kind_name(field_value(opcode, bits))))
    if "M" in fields and "R" in fields:
        mbits, rbits = fields["M"], fields["R"]
        axes.append(
            (
                "destination",
                lambda opcode, m=mbits, r=rbits: kind_name(
                    (field_value(opcode, m) << 3) | field_value(opcode, r)
                ),
            )
        )
        axes.append(("size", lambda opcode: {1: "b", 3: "w", 2: "l"}[opcode >> 12]))
    if not axes:
        return []

    def key(opcode: int) -> tuple:
        return tuple(axis(opcode) for _name, axis in axes)

    possible = {key(opcode) for opcode in words}
    seen = {key(opcode) for opcode in words if opcode in run}
    missing = sorted(possible - seen)
    names = " x ".join(name for name, _ in axes)
    if not missing:
        return [f"combinations ({names}): all {len(possible)} run"]
    return [
        f"combinations ({names}): {len(seen)}/{len(possible)} run; unrun:",
        *[f"    {' '.join(combination)}" for combination in missing],
    ]


def kind_name(field: int) -> str:
    kind = EA_KIND[field]
    return "invalid" if kind is None else KIND_NAMES[kind]


def ea_summary(possible: set[int], seen: set[int]) -> str:
    """EA field coverage as the twelve modes of PRM 2.2, not 64 raw values."""
    kinds_possible: dict[int, set[int]] = defaultdict(set)
    kinds_seen: dict[int, set[int]] = defaultdict(set)
    for value in possible:
        kind = EA_KIND[value]
        if kind is not None:
            kinds_possible[kind].add(value)
    for value in seen:
        kind = EA_KIND[value]
        if kind is not None:
            kinds_seen[kind].add(value)
    parts = []
    for kind in sorted(kinds_possible):
        total = len(kinds_possible[kind])
        run = len(kinds_seen.get(kind, ()))
        mark = "" if run == total else f" ({run}/{total})" if run else " NONE"
        parts.append(f"{KIND_NAMES[kind]}{mark}")
    return ", ".join(parts)


# -- behavioural paths --------------------------------------------------------
# The declared universe: every path the report looks for.  A path that no
# corpus case reaches is a gap, listed as such rather than assumed covered.

PATHS: tuple[tuple[str, str, str], ...] = (
    # (category, identifier, what it means)
    ("exception", "exception:2", "bus error (host raised BusError)"),
    ("exception", "exception:3", "address error"),
    ("exception", "exception:4", "illegal instruction"),
    ("exception", "exception:5", "divide by zero"),
    ("exception", "exception:6", "CHK"),
    ("exception", "exception:7", "TRAPV taken"),
    ("exception", "exception:8", "privilege violation"),
    ("exception", "exception:9", "trace"),
    ("exception", "exception:10", "line 1010 emulator"),
    ("exception", "exception:11", "line 1111 emulator"),
    *(("exception", f"exception:{32 + n}", f"TRAP #{n}") for n in range(16)),
    ("exception", "double-fault", "a group 0 fault while taking a group 0 exception"),
    ("address error", "group0:read:data", "address error on a data read"),
    ("address error", "group0:read:program", "address error on a program read"),
    ("address error", "group0:write:data", "address error on a data write"),
    (
        "address error",
        "group0:write:program",
        "address error on a program write (UNREACHABLE: the 68000 never writes to program space)",
    ),
    ("address error", "group0:in-instruction", "the aborted access belonged to an instruction"),
    (
        "address error",
        "group0:in-exception",
        "the aborted access belonged to exception processing (I/N set)",
    ),
    ("address error", "group0:user", "address error taken in user mode"),
    ("address error", "group0:supervisor", "address error taken in supervisor mode"),
    ("mode", "mode:supervisor", "an instruction executed with S set"),
    ("mode", "mode:user", "an instruction executed with S clear"),
    ("mode", "s:0->1", "S changed from user to supervisor"),
    ("mode", "s:1->0", "S changed from supervisor to user"),
    ("mode", "sp:swapped", "A7 exchanged with the other stack pointer"),
    ("mode", "privilege:andi_to_sr", "ANDI to SR in user mode"),
    ("mode", "privilege:eori_to_sr", "EORI to SR in user mode"),
    ("mode", "privilege:ori_to_sr", "ORI to SR in user mode"),
    ("mode", "privilege:move_to_sr", "MOVE to SR in user mode"),
    ("mode", "privilege:move_usp", "MOVE USP in user mode"),
    ("mode", "privilege:rte", "RTE in user mode"),
    ("mode", "privilege:reset", "RESET in user mode"),
    ("mode", "privilege:stop", "STOP in user mode"),
    ("interrupt", "interrupt:level", "an interrupt was accepted"),
    ("interrupt", "ack:autovector", "the acknowledge asked for the autovector"),
    ("interrupt", "ack:vector", "the acknowledge named a vector"),
    ("interrupt", "ack:spurious", "the acknowledge reported spurious"),
    ("interrupt", "ack:out-of-range", "the acknowledge answered outside 0-255"),
    ("interrupt", "nmi:edge", "a level 7 edge taken through the mask"),
    ("interrupt", "trace-before-interrupt", "trace taken while an interrupt was pending"),
    ("state", "stop:entered", "STOP executed"),
    ("state", "stop:idle", "a step of a stopped CPU"),
    ("state", "reset:instruction", "the RESET instruction"),
    ("state", "reset:pin", "M68000CPU.reset()"),
    ("state", "halted", "the CPU halted"),
    ("state", "trace:pending", "an instruction completed with T set"),
    ("branch", "trapv:taken", "TRAPV with V set"),
    ("branch", "trapv:not-taken", "TRAPV with V clear"),
    ("branch", "chk:above-bound", "CHK with Dn > bound"),
    ("branch", "chk:negative", "CHK with Dn < 0 and within the bound"),
    (
        "branch",
        "chk:negative:idle8",
        "CHK negative, bound - Dn negative in 16 bits (8 idle clocks)",
    ),
    ("branch", "chk:negative:idle10", "CHK negative, bound - Dn positive (10 idle clocks)"),
    ("branch", "chk:in-range", "CHK with Dn in range"),
    ("branch", "divu:zero", "DIVU by zero"),
    ("branch", "divs:zero", "DIVS by zero"),
    ("branch", "divu:overflow", "DIVU quotient over 16 bits"),
    ("branch", "divs:overflow", "DIVS quotient outside -32768..32767"),
    ("branch", "divu:normal", "DIVU with a representable quotient"),
    ("branch", "divs:normal", "DIVS with a representable quotient"),
    ("branch", "divs:negative-dividend", "DIVS with a negative dividend"),
    ("branch", "divs:negative-divisor", "DIVS with a negative divisor"),
    ("branch", "divu:overflow-boundary", "DIVU with dividend >> 16 exactly equal to the divisor"),
    ("branch", "mulu:source-zero", "MULU by zero"),
    ("branch", "mulu:source-ones", "MULU by $FFFF"),
    ("branch", "muls:source-min", "MULS by $8000"),
    ("branch", "muls:both-negative", "MULS with both operands negative"),
    ("branch", "dbcc:condition-true", "DBcc with the condition true"),
    ("branch", "dbcc:expired", "DBcc counting down to -1"),
    ("branch", "dbcc:branch", "DBcc branching"),
    ("branch", "bcc:taken", "Bcc taken"),
    ("branch", "bcc:not-taken", "Bcc not taken"),
    ("branch", "bcc:16-bit", "Bcc/BRA/BSR with a 16-bit displacement"),
    ("branch", "movem:zero-mask", "MOVEM with an empty register list"),
    ("branch", "movem:all", "MOVEM with all sixteen registers"),
    ("branch", "movem:an-in-list", "MOVEM -(An) with An itself in the list"),
)

SHIFT_KINDS = ("as", "ls", "rox", "ro")


class Probe:
    """Somewhere to record what the run reached."""

    def __init__(self) -> None:
        self.hits: Counter = Counter()
        #: (operation, size) -> set of (N, Z, V, C, X) outcomes.
        self.flag_outcomes: dict[tuple[str, int], set[tuple]] = defaultdict(set)
        #: (operation, size) -> set of (destination class, source class).
        self.operands: dict[tuple[str, int], set[tuple[str, str]]] = defaultdict(set)
        #: (shift kind, direction, size) -> set of counts.
        self.shift_counts: dict[tuple[str, str, int], set[int]] = defaultdict(set)
        #: family -> set of (condition, CCR low nibble).
        self.conditions: dict[str, set[tuple[int, int]]] = defaultdict(set)

    def hit(self, path: str) -> None:
        self.hits[path] += 1


def operand_class(value: int, size: int) -> str:
    """Where an operand sits among the boundaries a flag rule can turn on."""
    mask = (1 << (8 * size)) - 1
    value &= mask
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    if value == mask:
        return "all ones"
    if value == mask >> 1:
        return "max positive"
    if value == (mask >> 1) + 1:
        return "min negative"
    return "other"


def probed_class(probe: Probe):
    """A subclass of the core that records paths; the core itself is untouched."""
    from m68000_python import M68000CPU
    from m68000_python._core import AUTOVECTOR, SPURIOUS, S, V
    from m68000_python._ea import EA_KIND, sign_extend_16

    class ProbedCPU(M68000CPU):
        #: The last value :meth:`_ea_read` returned, for probes that need the source.
        _last_source = 0

        # -- exception entry ------------------------------------------------
        def _exception(self, vector, pc, *, idle=4, saved=None):
            probe.hit(f"exception:{vector}")
            if vector == 6:
                probe.hit(f"chk:negative:idle{idle}" if idle in (8, 10) else "chk:other-idle")
            return super()._exception(vector, pc, idle=idle, saved=saved)

        def _group_zero(self, fault):
            probe.hit(f"exception:{fault.vector}")
            probe.hit(
                f"group0:{'write' if fault.write else 'read'}:"
                f"{'program' if fault.program else 'data'}"
            )
            probe.hit(
                "group0:in-exception" if self._processing_exception else "group0:in-instruction"
            )
            probe.hit("group0:supervisor" if self.SR & S else "group0:user")
            was_halted = self.halted
            result = super()._group_zero(fault)
            if self.halted and not was_halted:
                probe.hit("double-fault")
                probe.hit("halted")
            return result

        def _privilege_violation(self):
            probe.hit(f"privilege:{self._handler_name()}")
            return super()._privilege_violation()

        def _handler_name(self) -> str:
            return NAMES[self._opcode]

        # -- mode and the stack pointers ------------------------------------
        def _set_sr(self, value):
            before = self.SR & S
            after = value & S
            if before != after:
                probe.hit("s:1->0" if before else "s:0->1")
                probe.hit("sp:swapped")
            return super()._set_sr(value)

        # -- interrupts, STOP, RESET ----------------------------------------
        def _interrupt(self, level):
            probe.hit("interrupt:level")
            probe.hit(f"interrupt:level{level}")
            if level == 7 and self._nmi_edge:
                probe.hit("nmi:edge")
            host = self._acknowledge

            def acknowledge(requested):
                # The core's own default when the host gave no callable.
                answer = AUTOVECTOR if host is None else host(requested)
                if answer == AUTOVECTOR:
                    probe.hit("ack:autovector")
                elif answer == SPURIOUS:
                    probe.hit("ack:spurious")
                elif 0 <= answer <= 255:
                    probe.hit("ack:vector")
                else:
                    probe.hit("ack:out-of-range")
                return answer

            self._acknowledge = acknowledge
            try:
                return super()._interrupt(level)
            finally:
                self._acknowledge = host

        def _op_stop(self, opcode):
            if self.SR & S:
                probe.hit("stop:entered")
            return super()._op_stop(opcode)

        def _op_reset(self, opcode):
            if self.SR & S:
                probe.hit("reset:instruction")
            return super()._op_reset(opcode)

        def reset(self):
            probe.hit("reset:pin")
            return super().reset()

        def step(self):
            probe.hit("mode:supervisor" if self.SR & S else "mode:user")
            if self.stopped and not self._trace_pending and not self.ipl:
                probe.hit("stop:idle")
            if self._trace_pending and self.ipl:
                probe.hit("trace-before-interrupt")
            clocks = super().step()
            if self._trace_pending:
                probe.hit("trace:pending")
            if self.halted:
                probe.hit("halted")
            return clocks

        # -- flag rules and operand boundaries -------------------------------
        def _record_flags(self, name, size):
            sr = self.SR
            probe.flag_outcomes[(name, size)].add(
                (bool(sr & 8), bool(sr & 4), bool(sr & 2), bool(sr & 1), bool(sr & 16))
            )

        def _flags_add(self, destination, source, result, size):
            super()._flags_add(destination, source, result, size)
            self._record_flags("add", size)

        def _flags_sub(self, destination, source, result, size):
            super()._flags_sub(destination, source, result, size)
            self._record_flags("sub", size)

        def _flags_cmp(self, destination, source, result, size):
            super()._flags_cmp(destination, source, result, size)
            self._record_flags("cmp", size)

        def _flags_addx(self, destination, source, result, size):
            super()._flags_addx(destination, source, result, size)
            self._record_flags("addx", size)

        def _flags_subx(self, destination, source, result, size):
            super()._flags_subx(destination, source, result, size)
            self._record_flags("subx", size)

        def _flags_logic(self, result, size):
            super()._flags_logic(result, size)
            self._record_flags("logic", size)

        def _add(self, destination, source, size):
            probe.operands[("add", size)].add(
                (operand_class(destination, size), operand_class(source, size))
            )
            return super()._add(destination, source, size)

        def _sub(self, destination, source, size):
            probe.operands[("sub", size)].add(
                (operand_class(destination, size), operand_class(source, size))
            )
            return super()._sub(destination, source, size)

        def _addx(self, destination, source, size):
            probe.operands[("addx", size)].add(
                (operand_class(destination, size), operand_class(source, size))
            )
            return super()._addx(destination, source, size)

        def _subx(self, destination, source, size):
            probe.operands[("subx", size)].add(
                (operand_class(destination, size), operand_class(source, size))
            )
            return super()._subx(destination, source, size)

        # -- per-instruction branches ----------------------------------------
        def _op_trapv(self, opcode):
            probe.hit("trapv:taken" if self.SR & V else "trapv:not-taken")
            return super()._op_trapv(opcode)

        def _op_chk(self, opcode):
            negative = sign_extend_16(self.R[(opcode >> 9) & 7]) < 0
            trapped = probe.hits["exception:6"]
            result = super()._op_chk(opcode)
            if probe.hits["exception:6"] == trapped:
                probe.hit("chk:in-range")
            elif negative:
                probe.hit("chk:negative")
            else:
                probe.hit("chk:above-bound")
            return result

        def _divide_by_zero(self, signed, dividend):
            probe.hit("divs:zero" if signed else "divu:zero")
            return super()._divide_by_zero(signed, dividend)

        def _op_divu(self, opcode):
            by_zero = probe.hits["divu:zero"]
            dividend = self.R[(opcode >> 9) & 7]
            result = super()._op_divu(opcode)
            if probe.hits["divu:zero"] != by_zero:
                return result
            probe.hit("divu:overflow" if self.SR & V else "divu:normal")
            if self._last_source and (dividend >> 16) == self._last_source:
                probe.hit("divu:overflow-boundary")
            return result

        def _op_mulu(self, opcode):
            result = super()._op_mulu(opcode)
            if self._last_source == 0:
                probe.hit("mulu:source-zero")
            if self._last_source == 0xFFFF:
                probe.hit("mulu:source-ones")
            return result

        def _op_muls(self, opcode):
            before = self.R[(opcode >> 9) & 7]
            result = super()._op_muls(opcode)
            if self._last_source == 0x8000:
                probe.hit("muls:source-min")
            if self._last_source & 0x8000 and before & 0x8000:
                probe.hit("muls:both-negative")
            return result

        def _ea_read(self, kind, register, size):
            value = super()._ea_read(kind, register, size)
            self._last_source = value
            return value

        def _op_divs(self, opcode):
            dn = (opcode >> 9) & 7
            if self.R[dn] & 0x80000000:
                probe.hit("divs:negative-dividend")
            by_zero = probe.hits["divs:zero"]
            result = super()._op_divs(opcode)
            if getattr(self, "_last_source", 0) & 0x8000:
                probe.hit("divs:negative-divisor")
            if probe.hits["divs:zero"] != by_zero:
                return result
            probe.hit("divs:overflow" if self.SR & V else "divs:normal")
            return result

        def _op_dbcc(self, opcode):
            from m68000_python._flags import CONDITION

            condition = (opcode >> 8) & 0xF
            probe.conditions["dbcc"].add((condition, self.SR & 0xF))
            if CONDITION[condition][self.SR & 0xF]:
                probe.hit("dbcc:condition-true")
            else:
                count = (self.R[opcode & 7] - 1) & 0xFFFF
                probe.hit("dbcc:expired" if count == 0xFFFF else "dbcc:branch")
            return super()._op_dbcc(opcode)

        def _op_scc(self, opcode):
            probe.conditions["scc"].add(((opcode >> 8) & 0xF, self.SR & 0xF))
            return super()._op_scc(opcode)

        def _op_bcc(self, opcode):
            from m68000_python._flags import CONDITION

            condition = (opcode >> 8) & 0xF
            probe.conditions["bcc"].add((condition, self.SR & 0xF))
            probe.hit("bcc:taken" if CONDITION[condition][self.SR & 0xF] else "bcc:not-taken")
            if not opcode & 0xFF:
                probe.hit("bcc:16-bit")
            return super()._op_bcc(opcode)

        def _op_bra(self, opcode):
            if not opcode & 0xFF:
                probe.hit("bcc:16-bit")
            return super()._op_bra(opcode)

        def _op_bsr(self, opcode):
            if not opcode & 0xFF:
                probe.hit("bcc:16-bit")
            return super()._op_bsr(opcode)

        def _op_movem(self, opcode):
            mask = self.irc
            if mask == 0:
                probe.hit("movem:zero-mask")
            if mask == 0xFFFF:
                probe.hit("movem:all")
            predec_store = EA_KIND[opcode & 0x3F] == 4 and not opcode & 0x0400
            if predec_store and mask & (1 << (15 - (8 + (opcode & 7)))):
                probe.hit("movem:an-in-list")
            return super()._op_movem(opcode)

        def _shift_register(self, opcode, kind):
            size = (1, 2, 4, 0)[(opcode >> 6) & 3]
            if opcode & 0x20:
                count = self.R[(opcode >> 9) & 7] & 63
            else:
                count = (8, 1, 2, 3, 4, 5, 6, 7)[(opcode >> 9) & 7]
            direction = "left" if opcode & 0x0100 else "right"
            probe.shift_counts[(kind, direction, size)].add(count)
            return super()._shift_register(opcode, kind)

        def _shift_memory(self, opcode, kind):
            direction = "left" if opcode & 0x0100 else "right"
            probe.shift_counts[(kind, direction, 2)].add(1)
            return super()._shift_memory(opcode, kind)

    return ProbedCPU


def host_module(which: str):
    """The harness module whose host matches the corpus's RAM convention.

    The m68000 corpus's RAM is 16-bit words at even addresses, the 680x0
    corpus's is bytes (docs/validation.md); each has its own host, and a
    case run through the other's would read the wrong memory.
    """
    if which == "m68000":
        import harness

        return harness, lambda case: harness.run_case(case, compare_transactions=False)
    import harness_680x0

    return harness_680x0, harness_680x0.run_case_680x0


def run_paths(which: str, probe: Probe, limit: int | None) -> tuple[int, int]:
    """Run every case of one corpus through the probed core; return (cases, files)."""
    module, run = host_module(which)
    original = module.M68000CPU
    module.M68000CPU = probed_class(probe)
    try:
        cases = files = 0
        for path in sorted(directory_of(which).glob(pattern_of(which))):
            files += 1
            for index, case in enumerate(reader_of(which)(path)):
                if limit is not None and index >= limit:
                    break
                # A crash is still a path the corpus reached.
                with contextlib.suppress(Exception):
                    run(case)
                cases += 1
        return cases, files
    finally:
        module.M68000CPU = original


def run_paths_suite(probe: Probe) -> str:
    """Run the whole suite with every ``M68000CPU`` replaced by the probed subclass.

    test_readability.py is left out: it inspects the class's own handlers,
    and the probe's overrides are not handlers.  Test outcomes are not the
    point here (a probe override can upset a test that checks identity);
    only which paths ran is recorded.
    """
    import pytest

    import m68000_python
    import m68000_python.cpu

    probed = probed_class(probe)
    m68000_python.M68000CPU = probed
    m68000_python.cpu.M68000CPU = probed
    pytest.main(
        [
            "-q",
            "-p",
            "no:cacheprovider",
            str(ROOT / "tests"),
            "--ignore",
            str(ROOT / "tests" / "test_readability.py"),
        ]
    )
    return "the whole test suite but test_readability.py (python -m pytest tests)"


def report_paths(which: str, probe: Probe, cases: int, files: int, out, what: str = "") -> None:
    heading = what or f"SingleStepTests/{which}"
    print(f"# Behavioural path coverage: {heading}", file=out)
    if not what:
        print(f"\n{files} files, {cases:,} cases run through a probed subclass.\n", file=out)
    else:
        print("\nEvery CPU the suite builds is the probed subclass.\n", file=out)
    by_category: dict[str, list] = defaultdict(list)
    for category, identifier, description in PATHS:
        by_category[category].append((identifier, description))
    for category, entries in by_category.items():
        print(f"## {category}\n", file=out)
        for identifier, description in entries:
            count = probe.hits.get(identifier, 0)
            mark = f"{count:>12,}" if count else "        NEVER"
            print(f"{mark}  {identifier:28} {description}", file=out)
        print(file=out)

    print("## Flag outcomes reached (N Z V C X)\n", file=out)
    print(
        "The denominator is the set of outcomes the rule can produce at all,\n"
        "found by running the rule over every byte operand pair and both X\n"
        "values (achievable_flag_outcomes): 32 is never the right denominator,\n"
        "because X always follows C for the arithmetic rules and N and Z cannot\n"
        "both be set.  The denominator is the core's own rule, so it measures\n"
        "the corpus, not the rule.\n",
        file=out,
    )
    universes = achievable_flag_outcomes()
    for (name, size), outcomes in sorted(probe.flag_outcomes.items()):
        universe = universes[name]
        missing = sorted(universe - outcomes)
        print(
            f"{name} size {size}: {len(outcomes & universe)}/{len(universe)} outcomes"
            f"; missing {', '.join(show_flags(f) for f in missing) if missing else 'none'}",
            file=out,
        )
    print(file=out)

    print("## Operand boundary classes reached (destination x source)\n", file=out)
    classes = ("0", "1", "all ones", "max positive", "min negative", "other")
    for (name, size), pairs in sorted(probe.operands.items()):
        reached = [f"{d} x {s}" for d in classes for s in classes if (d, s) in pairs]
        print(f"{name} size {size}: {len(pairs)}/36 pairs reached: {'; '.join(reached)}", file=out)
    print(file=out)

    print("## Shift and rotate counts reached\n", file=out)
    for key, counts in sorted(probe.shift_counts.items()):
        kind, direction, size = key
        bits = 8 * size
        missing = sorted(set(range(64)) - counts)
        over = sorted(count for count in counts if count >= bits)
        print(
            f"{kind} {direction} size {size}: {len(counts)}/64 counts; "
            f"counts >= width: {len(over)}; missing "
            f"{compress(missing) if missing else 'none'}",
            file=out,
        )
    print(file=out)

    print("## Condition-code inputs reached (condition x CCR nibble)\n", file=out)
    # Bcc's field cannot hold 0 or 1: those words are BRA and BSR.
    universe = {"bcc": range(2, 16)}
    for family, pairs in sorted(probe.conditions.items()):
        conditions = universe.get(family, range(16))
        missing = [(c, n) for c in conditions for n in range(16) if (c, n) not in pairs]
        total = 16 * len(conditions)
        print(f"{family}: {total - len(missing)}/{total} pairs; missing {len(missing)}", file=out)
        if missing and len(missing) <= 64:
            print(f"    {', '.join(f'{c}/{n:x}' for c, n in missing)}", file=out)
    print(file=out)


def show_flags(outcome: tuple) -> str:
    return "".join(letter if bit else "-" for letter, bit in zip("NZVCX", outcome, strict=True))


def achievable_flag_outcomes() -> dict[str, set[tuple]]:
    """Which (N, Z, V, C, X) each flag rule can produce, over all byte operands.

    A denominator, not an oracle: it is the core's own rule enumerated, so a
    missing outcome means the corpus never asked for it, not that the rule is
    right.  Byte operands are enough: the rules are width-parameterised.
    """
    from m68000_python._flags import FlagsMixin

    class Dummy(FlagsMixin):
        SR = 0

    dummy = Dummy()
    found: dict[str, set[tuple]] = defaultdict(set)

    def record(name: str) -> None:
        sr = dummy.SR
        found[name].add((bool(sr & 8), bool(sr & 4), bool(sr & 2), bool(sr & 1), bool(sr & 16)))

    for x in (0, 16):
        for destination in range(256):
            dummy.SR = x
            dummy._flags_logic(destination, 1)
            record("logic")
            for source in range(256):
                dummy.SR = x
                dummy._flags_add(destination, source, destination + source, 1)
                record("add")
                dummy.SR = x
                dummy._flags_sub(destination, source, destination - source, 1)
                record("sub")
                dummy.SR = x
                dummy._flags_cmp(destination, source, destination - source, 1)
                record("cmp")
                carry = 1 if x else 0
                dummy.SR = x | 4  # Z set: the sticky rules can only clear it
                dummy._flags_addx(destination, source, destination + source + carry, 1)
                record("addx")
                dummy.SR = x | 4
                dummy._flags_subx(destination, source, destination - source - carry, 1)
                record("subx")
                dummy.SR = x  # Z clear: the other half of the sticky rule
                dummy._flags_addx(destination, source, destination + source + carry, 1)
                record("addx")
                dummy.SR = x
                dummy._flags_subx(destination, source, destination - source - carry, 1)
                record("subx")
    return found


def compress(values: list[int]) -> str:
    """[0,1,2,5] -> '0-2, 5'."""
    if not values:
        return ""
    runs = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        runs.append((start, previous))
        start = previous = value
    runs.append((start, previous))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


# -- source-line coverage -----------------------------------------------------


def run_lines(which: str, limit: int | None, suite: bool) -> tuple[dict[str, set[int]], str]:
    """Trace the core's own source lines while running the corpus, or the whole suite."""
    _, run = host_module(which)
    package = str(ROOT / "src" / "m68000_python")
    seen: dict[str, set[int]] = defaultdict(set)

    def local(frame, event, arg):
        if event == "line":
            seen[frame.f_code.co_filename].add(frame.f_lineno)
        return local

    def entry(frame, event, arg):
        if event == "call" and frame.f_code.co_filename.startswith(package):
            seen[frame.f_code.co_filename].add(frame.f_lineno)
            return local
        return None

    cases = 0
    sys.settrace(entry)
    try:
        if suite:
            import pytest

            pytest.main(["-q", "-p", "no:cacheprovider", str(ROOT / "tests")])
            return seen, "the whole committed test suite (python -m pytest tests)"
        for path in sorted(directory_of(which).glob(pattern_of(which))):
            for index, case in enumerate(reader_of(which)(path)):
                if limit is not None and index >= limit:
                    break
                with contextlib.suppress(Exception):
                    run(case)
                cases += 1
    finally:
        sys.settrace(None)
    return seen, f"{cases:,} cases of SingleStepTests/{which}"


def statements_of(source: str) -> set[int]:
    """Line numbers of the executable statements inside functions.

    Module-level statements (imports, constants, class bodies) run at import,
    before the tracer is installed, so counting them would report every one of
    them as unreached.  Docstrings are expression statements and are dropped.
    """
    import ast

    tree = ast.parse(source)
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # the docstring
        for statement in body:
            for inner in ast.walk(statement):
                if isinstance(inner, ast.stmt) and not isinstance(
                    inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    lines.add(inner.lineno)
    return lines


def report_lines(seen: dict[str, set[int]], what: str, out) -> None:
    print("# Source-line coverage of src/m68000_python\n", file=out)
    print(f"Traced: {what}.\n", file=out)
    print(
        "Statements inside functions only: module-level code runs at import,\n"
        "before the tracer is installed.  A line listed here is one no traced\n"
        "run executed.\n",
        file=out,
    )
    total_statements = total_seen = 0
    for path in sorted((ROOT / "src" / "m68000_python").glob("*.py")):
        source = path.read_text()
        statements = statements_of(source)
        if not statements:
            continue
        run = seen.get(str(path), set()) & statements
        missing = sorted(statements - run)
        total_statements += len(statements)
        total_seen += len(run)
        print(f"## {path.name}: {len(run)}/{len(statements)} statements", file=out)
        if missing:
            lines = source.splitlines()
            for number in missing:
                print(f"    {number:4}  {lines[number - 1].strip()}", file=out)
        print(file=out)
    print(f"TOTAL {total_seen}/{total_statements} statements", file=out)


# -- entry point --------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("view", choices=("encodings", "paths", "lines"))
    parser.add_argument("--corpus", default="m68000", choices=("m68000", "680x0"))
    parser.add_argument("--limit", type=int, default=None, help="cases per file (default: all)")
    parser.add_argument("--suite", action="store_true", help="measure the whole test suite")
    parser.add_argument("--out", default="-", help="write the report here")
    args = parser.parse_args()

    if not args.suite and not directory_of(args.corpus).exists():
        print(
            f"{directory_of(args.corpus)} not fetched (scripts/fetch_test_vectors.py)",
            file=sys.stderr,
        )
        return 2

    out = sys.stdout if args.out == "-" else open(args.out, "w")  # noqa: SIM115
    started = time.perf_counter()
    try:
        if args.view == "encodings":
            report_encodings(args.corpus, out, suite=args.suite)
        elif args.view == "paths" and args.suite:
            probe = Probe()
            what = run_paths_suite(probe)
            report_paths(args.corpus, probe, 0, 0, out, what=what)
        elif args.view == "paths":
            probe = Probe()
            cases, files = run_paths(args.corpus, probe, args.limit)
            report_paths(args.corpus, probe, cases, files, out)
        else:
            seen, what = run_lines(args.corpus, args.limit, args.suite)
            report_lines(seen, what, out)
        print(f"\n({time.perf_counter() - started:.1f}s)", file=out)
    finally:
        if out is not sys.stdout:
            out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
