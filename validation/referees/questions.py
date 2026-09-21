"""Put each open question of docs/worklog.md and docs/coverage.md to the referees.

    python validation/referees/questions.py            # every question
    python validation/referees/questions.py dbcc chk   # some of them

Each question is a handful of hand-written states run through this core,
WinUAE's CPU-tester core (pre-exception view) and Musashi (post view).  The
script prints what each says; docs/referees.md records the answers with each
referee's lineage and whether the question lies inside its
hardware-corrected scope.  Nothing here is a vote.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "src"), str(HERE.parents[1] / "tests")]

from referee import (  # noqa: E402
    Driver,
    Outcome,
    Setup,
    outcome_of_musashi,
    outcome_of_winuae,
    run_core,
)

CODE = 0x1000
USP = 0x6000
SSP = 0x8000
HANDLER = 0x3000  # vector n points at HANDLER + 0x10 * n, filled with NOPs


def base_ram(odd_vectors: dict[int, int] | None = None) -> dict[int, int]:
    ram: dict[int, int] = {}
    for vector in range(2, 64):
        target = (odd_vectors or {}).get(vector, HANDLER + 0x10 * vector)
        for i in range(4):
            ram[vector * 4 + i] = (target >> (24 - 8 * i)) & 0xFF
        for i in range(0, 0x10, 2):
            ram[HANDLER + 0x10 * vector + i] = 0x4E
            ram[HANDLER + 0x10 * vector + i + 1] = 0x71
    return ram


def state(
    words: list[int],
    *,
    d: dict[int, int] | None = None,
    a: dict[int, int] | None = None,
    sr: int = 0x2700,
    ssp: int = SSP,
    usp: int = USP,
    pc: int = CODE,
    ram: dict[int, int] | None = None,
    odd_vectors: dict[int, int] | None = None,
) -> Setup:
    registers = {f"d{i}": (d or {}).get(i, 0) for i in range(8)}
    registers.update({f"a{i}": (a or {}).get(i, 0) for i in range(7)})
    registers.update(usp=usp, ssp=ssp)
    memory = base_ram(odd_vectors)
    for index, word in enumerate([*words, 0x4E71, 0x4E71, 0x4E71]):
        memory[pc + 2 * index] = word >> 8
        memory[pc + 2 * index + 1] = word & 0xFF
    memory.update(ram or {})
    return Setup(registers, sr, pc, memory)


class Referees:
    def __init__(self) -> None:
        self.winuae = Driver("winuae")
        self.musashi = Driver("musashi")

    def ask(self, setup: Setup, bus_error: tuple[int, int, int] | None = None) -> dict:
        core_pre, core_post, cpu = run_core(setup, bus_error)
        if bus_error is not None:
            self.winuae.command("B {:x} {:x} {:x}".format(*bus_error))
        (w,) = self.winuae.run([setup.line("q")])
        if bus_error is not None:
            self.winuae.command("B 0 0 0")
        (m,) = self.musashi.run([setup.line("q")])
        return {
            "core": core_pre,
            "core_post": core_post,
            "cpu": cpu,
            "winuae": outcome_of_winuae(w, setup),
            "winuae_raw": w,
            "musashi": outcome_of_musashi(m),
            "musashi_raw": m,
        }

    def close(self) -> None:
        self.winuae.close()
        self.musashi.close()


def musashi_frame(outcome: Outcome, setup: Setup, size: int) -> bytes:
    ssp = outcome.registers["ssp"]
    return bytes(outcome.writes.get((ssp + i) & 0xFFFFFF, setup.byte(ssp + i)) for i in range(size))


def ccr(value: int) -> str:
    return "".join(
        f if value & bit else "-" for f, bit in zip("XNZVC", (16, 8, 4, 2, 1), strict=True)
    )


def show(title: str, rows: list[tuple[str, ...]], header: tuple[str, ...]) -> None:
    print(f"\n### {title}\n")
    print("| " + " | ".join(header) + " |")
    print("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        print("| " + " | ".join(row) + " |")


def frame_summary(outcome: Outcome) -> str:
    if not outcome.exception:
        return "no exception"
    if outcome.exception in (2, 3):
        f = outcome.frame
        info = int.from_bytes(f[0:2], "big")
        text = (
            f"vec {outcome.exception} PC {outcome.registers['pc']:06x} IR {f[6:8].hex()} "
            f"info {info:04x} (I/N {info >> 3 & 1}) addr {f[2:6].hex()}"
        )
        if outcome.frame1:
            text += f"; first frame PC {outcome.frame1[2:6].hex()}"
        return text
    return f"vec {outcome.exception} PC {outcome.registers['pc']:06x}"


# ----------------------------------------------------------------------------
# The questions


def q_dbcc(ref: Referees) -> None:
    """DBcc whose branch target is odd: which PC is stacked?"""
    rows = []
    for count in (5, 0):
        # DBF D0,*+0x13 at $1000: the target $1013 is odd.
        s = state([0x51C8, 0x0011], d={0: count})
        r = ref.ask(s)
        mf = musashi_frame(r["musashi"], s, 14)
        rows.append(
            (
                f"DBF D0 (D0.w={count}), target $1013",
                frame_summary(r["core"]) + f", D0={r['core'].registers['d0']:x}",
                frame_summary(r["winuae"]) + f", D0={r['winuae'].registers['d0']:x}",
                f"PC {mf[10:14].hex()} IR {mf[6:8].hex()} info {mf[0:2].hex()}",
            )
        )
    show("DBcc with an odd target", rows, ("case", "core (= gate)", "WinUAE", "Musashi"))


def q_chk_timing(ref: Referees) -> None:
    """CHK with a negative Dn inside the bound: 8 or 10 internal clocks?"""
    rows = []
    for dn, bound in ((0xFFFF, 5), (0x8000, 0x7FFF), (0x8001, 0x7FFF), (0xC000, 0x4001)):
        s = state([0x4181], d={0: dn, 1: bound})  # CHK D1,D0
        r = ref.ask(s)
        overflow = ((bound - (dn - 0x10000)) & 0xFFFF) >= 0x8000
        rows.append(
            (
                f"CHK D1,D0 D0.w=${dn:04x} bound=${bound:04x}"
                + (" (bound-Dn overflows)" if overflow else ""),
                f"{r['core'].clocks}",
                f"{r['winuae'].clocks} (= {r['winuae_raw']['cyc']} + {r['winuae_raw']['excyc']})",
                f"{r['musashi'].clocks}",
            )
        )
    show("CHK trap for a negative Dn: clocks", rows, ("case", "core", "WinUAE", "Musashi"))


def q_double_fault(ref: Referees) -> None:
    """An address error whose frame cannot be stacked (odd SSP), or whose vector is odd."""
    rows = []
    cases = {
        "MOVE.W (A0),D0, A0 odd, SSP odd": state([0x3010], a={0: 0x4001}, ssp=0x8001),
        "MOVE.W (A0),D0, A0 odd, vector 3 odd": state(
            [0x3010], a={0: 0x4001}, odd_vectors={3: 0x5001}
        ),
    }
    for name, s in cases.items():
        r = ref.ask(s)
        rows.append(
            (
                name,
                "halted" if r["cpu"].halted else frame_summary(r["core"]),
                ",".join(sorted(r["winuae"].notes)) or frame_summary(r["winuae"]),
                {0: "running", 1: "stopped", 2: "halted"}[r["musashi_raw"]["stopped"]],
            )
        )
    show("Double bus fault", rows, ("case", "core", "WinUAE tester", "Musashi"))


def q_divide_by_zero(ref: Referees) -> None:
    """Flags after DIVU/DIVS by zero, over dividend shapes and the incoming CCR."""
    rows = []
    for op, name in ((0x80C1, "DIVU D1,D0"), (0x81C1, "DIVS D1,D0")):
        for dividend in (0x00001234, 0x00000000, 0x7FFF0000, 0x80001234, 0xFFFF0000):
            for incoming in (0x00, 0x1F):
                s = state([op], d={0: dividend, 1: 0}, sr=0x2700 | incoming)
                r = ref.ask(s)
                rows.append(
                    (
                        f"{name} D0=${dividend:08x} CCR in {ccr(incoming)}",
                        ccr(r["core"].registers["sr"]),
                        ccr(r["winuae"].registers["sr"]),
                        ccr(musashi_frame(r["musashi"], s, 2)[1]),
                        f"{r['core'].clocks}/{r['winuae'].clocks}/{r['musashi'].clocks}",
                    )
                )
    show(
        "Divide by zero: stacked CCR",
        rows,
        ("case", "core", "WinUAE", "Musashi", "clocks core/WinUAE/Musashi"),
    )


def q_chk_zero(ref: Referees) -> None:
    """CHK's undefined flags when Dn is zero."""
    rows = []
    for bound in (5, 0, 0xFFFF):
        for incoming in (0x00, 0x1F):
            s = state([0x4181], d={0: 0, 1: bound}, sr=0x2700 | incoming)
            r = ref.ask(s)
            m = r["musashi"]
            m_ccr = musashi_frame(m, s, 2)[1] if r["core"].exception else m.registers["sr"]
            rows.append(
                (
                    f"CHK D1,D0 D0.w=0 bound=${bound:04x} CCR in {ccr(incoming)}",
                    f"{ccr(r['core'].registers['sr'])} (trap {r['core'].exception == 6})",
                    f"{ccr(r['winuae'].registers['sr'])} (trap {r['winuae'].exception == 6})",
                    f"{ccr(m_ccr)}",
                )
            )
    show("CHK with Dn = 0: flags", rows, ("case", "core", "WinUAE", "Musashi"))


def q_illegal(ref: Referees) -> None:
    """The PC stacked by ILLEGAL and the other not-executed words."""
    rows = []
    for word, name in (
        (0x4AFC, "ILLEGAL $4AFC"),
        (0x4AFA, "$4AFA"),
        (0x4AFB, "$4AFB"),
        (0x4E7B, "$4E7B (MOVEC, 68010+)"),
        (0xA123, "line A $A123"),
        (0xF123, "line F $F123"),
    ):
        s = state([word])
        r = ref.ask(s)
        mf = musashi_frame(r["musashi"], s, 6)
        rows.append(
            (
                name,
                frame_summary(r["core"]),
                frame_summary(r["winuae"]),
                f"PC {mf[2:6].hex()}",
                f"{r['core'].clocks}/{r['winuae'].clocks}/{r['musashi'].clocks}",
            )
        )
    show(
        "Illegal and unimplemented words: stacked PC (instruction at $1000)",
        rows,
        ("case", "core", "WinUAE", "Musashi", "clocks core/WinUAE/Musashi"),
    )


def q_bus_error(ref: Referees) -> None:
    """Bus errors: stacked PC, IR and access information."""
    region = (0x880000, 0x80000, 7)
    rows = []
    cases = {
        "MOVE.W (A0),D0, (A0) faults (data read)": state([0x3010], a={0: 0x880000}),
        "MOVE.W D0,(A0), (A0) faults (write)": state([0x3080], a={0: 0x880000}),
        "MOVE.L (A0),D0, first word faults": state([0x2010], a={0: 0x880000}),
        "MOVE.W (A0)+,D0, (A0) faults": state([0x3018], a={0: 0x880000}),
        "MOVE.W -(A0),D0, -(A0) faults": state([0x3020], a={0: 0x880002}),
        "NOP at $87FFFC, its prefetch of $880000 faults": state([0x4E71], pc=0x87FFFC),
        "JMP (A0) to $880000 (target fetch faults)": state([0x4ED0], a={0: 0x880000}),
        "ADD.W D0,(A0), read and write fault (the read first)": state(
            [0xD150], a={0: 0x880000}
        ),  # read also faults first
    }
    for name, s in cases.items():
        r = ref.ask(s, bus_error=region)
        rows.append((name, frame_summary(r["core"]), frame_summary(r["winuae"])))
    # A read-only region: the read succeeds, the write faults.
    s = state([0xD150], a={0: 0x880000})
    r = ref.ask(s, bus_error=(0x880000, 0x80000, 2))
    rows.append(
        ("ADD.W D0,(A0), write-only fault", frame_summary(r["core"]), frame_summary(r["winuae"]))
    )
    show("Bus errors", rows, ("case", "core", "WinUAE"))


def q_in_bit(ref: Referees) -> None:
    """An address error during exception processing (the I/N case): odd vectors."""
    rows = []
    for words, name, vector, extra in (
        ([0x4AFC], "ILLEGAL, vector 4 odd", 4, {}),
        ([0x4E40], "TRAP #0, vector 32 odd", 32, {}),
        ([0x80C1], "DIVU D1,D0 by zero, vector 5 odd", 5, {}),
        ([0x4181], "CHK D1,D0 trapping, vector 6 odd", 6, {0: 0xFFFF, 1: 5}),
        ([0x4E76], "TRAPV with V set, vector 7 odd", 7, {}),
    ):
        sr = 0x2702 if vector == 7 else 0x2700
        s = state(words, d=extra, sr=sr, odd_vectors={vector: 0x5001})
        r = ref.ask(s)
        rows.append(
            (
                name,
                frame_summary(r["core"]) + f"; {r['core'].clocks} clk",
                frame_summary(r["winuae"]) + f"; {r['winuae'].clocks} clk",
            )
        )
    show("Address error during exception processing (odd vector)", rows, ("case", "core", "WinUAE"))


def q_operand_pcs(ref: Referees) -> None:
    """Stacked PCs of operand address errors: one case per family the gate disagrees on."""
    rows = []
    cases = {
        "JSR (d16,A0) to an odd target": state([0x4EA8, 0x0010], a={0: 0x4001}),
        "JSR (d8,A0,D0) to an odd target": state([0x4EB0, 0x0010], a={0: 0x4001}),
        "JSR (xxx).W to an odd target": state([0x4EB8, 0x4001]),
        "JMP (d16,A0) to an odd target": state([0x4EE8, 0x0010], a={0: 0x4001}),
        "MOVEM.W (d8,A0,D0),D1 at an odd address": state([0x4CB0, 0x0002, 0x0010], a={0: 0x4001}),
        "MOVEM.W (d16,A0),D1 at an odd address": state([0x4CA8, 0x0002, 0x0010], a={0: 0x4001}),
        "MOVE.W (A0)+,D0 at an odd address": state([0x3018], a={0: 0x4001}),
        "MOVE.W -(A0),D0 at an odd address": state([0x3020], a={0: 0x4003}),
        "MOVE.L (A0)+,D0 at an odd address": state([0x2018], a={0: 0x4001}),
        "CMPM.W (A0)+,(A1)+, A0 odd": state([0xB348], a={0: 0x4001, 1: 0x5000}),
    }
    for name, s in cases.items():
        r = ref.ask(s)
        rows.append(
            (
                name,
                frame_summary(r["core"]) + f", A0={r['core'].registers['a0']:x}",
                frame_summary(r["winuae"]) + f", A0={r['winuae'].registers['a0']:x}",
            )
        )
    show(
        "Operand address errors: stacked PC and address register",
        rows,
        ("case (instruction at $1000)", "core (= gate)", "WinUAE"),
    )


def q_move_in(ref: Referees) -> None:
    """MOVE.W to -(An) whose write faults, followed by an illegal instruction or with T set."""
    rows = []
    for words, sr, name in (
        ([0x3100, 0x4E71], 0x0700, "MOVE.W D0,-(A0), next NOP"),
        ([0x3100, 0x4AFC], 0x0700, "MOVE.W D0,-(A0), next ILLEGAL"),
        ([0x3100, 0x4E73], 0x0700, "MOVE.W D0,-(A0), next RTE in user mode"),
        ([0x3100, 0x4E71], 0x8700, "MOVE.W D0,-(A0), next NOP, T set"),
    ):
        s = state(words, a={0: 0x4003}, sr=sr)
        r = ref.ask(s)
        rows.append(
            (
                name,
                frame_summary(r["core"]) + f"; {r['core'].clocks} clk",
                frame_summary(r["winuae"]) + f"; {r['winuae'].clocks} clk",
            )
        )
    show("MOVE.W to -(An): the faulting write's frame", rows, ("case", "core (= gate)", "WinUAE"))


def q_clocks(ref: Referees) -> None:
    """Clock counts where the manual and the emulators disagree."""
    rows = []
    for words, name, manual, extra in (
        ([0x5248], "ADDQ.W #1,A0", "4 (UM Table 8-5)", {}),
        ([0x5288], "ADDQ.L #1,A0", "8", {}),
        ([0x5348], "SUBQ.W #1,A0", "4 (UM Table 8-5)", {}),
        ([0x4181], "CHK D1,D0, D0 > bound (trap)", "40 (UM Table 8-14)", {0: 7, 1: 5}),
        ([0x4181], "CHK D1,D0, no trap", "10", {0: 3, 1: 5}),
        ([0x3010], "MOVE.W (A0),D0, A0 odd", "50 (UM Table 8-14)", "odd"),
    ):
        a = {0: 0x4001} if extra == "odd" else {}
        s = state(words, d=extra if isinstance(extra, dict) else {}, a=a)
        r = ref.ask(s)
        rows.append(
            (
                name,
                manual,
                str(r["core"].clocks),
                str(r["winuae"].clocks),
                str(r["musashi"].clocks),
            )
        )
    show("Clocks", rows, ("case", "manual", "core", "WinUAE", "Musashi"))


QUESTIONS = {
    "dbcc": q_dbcc,
    "chk-timing": q_chk_timing,
    "double-fault": q_double_fault,
    "divide-by-zero": q_divide_by_zero,
    "chk-zero": q_chk_zero,
    "illegal": q_illegal,
    "bus-error": q_bus_error,
    "in-bit": q_in_bit,
    "operand-pc": q_operand_pcs,
    "move-in": q_move_in,
    "clocks": q_clocks,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("questions", nargs="*", choices=[*QUESTIONS, []])
    args = parser.parse_args()
    ref = Referees()
    for name in args.questions or QUESTIONS:
        QUESTIONS[name](ref)
    ref.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
