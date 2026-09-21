# Claims: what this core claims, how strongly, and where it stops

The Z80 and 6502 cores could be checked exhaustively against hardware-
captured oracles. The 68000 cannot: the only hardware-captured sources are
narrow, the broad corpora come from emulators, and this project has **no
68000 hardware** of its own. So this core makes no single claim of
correctness. Each behaviour instead carries a status, set by how many
*independent* lines of evidence agree on it and how close to silicon the
best of them is. Where the evidence runs out, this page says so rather than
choosing a winner.

This page is the contract. The evidence behind each row lives in
[validation](validation.md), [referees](referees.md),
[coverage](coverage.md), [mutation](mutation.md) and
[undocumented-behavior](undocumented-behavior.md); what was decided, and
when, is in the [worklog](worklog.md).

## The strands of evidence

Agreement counts once per *lineage*, not once per source: two results from
the same implementation are one confirmation.

| Lineage | Sources here | Tier | Reach |
| --- | --- | --- | --- |
| **Real 68000 silicon** | flamewing's BCD verifier (Genesis-captured tables); transistorfet's hardware run over ASR.b | T1 | ABCD, SBCD, NBCD exhaustively; 1,642 ASR.b cases |
| **MAME's microcode transcription** | the SingleStepTests/m68000 gate (317,500 cases); the MAME 0.285 lockstep (24.6 M + 28.2 M instructions); MAME's opcode listing | T3 | every instruction family, the bus-cycle order, the prefetch queue, exact clocks, address-error frames. The gate and the lockstep are **one** lineage |
| **UAE / WinUAE** | WinUAE's CPU-tester core, built and run here (Hatari's core is the same code and is not counted again) | **T2** inside the scope its author checks on real Amigas, T3 outside it | results, all flags, address-error and odd-vector frames, read and prefetch bus-error frames, clock totals to within ±2 |
| **CLK** (Tom Harte) | SingleStepTests/680x0 (1,000,060 cases) | T3 | every family, with its own choices on the disputed corners |
| **Musashi** | built and run here | T3 | architectural results and group 1/2 exception entry only |
| **Motorola** | the PRM and the User's Manual | documentation | defined behaviour, published clock tables, exception rules; silent or ambiguous on the corners |
| **The suite itself** | coverage mapping, 176 seeded mutants | not an oracle | shows where the evidence reaches and whether it would notice a wrong rule |

## Status levels

| Status | Meaning |
| --- | --- |
| **Verified** | Hardware-captured (T1) evidence covers the behaviour exhaustively over a stated domain, and the core matches it. |
| **Strong** | Hardware-corrected T2 evidence, **run** inside its checked scope, agrees with the core, and so does at least one other lineage. This is the most that can be said without silicon. |
| **Provisional** | One lineage, or one lineage plus the manual, supports the core, and no credible source contradicts it. |
| **Contested** | Credible sources of different lineages disagree. The core follows the gate (MAME's microcode) until something closer to silicon decides. |
| **Undecidable here** | Nothing available can tell the candidates apart: a difference inside T2's ±2-clock tolerance, or behaviour T2 never checks. It needs hardware. |
| **Outside the contract** | Not claimed at all, by decision. |

## The claims

### Verified

- **ABCD, SBCD and NBCD**: the result and all five flags, including the
  undefined N and V and non-BCD digits, for every input (525,312 cases),
  against flamewing's hardware-captured tables.
- **ASR.b by a register count of at least 8** sets X and C (1,642 cases
  of a hardware run). ASR.w and ASR.l follow the same rule, but only at
  *Strong*.

### Strong

- **Instruction results and defined flags** for every one of the 45,815
  defined first words:
  - The gate executes 38,019 of them directly.
  - WinUAE, run over the whole gate, disagrees with no ordinary
    (non-faulting) case.
  - Musashi agrees on 98.2% of judged gate cases; a higher tier decides
    every difference in the core's favour.
  - CLK agrees wherever no named cause applies.

  The other 7,796 words come from the suite's own tests. 2,631 of them
  (every Bcc, BRA and MOVEQ word) and 57 more are run against the manual
  or an effective-address model, and 3,345 are register-renamed twins of
  words the gate runs. The remaining 1,763 (1,510 plus 253) rest on register
  symmetry alone, with words the gate does not run either: the suite shows
  the handler treats register numbers alike, and the gate checks that
  handler on other words.
- **The undefined flags** of DIVU/DIVS overflow, DIVU/DIVS by zero, and CHK
  (Dn = 0 included). WinUAE's run agrees on every case, and so do the gate
  where it has cases and CLK where it has them. Dn = 0 for CHK is a corner
  that cputest's random generator may never have hit.
- **The decoder**: which of the 65,536 first words are instructions,
  ILLEGAL, line A, line F or illegal. This matches MAME's listing word for
  word, the gate, and WinUAE's run on the illegal words.
- **Group 1 and 2 exception entry**: the vector, the three-word frame, the
  new SR, and the stacked PC. For ILLEGAL and the unimplemented words that
  PC is the word's own address, taking 34 clocks. Evidence: WinUAE (run),
  Musashi and the gate.
- **An address error's clocks**: 58 from the aborted access, not the
  manual's 50. WinUAE (run) confirms all 178,083 judged 680x0 cases.
- **Most of an address error's frame and register side effects**:
  - The stacked PC matches WinUAE in 118,245 of 123,858 judged 680x0
    cases, and in all gate cases outside the contested families below.
  - The access word and function code are confirmed. So are the halfway
    flags of a faulting MOVE.L and the IR of a faulting MOVE.W.
  - The long `(An)+` and `-(An)` register rules are confirmed.
- **I/N when a group 2 exception's own processing faults** (TRAP, TRAPV,
  CHK, divide by zero with an odd vector): clear. WinUAE (run) and MAME's
  microcode (read) agree. The core followed the manual's wording (set)
  until 2026-09-21.
- **LINK A7** pushes A7's value from before the push.
- **ADDQ.W and SUBQ.W #,An take 8 clocks**, not the manual's 4. WinUAE
  (run) and the gate agree, and the 4-clock difference is outside ±2.

### Provisional

- **Exact clock totals of ordinary instructions.** The gate gives exact
  values and the lockstep matches MAME instruction by instruction. WinUAE
  confirms them only to within ±2 clocks, so the exact figure rests on
  one lineage.
- **The order of bus cycles, the prefetch queue's contents, and the
  function code of completed accesses.** Only MAME's lineage records
  these, through the gate and the lockstep. cputest never checks bus
  order, and CLK reads RTE's and RTR's stack in a different order. The
  lockstep shows real games run identically to MAME. That confirms
  integration with the gate's lineage, not correctness independent of it.
- **Trace**:
  - trace as its own boundary after the traced instruction;
  - no trace after an instruction that never executed (illegal, line A/F,
    privileged in user mode);
  - trace taken before a pending interrupt.

  The evidence is the manual, MAME's microcode (read) and WinUAE's rule
  (read). No corpus captures a trace exception, and the referees were not
  run on it.
- **Interrupts and STOP**:
  - level and mask handling;
  - level 7 as an edge;
  - autovector, vectored and spurious acknowledge;
  - the entry frame;
  - STOP's wake-up.

  The evidence is the manual, the MAME lockstep (5,579 interrupts), and
  scenario tests. The **E-clock wait of an autovector acknowledge** (5 to
  14 clocks by phase) is MAME's rule alone.
- **RESET and STOP as instructions**: the gate (MAME) and the manual.
- **ADDQ.L and SUBQ.L #,An take 8 clocks**: the manual and the gate say
  8, CLK says 6. WinUAE agrees with 8, but a 2-clock difference is inside
  its tolerance.

### Contested

In every case below, the core follows the gate. What settles each one is
the same: WinUAE's `cputest` run on real 68000 hardware, which would turn
T2 into T1.

| Behaviour | Core = gate (MAME) | WinUAE (T2, run, in scope) | CLK | Gate cases affected |
| --- | --- | --- | --- | ---: |
| Is An advanced when a **word (An)+** operand address-errors? | yes, by 2 | no | yes | 4,330 |
| An after **CMPM.L (An)+,(An)+** faults | 2 further | 2 less | differs from both | 115 |
| Stacked PC of **JSR** through (d16,An), (d8,An,Xn), (d16,PC), (d8,PC,Xn) to an odd target | instruction + 4 | instruction + 2 | differs from both | 762 |
| Stacked PC of **DBcc** to an odd target | instruction + 4 | target + 2 | the target | 632 |
| Stacked PC of **MOVEM** through (d8,An,Xn), (d8,PC,Xn) at an odd address | 4 more | 4 less | = WinUAE | 306 |
| I/N of a **MOVE.W to -(An)** whose write faults when the next word is illegal or privileged | 0 | 1 | 0 | 35 |

Why these are not decided by the tier rule alone: T2 judges what its author
corrected it on, and cputest's address-error presets cover this *category*.
But the record does not show that these particular modes ran on hardware,
and the other side is transcribed from the chip's own microcode. Picking
either would claim more than the evidence gives.

### Undecidable here

These need hardware that this project does not have.

- **Differences of 2 clocks**, inside cputest's tolerance:
  - CHK trapping for a negative Dn when `bound - Dn` overflows 16 bits.
    The gate says 8 internal clocks; WinUAE, CLK and Musashi say 10.
  - CHK trapping for Dn > bound: the gate and WinUAE say 38, the manual 40.
  - MOVE to -(An) whose write faults: WinUAE takes 2 more (228 gate cases).

  The core keeps the gate's values. A logic-analyser capture would settle
  them.
- **The double bus fault.** The core halts, as UM 5.4.4 says, and so do
  Musashi (run, with an odd SSP) and WinUAE's emulator (read). MAME takes another address
  error instead. cputest skips every test that would halt.

### Outside the contract

- **The contents of a bus-error frame.** A host raises `BusError` and the
  core takes vector 2 with a seven-word frame. The frame's stacked PC, IR,
  I/N bit, and whether the instruction's flags and register writes happened
  first are **not claimed**:
  - With BERR injected into the gate's own states, WinUAE (run, T2 for
    reads and prefetches) agrees on 90% of data-read faults, but only 33%
    of prefetch and write faults.
  - The differences fall into named classes ([referees](referees.md),
    "Bus errors"). Matching them would mean reordering the closing prefetch
    against the result writes in most handlers, checked against one
    lineage.
  - Bus errors matter to Amiga and Atari ST system software, not to the
    System 16 and Mega Drive boards this core is for.
  - Seven cases where the two agree are pinned as tests; nothing else about
    the frame is.
- **Timing inside an instruction.** `step()` returns clock totals. Where
  each bus cycle falls within them, TAS's 5-clock read-modify-write shape,
  and wait states the host inserts are not modelled.
- **Other processors**: the 68010 and later (VBR, loop mode, the 68010
  bus-error frame, `MOVEC`, `MOVES`), the 32-bit bus and addressing of the
  68020 and up, and the 68008's timing.
- **Behaviour the host owns**: anything done with the RESET and HALT pins
  beyond the RESET instruction, bus arbitration, dropped TAS write-backs,
  DMA stalls.

## How strong the suite is

Coverage and mutation testing measure the evidence, not the core:

- **Coverage.** The suite runs all 45,815 defined words and every
  behavioural path it declares (a 68000 never writes to program space, so
  that path is unreachable). It reaches 1,442 of 1,466 core statements;
  the other 24 are import-time code, defensive asserts and 4 dead lines
  ([coverage](coverage.md)).
- **Mutation testing.** 176 seeded semantic mutants were run. Every
  non-equivalent mutant is killed, including D10 (the DIVS-by-zero flags),
  which the WinUAE run pinned. The two survivors, N7 and M8, are provably
  equivalent: nothing a host can observe changes ([mutation](mutation.md)).
- **What surviving checks found.** Three real core bugs got past a 100%
  gate pass, because the gate records nothing in those places:
  - trace after an instruction that never executed;
  - TRAPV's IR when its vector is odd;
  - a bus error on TAS's write escaping `step()`.

  A fourth rule, I/N in group 2, was corrected on referee evidence. Each
  fix went in as a failing test first.

## The claim, in one paragraph

m68000-python implements the documented MC68000 instruction set and
exception model.
- **BCD instructions:** verified against hardware.
- **Instruction results, defined and undefined flags, exception entry,
  and address-error timing:** agree with a hardware-corrected emulator run
  inside its checked scope, and with at least one other independent
  lineage.
- **Exact clocks, bus-cycle order and prefetch behaviour:** follow MAME's
  microcode transcription, over 317,500 single-step cases and 52.8
  million instructions of real game code in lockstep.
- **Not settled by available evidence:** six address-error behaviours
  where credible sources disagree, three 2-clock timing questions, and the
  double bus fault, each listed with what would settle it.
- **Not claimed:** bus-error frame contents.
