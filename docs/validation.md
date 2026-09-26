# Validation: the certification record, and the oracles behind it

## Claim

`m68000-python` agrees with the **hardware-captured** BCD tables of
flamewing's verifier on every input of `ABCD`, `SBCD` and `NBCD` (result and
all five flags), and with **every case** of the pinned, **microcode-derived**
SingleStepTests/m68000 corpus: 317,500 of 317,500, each compared on
registers, SR, both stack pointers, the prefetch queue, RAM, the clock total
and the ordered bus transactions with their function codes. No case is
excluded. Run in lockstep with MAME 0.285 on real game code it matched
every register before every instruction for 24,595,631 instructions of
System 16B Altered Beast (every bus write checked, every instruction's clock
count checked) and 28,249,660 of the Genesis Altered Beast. Against the
second corpus, SingleStepTests/680x0, 787,660 of 1,000,060 cases agree and
every disagreement has a named cause; WinUAE's CPU-tester core, built here
and **run** on every case (T2 inside the scope its author checks on real
Amigas, [referees](referees.md)), sides with this core on most of them and
one cause rests on a hardware run (T1).  Running WinUAE also found places
where this core and the gate disagree with it inside that scope (the An of
a faulting word (An)+, the stacked PC of three families of odd jumps and
MOVEM, one I/N bit); the core follows the gate on each, and
[claims](claims.md) lists them as contested.  A second I/N rule (group 2
exception processing) was one-sided and is now the core's (e395be9).  Beyond BCD and
what WinUAE's run decides, the claim rests on emulator-derived oracles
(MAME's microcode transcription): strong detectors, not a hardware
judgement.

## Certification record

Linux x86_64, a shared 32-core machine at a load average of 30-50 (timings
are upper bounds). CPython 3.14.4; PyPy 7.3.23 / Python 3.11.15.

| Gate | Tier | Pin | Result | CPython | PyPy |
| --- | --- | --- | --- | ---: | ---: |
| BCD tables: ABCD 262,144 + SBCD 262,144 + NBCD 1,024 inputs, result and X N Z V C (`tests/test_bcd.py`) | T1 | flamewing/68k-bcd-verifier `39a01be528b0744302bf1dc9b3463fc22a3fc45f`, table SHA-256 `8432868c…80147e5` | all agree | 0.8 s | 0.9 s |
| SingleStepTests/m68000, 127 files, 317,500 cases (`tests/test_corpus.py`) | T3 (microcode) | `64b253116a3de04aaac4346c43680960dc9b67e5` | 317,500 / 317,500 | 27 s | 26 s |
| Decoder: 65,536 first words vs MAME 0.285 `m68000.lst` | T3 | `mame0285` | 45,815 defined + ILLEGAL + 8,192 line A/F, every word's family agrees | -- | -- |

Commands, from the repository root with the corpus fetched
(`python scripts/fetch_test_vectors.py`):

```text
python -m pytest -q tests/test_bcd.py tests/test_corpus.py
python scripts/run_corpus.py --all            # the same comparison, one line per file
```

`M68000_BCD_TABLE=path/to/bcd-table.bin` makes the BCD gate compare byte by
byte against a locally generated table (build `bcd-gen.cc` at the pin with
any C++ compiler and run it); without it the gate compares SHA-256.

### What each corpus case compares

`tests/harness.py` loads the initial state into the core (the corpus's
`pc` is the prefetch address, the instruction's own address + 4, and
`prefetch` is IR and IRC), runs one `step()`, and compares: D0-D7, A0-A6,
USP, SSP, SR, the prefetch address, IR and IRC, every RAM word the final
state lists, the clock total, and the complete ordered list of bus accesses,
each with kind (read, write, aborted read, aborted write), address, size,
the 16-bit bus value, both data strobes, and the function code. The host
logs each access as the core makes it; function codes are on for the run.

Not compared, on purpose: the data value of an access that an address error
aborted (AS is never asserted, so no data moves; the corpus records
whatever MAME's data latch held), and the position of each idle (`n`)
entry among the accesses (their sum is inside the clock total, and the
order of every bus access is compared).

### Decisions and notes

- **Trace (corpus issue #2).** The T bit is not stripped. Trace is its own
  boundary: an instruction that begins with T set completes and `step()`
  returns; the next `step()` takes the trace exception. The corpus captures
  `final` before the trace exception, which is exactly the first boundary.
- **TAS.** The corpus README says its TAS "doesn't properly handle the
  special 5-cycle TAS read-modify-write timing". The totals the corpus
  records (memory forms: operand read, 2 internal clocks, write, then the
  prefetch; 14 clocks for `(An)`) are also what WinUAE's 68000 generator
  produces (`gencpu.cpp`, `i_TAS`, `cpu_level == 0`, at WinUAE master
  `1977af501f6c3389c2eefe119ecb10c82d6582f3`, T2; since 2026-09-21 also run:
  WinUAE's tester core agrees with all 2,498 TAS cases it can judge, clocks
  included, [referees](referees.md)), so all 2,500 TAS cases are
  compared on clocks too and pass. The per-cycle shape inside the
  read-modify-write, which the README's remark is about, is below this
  core's resolution.
- **TRAPV.** The README's "strange issue" did not show: all 2,500 cases
  pass, including the taken trap, whose refill read is made after S is set
  (program space FC 6).
- **Address errors** are 60% of many files' cases, because the corpus's
  address registers are random. Everything that makes them pass is a rule
  the corpus records (T3) and [undocumented-behavior](undocumented-behavior.md)
  now states: the stacked PC, the IR and access-information words, the
  halfway flags of a long, when (An)+ and -(An) move, and the clock cost.

## Rung 4: MAME 0.285 lockstep on real code

`validation/lockstep.py record BOARD` runs MAME headless with
`validation/lockstep.lua` (docs/mame-oracle.md's recipe): the debugger's
`trace` action logs `curpc sr d0-d7 a0-a6 usp sp totalcycles` before every
instruction, one watchpoint logs every read of a device window, another
every write. `compare` builds the board around the core, replays the
watched reads in MAME's order, checks every watched write (address, size,
value), and before every instruction compares PC, SR, D0-D7, A0-A6, USP and
SSP, and the clocks since the previous line. The host is the validation
directory's, not the core's.

| Board (MAME driver) | Program | Instructions identical | Interrupts | Clocks |
| --- | --- | ---: | ---: | --- |
| System 16B `altbeast` (sega/segas16b.cpp), 68000 at 10 MHz; only the 256 KB program ROM modelled, every other read replayed and **every write checked** | romset `altbeast` (epr-11907.a7 crc 29e0c3ad, epr-11906.a5 crc 4c9e9cd8), 30 emulated seconds from power-on | **24,595,631** | 1,791 (level 4, autovectored) | every one of 24,593,837 intervals agrees; the other 1,792 contain the driver's `spin_68k_w` stall (20,000 cycles when the i8751 asks) |
| Genesis `genesis` (sega/megadriv.cpp), 68000 at 7.67 MHz; ROM and 64 KB RAM modelled, Z80 window, I/O and VDP replayed and their writes checked | Altered Beast (USA, Europe) (Rev 2), No-Intro, SHA-1 `38945360d824d2fb9535b4fd7f25b9aa9b32f019`, 40 emulated seconds | **28,249,660** (and the state before the 28,249,661st, where MAME stopped) | 3,788 (levels 4 and 6, autovectored) | 28,181,328 of 28,249,660 agree; the rest, where sampled, are accesses to the Z80 window, which MAME delays by a clock (`before_delay`), and VDP waits: the host's business |

Command lines (in each run's `command.txt`; nothing under
`validation/mame_runs/` is committed):

```text
python validation/lockstep.py record altbeast --seconds 30 --tag 30s
python validation/lockstep.py compare altbeast --tag 30s
python validation/lockstep.py record genesis "Altered Beast (USA, Europe) (Rev 2).zip" --seconds 40
python validation/lockstep.py compare genesis "Altered Beast (USA, Europe) (Rev 2).zip"
```

What the board needed, all of it host, not CPU: on `altbeast` the i8751
reaches the 68000's bus through the 315-5195 mapper (register 5 transfers;
the reader drops those accesses), drives the 68000's RESET once during boot
(partway through an instruction, which an instruction-level core cannot
reproduce, so the lockstep takes D0-D7/A0-A6/USP from MAME's next line
after that one reset; PC, SR and SSP come from the core's own reset: one
resynchronisation of fifteen registers in 24,595,631 instructions, accepted
on 2026-09-25 as a limitation of the comparison, not a claim about the
core), and raises IRQ4. On the Genesis the Z80 reaches the
68000's bus through its bank window (dropped likewise), and the bus drops
TAS's write-back. Interrupts are recognised where MAME's next line is a
handler entered with the mask raised; the host then holds that level for
one step and the core must arrive at the same state.

The first divergences on the way, each diagnosed before the runs were
extended: the i8751's and Z80's own accesses on the 68000's bus (a lockstep
host matter), and a PC compared at 24 bits when Genesis code runs at
`$FFFFxxxx`. None was a core error.

Disassembly: `validation/disasm_vs_mame.py` compares `disasm.py` with
MAME's disassembler on every distinct instruction these traces ran:
880 of 880 (altbeast, 4 s) and 3,771 of 3,771 (Genesis).

## Rung 5: SingleStepTests/680x0 as a detector

`scripts/run_680x0.py` runs all 124 files of the second corpus (Tom
Harte's, generated by his CLK emulator, T3, no license file: fetched with
`--with-680x0`, never committed) through the same comparison as the gate,
adapted to its conventions (`tests/harness_680x0.py`: byte-addressed RAM,
byte values on byte accesses, no strobes, no record of an aborted access).
`scripts/classify_680x0.py` sorts every disagreement into a named cause; no
case falls outside the rules (none is printed as `UNCLASSIFIED`).

**787,660 of 1,000,060 cases agree** (commit `979c928`, PyPy 7.3.23, about
2 minutes). The 212,400 others, by cause (a case can have several):

| Cases | Cause | Files | Explained by | WinUAE, run (docs/referees.md) |
| ---: | --- | --- | --- | --- |
| 178,087 | An address error costs 8 clocks more here: the aborted bus cycle (4) and 4 more before the two internal steps | 62 files | **T2**: WinUAE charges the aborted access 4 clocks (`exception3_read_access`, `exception3_write_access`) and 8 more before the frame (`Exception_ce000`, `start = 8` for a 68000 address error), 12 in all, as MAME's microcode does; CLK charges 4. `newcpu.cpp` at WinUAE `1977af5`. | **T2 by running**: clocks = core in all 178,083 judged (8 clocks: decisive). |
| 123,862 | The PC stacked by an address error | 62 files | **Partly open.** For a jump to an odd address WinUAE (T2) stacks the instruction's address + 2 with I/N clear (`i_JMP`: `incpc("2")`, `exception3_read_prefetch_only`), as this core and MAME do; CLK stacks the odd target with I/N set. For operand faults WinUAE computes a mode-dependent stacked PC (`check_address_error`, `exception_pc_offset`, MOVE's `pcextra`) of the same kind as MAME's microcode PC, but its values were not evaluated case by case. **DBcc** (about 1,960 of these) is a three-way disagreement: MAME stacks the instruction + 4, CLK the odd target, and WinUAE's generator reads as the target + 2 (`i_DBcc`: `incpc` to the target, then `exception3_read_prefetch`, which adds 2 on a 68000). Contested ([claims](claims.md)). | pc = core in 118,245; **contradicted** in 5,613: MOVEM (d8,An,Xn)/(d8,PC,Xn) (1,069, WinUAE = CLK), JSR via (d16,An)/(d8,An,Xn)/(d16,PC)/(d8,PC,Xn) (2,580, neither: instruction + 2), DBcc (1,964, neither: target + 2, as read). T2 conflicts with the gate: **contested**, the core stays on the gate ([claims](claims.md)). |
| 17,119 | Whether an address register had moved when the fault came | 22 files | **T2**: WinUAE's rules are this core's: `-(An)` is decremented before the check on a 68000, a MOVE `(An)+` destination is not incremented, a long MOVE to `-(An)` leaves An, ADDX/SUBX's special case (`check_address_error`, `move_68000_address_error`). | An/Dn = core in 16,746 (**T2 by running**); **contradicted** for CMPM.L (An)+,(An)+ (373, neither). Not in this row: 14,148 word (An)+ faults where core and CLK agree An moved and WinUAE says it did not (open). |
| 8,180 | Accesses before the fault differ (MOVE with a PC-relative source; RTE, RTR) | MOVE.w, MOVE.l, RTE, RTR | the causes in the next rows, seen before a fault | No pre-exception field differs but MOVE to -(An)'s clocks (18: +2, inside ±2). |
| 8,049 | RTE and RTR read the stack in another order (CLK reads the PC's high word before SR) | RTE, RTR | **T2**: WinUAE reads SR, then PC high, then PC low (`i_RTE`, 68000 branch: "Read SR (SP+=6), Read PC high, Read PC low"; `i_RTR` likewise). | Data-read order = core in all 8,048 judged, but bus order is not what cputest checks: **T3 by running** (the T2 label was too strong). |
| 6,828 | TAS's read-modify-write is logged as one access (`t`) with the written value | TAS | The 680x0 corpus's format, not a behaviour: the same address, the same value written, the same clocks. | No pre-exception difference. |
| 4,541 + 3,175 | The function code of a PC-relative operand read: program space (2/6) here, data (1/5) in CLK; directly, and inside address-error frames | 35 files | **T2**: WinUAE uses FC 2 for PC-relative operands in its hardware-checked address-error frames (`check_address_error`: "PC-relative: FC=2"). MAME's microcode does the same. | In address-error frames: access word = core in all 3,175 (**T2 by running**). A completed access's FC is not observable to the tester: the direct 4,541 stay T2 by reading. |
| 4,291 | CHK takes the trap without first refilling the queue | CHK | **T2**: WinUAE's `i_CHK` goes straight to the exception after the compare. | 3,672: bus order only (T3). **605: clocks = CLK** (10 internal: the CHK-timing question; inside ±2, undecided). 13: ccr = core. |
| 3,736 | ASR by a register count of at least the operand size: X and C set here, clear in CLK | ASR.b/.w/.l | **T1** for ASR.b: transistorfet's hardware runner found that 1,642 ASR.b cases of this corpus "don't match what the hardware is doing ... the test thinking the extend and carry flags shouldn't be set"; this core disagrees with exactly 1,642 ASR.b cases, each by X and C only. ASR.w (1,063) and ASR.l (1,031) are the same rule at other widths, `[unverified]` on hardware. | X and C = core in all 3,736: **T2 by running** for ASR.w and ASR.l. |
| 2,839 + 1,855 + 1,265 | DIVS and DIVU after overflow: flags, and DIVS's clocks | DIVS, DIVU | **T2**: WinUAE's 68000 rules, `setdivuflags`/`setdivsflags` (V=1, N=1, Z=0, C=0) and Cwik's `getDivs68kCycles` (absolute overflow found early), are this core's; every one of these cases is an overflow except one DIVU divide by zero, where WinUAE's `divbyzero_special` flags and next-instruction PC are this core's. | Flags and DIVS clocks = core in all judged (**T2 by running**; the clock differences are 106-132). |
| 1,005 | LINK A7 pushes A7's value from before the push here, after it in CLK | LINK | **T2**: WinUAE `i_LINK` ("ce confirmed"): "smode must be first in case it is A7". | Memory = core in all (**T2 by running**). |
| 822 | The halfway flags a MOVE.L shows when its first write faults | MOVE.l | **T2**: WinUAE's `move_68000_address_error` has the same table (none / high word / low word / complete by source and destination). | = core in all (**T2 by running**). |
| 731 | ADDQ.L and SUBQ.L to An: 8 clocks here, 6 in CLK | ADD.l, SUB.l | **T2** and the manual: WinUAE "ADDAQ.x is always 8 cycles"; UM Table 8-5 prints 8. | = core in all, but 2 clocks is inside the tester's ±2: not T2; the manual (8) and the gate stand. |
| 332 | The IR word of a MOVE.W whose `-(An)` write faults after the prefetch (the next opcode here) | MOVE.w | T2 by reading: WinUAE's `exception3_write` stacks `regs.ir`, which the prefetch before the write has already advanced. | IR = core in all (**T2 by running**); 2 more clocks in all (inside ±2) and I/N = 1 in 85 whose next word is illegal or privileged (a conflict with the gate: open). |
| 321 | CHK's undefined flags | CHK | **T2**: WinUAE's `setchkundefinedflags` for the 68000 (C=V=0, Z from Dn=0, N from Dn<0) is this core's. | = core in all (**T2 by running**). |
| 2 | ASL.b cases 1583 and 1761 | ASL.b | **The corpus's issue #4**: this core's results are the values the issue gives as correct. | = core. |

"T2 by reading" means the rule was read from WinUAE's source at the pin.
Since 2026-09-21 the last column says what WinUAE's CPU-tester core said
when it was **run** on every one of these cases (docs/referees.md: the
tester core is built from the pinned source and driven one instruction at
a time; `validation/referees/rerun_680x0.py`, 124 s on PyPy).  Its
authority is that WinUAE's author corrects it against real Amigas with
`cputest`, so its answer is T2 only inside what cputest checks: results,
flags (the undefined ones too), exception frames, register side effects of
faults, and clock totals to within 2 clocks.  Bus order is outside, which
is why the RTE/RTR row drops to T3, and 2-clock differences are inside the
tolerance, which is why the ADDQ.L row and the CHK timing question stay
undecided by T2.  Running contradicted the reading in three places (the
stacked PC of MOVEM and JSR through indexed and displacement modes, and
CMPM.L's An) and found a disagreement the table could not show, because
the core and CLK agree on it (a word (An)+ that faults: WinUAE leaves An).
Each is **contested** in [claims](claims.md) (decided 2026-09-21: the core
follows the gate until real-hardware evidence decides); the decision record
is [history/worklog.md](history/worklog.md).

## Rung 6: interrupts and STOP

`tests/test_interrupts.py` (12 scenarios): a level above the mask taken at
the next boundary, one at or below it held; the frame (PC low, SR, PC high)
and the new SR; level 7 taken on each 0-to-7 edge regardless of the mask
and not again while held; acknowledge answering a vector, `AUTOVECTOR`,
`SPURIOUS` (vector 24) or an out-of-range number (vector 15); trace taken
before a pending interrupt, which then enters from the trace handler's
first instruction (UM 6.3.8); interrupt entry clearing T; STOP waiting for a
level above its new mask and resuming after the STOP; STOP in user mode a
privilege violation; a traced STOP taking the trace exception; and the
E-clock phase of the autovector wait.

The claim is "consistent with the manual and with MAME", not verified: the
MAME lockstep checks the same entry on 1,791 System 16B and 3,788 Genesis
interrupts (state, the three frame writes on System 16B, the vector), and
with the clock-carrying trace the entry's clocks agree with MAME's at all
ten E-clock phases once the acknowledge adds MAME's one clock after VPA
(`vpa_sync`, `vpa_after` in m68000.cpp): 44 clocks plus 5 to 14 of E-clock
wait for an autovector, 44 for a vectored acknowledge (UM Table 8-14).

## Coverage and mutation (2026-09-21)

What the gates above reach, and how much a wrong core would have to differ
before the suite noticed, are measured in [coverage](coverage.md) and
[mutation](mutation.md). In brief:

- The gate executes 38,019 of the 45,815 defined first words, every value
  of every field but 125 BRA displacements, and every (size, addressing
  mode) combination but 18. It never takes vectors 2, 4, 5 or 9, a double
  fault, an address error during exception processing, a DBcc count-out,
  or word and long operands at their boundaries.
- The suite now executes all 45,815. The words the gate misses are covered
  by manual-derived tests (every Bcc, BRA and MOVEQ word; the 18
  combinations), by a PRM 2.2 effective-address model (40 words using A7's
  byte step or only absolute addresses), and by register renaming, a
  symmetry the manual implies (PRM 2.2): 3,345 of them are renamings of
  words the gate runs, so the gate's evidence transfers to them.
- One core bug was found this way and fixed (4206431 test, 8760315 fix): a
  traced illegal, line A/F or privilege-violating instruction was followed
  by a trace exception, contrary to UM 6.3.8 (MAME's microcode and WinUAE
  agree with the manual). No corpus could see it.
- Of 176 seeded mutants the suite at e3629c1 killed 158; with the coverage
  and survivor tests, 173; with the referee-pinned divide-by-zero flags
  (2026-09-21), 174. The two survivors, N7 and M8, are equivalent to the
  core: nothing a host can observe changes.

## The tier rule

Oracles are ranked by where their expected values came from:

| Tier | Meaning | Use |
| --- | --- | --- |
| **T1 hardware-captured** | Expected values read off a real MC68000 | Judge |
| **T2 hardware-corrected** | An emulator whose outputs have been compared against real hardware by its author and corrected until they agree, with that process on record | Judge for what it was corrected on; detector elsewhere |
| **T3 emulator-derived** | Values produced by an emulator, however good | Detector: a disagreement is a question, never a verdict |

A T3 oracle that is derived from the chip's own microcode (MAME's, below)
is still T3. Its answers are more likely right than a hand-written core's,
and a disagreement with it is a strong question; it remains an emulator
until someone runs the same case on silicon.

## Summary

| Oracle | Tier | License | Pin | Coverage | Status here |
| --- | --- | --- | --- | --- | --- |
| flamewing/68k-bcd-verifier | T1 | GPL-3.0 | `39a01be528b0744302bf1dc9b3463fc22a3fc45f` (2018-08-31) | ABCD, SBCD, NBCD: all inputs, all flags | **Gate: all 525,312 inputs agree** (generator run locally, table hashed) |
| transistorfet/68k-test-runner | T1 (tiny) | GPL-3.0 | `5b10d9f68a3f4370e02f5bda8afd28d2a86e69e7` (2023-06-12) | ASL.b, ASR.b of the 2023 Harte corpus on a real 68000 board | Not fetched; evidence only |
| WinUAE `cputest` and its 68000 core | T2 (inside cputest's checked scope) | GPL-2.0+ | `1977af501f6c3389c2eefe119ecb10c82d6582f3` (2026-09-17) | Integer instructions, undefined flags, address/bus error frames, cycle counts to ±2 (7 MHz Amiga) | **Built and run** (validation/referees, not committed): vs the gate 308,416 / 314,988 judged cases agree; the 680x0 table re-derived; [referees](referees.md) |
| SingleStepTests/m68000 | T3 (microcode-derived) | MIT | `64b253116a3de04aaac4346c43680960dc9b67e5` (2024-08-01) | 127 files, 317,500 cases, registers + RAM + prefetch + bus transactions + cycles | **Gate: 317,500 / 317,500** |
| MAME 0.285 microcoded 68000 | T3 (microcode-derived) | BSD-3-Clause core in GPL-2.0+ MAME | `mame0285` = `3bd358f74ce504be519247ac9eddff4d6b46cb70`; `/usr/games/mame` 0.285 | Whole-game traces, see [mame-oracle](mame-oracle.md) | **Trace run verified** |
| SingleStepTests/680x0 (Harte) | T3 | **none** (issue #1 open) | `e0d5ece9670205cc84a0101081837deb446f86a3` (2024-05-14) | 124 files, 1,000,060 cases, registers + RAM + prefetch + transactions + cycles | **Fetched and counted**, detector only |
| Musashi | T3 | MIT | `313ebf1bd9f4d0d93341eb5ce21fd8a119e9dbdd` (2026-03-08) | Architectural results and group 1/2 exception entry, an independent hand-written lineage | **Built and run** (validation/referees): vs the gate 257,300 / 261,894 judged cases agree, every difference an undefined or disputed rule a higher tier decides; [referees](referees.md) |
| MicroCoreLabs `MC68000_test_all_opcodes` | T3 | MIT-style notice in the source | `MicroCoreLabs/Projects` (not pinned) | Self-checking opcode program, "developed using the Easy68K simulator" | Not fetched |
| cdifan/cputest | T3 | none | `be90dc8b410733075afe0fa4eead1444b3455574` (2022-03-13) | The same program for CD-i (68070); "No CD-i hardware or emulator currently passes all of the tests" | Not fetched |

No hardware-captured single-step corpus for the 68000 exists in the
SingleStepTests organisation (its "Hardware-Generated" suites are 8088,
8086, 80186, 80286, 80386 and V20; both 68000 repositories are
emulator-generated, checked 2026-09-11 via the GitHub API). The two T1
sources found are narrow: one instruction family exhaustively, and two
opcodes' worth of cross-checking.

## T1: flamewing's BCD verifier

<https://github.com/flamewing/68k-bcd-verifier>, GPL-3.0. A Sega Genesis
ROM that runs every input combination of `ABCD` and `SBCD` (256 × 256
operands × 4 X/Z states = 262,144 each) and of `NBCD`, compares the result
and CCR against a table, and reports deviations. README: "Real hardware
naturally passes all tests; this has been verified on: Model 1 Sega Genesis,
Model 3 VA2 Sega Genesis. For reference, the original BCD data I used to
reverse-engineer the operations was obtained from a Model 1." The
expected tables are generated by the source; the rule, stated in
[undocumented-behavior](undocumented-behavior.md) and written out in
`_bcd.py`, is the T1 gate for the three instructions (`tests/test_bcd.py`;
the certification record above). Limits: only BCD; only
the register forms are timed by the frame counter, not cycle-verified.

## T1 (evidence): transistorfet's hardware runner

<https://github.com/transistorfet/68k-test-runner>, GPL-3.0. Ran Tom
Harte's then-current 68000 JSON tests on a real 68000 (the Computie
single-board computer) over a serial link, ~8,000 cases per opcode in five
minutes. README (June 2023): "The ASR.b instructions are showing that 1642
tests don't match what the hardware is doing, and I think the hardware is
correct. In most of the tests, the flags are incorrectly set, with the test
thinking the extend and carry flags shouldn't be set." Only `ASL.b` and
`ASR.b` were run. The corpus that repository tested predates the 680x0
repository's 2024-05-14 import, so whether those 1,642 cases were fixed is
not known; the 680x0 corpus still has open issue #4 (two wrong `ASL.b`
cases, `e502` numbers 1583 and 1761, upper bytes of D2 altered). The value
here is methodological: the same runner, pointed at the m68000 corpus,
would be the cheapest route to a T1 statement about it.

## T2: WinUAE's 68000 and `cputest`

<https://github.com/tonioni/WinUAE>, GPL-2.0+, `cputest/readme.txt`. Toni
Wilen's tester generates test sets from the UAE core ("All the CPU logic
comes from UAE CPU core"), then runs them *on real Amigas*, stopping at the
first mismatch; the emulator is corrected until hardware agrees. It checks
"All CPU registers (D0-D7/A0-A7, PC and SR/CCR)", "Generated exception and
stack frame contents", "Memory writes", "Undefined flags (for example DIV
and CHK or 68000/010 bus address error)", and on a 7 MHz PAL Amiga with
real Fast RAM, cycle counts to ±2 clocks. Compatibility line for the
68000: "Complete. Including bus and address error stack frame/register/CCR
modification undocumented behavior. Full cycle count support." Caveats from
the same file: TAS results depend on RMW-compatible RAM; STOP and RESET
variants that would halt are skipped; the generator is "very brute force".

What this repository can use without an Amiga: the tester's own 68000
core, which `validation/referees/build_referees.py` generates from the
pinned source and `winuae_referee.cpp` runs one instruction at a time
([referees](referees.md): what it models, its calibration against the gate,
its checked scope and every answer it gave).  What it cannot claim: a
hardware run of its own; WinUAE's answer is T2 only where cputest checks
it on hardware, and a detector elsewhere.  The published test-data license
is not stated in the readme; nothing of it is copied here, and no WinUAE
source is committed.

## T3: SingleStepTests/m68000 (the chosen corpus)

<https://github.com/SingleStepTests/m68000>, MIT (Copyright (c) 2024
SingleStepTests). README: "Generated using the microcoded core in MAME"
via raddad772's fork <https://github.com/raddad772/mame-m68k-test-gen>
(`88e8b3278b8a06268a0f9bd63d28ce5d96cbede6`, 2024-08-01, GPL-2.0+ as MAME).
"STATUS: all of the tests except TAS and TRAPV are verified as good." The
README does not say verified against *what*; no hardware run is claimed, so
the tier is T3 and the "verified" is `[unverified]` here.

Pinned and fetched by `scripts/fetch_test_vectors.py` on 2026-09-11:

```text
SingleStepTests/m68000 @ 64b253116a3de04aaac4346c43680960dc9b67e5
  files: 127  cases: 317500  bytes: 137928157
```

127 `v1/*.json.bin` files, 2,500 cases each (every file), 137,928,157 bytes
(the GitHub archive is 112 MB compressed). The files are one per mnemonic
and size (`ADD.b`, `ADD.w`, `ADD.l`, …), plus `ILLEGAL_LINEA`,
`ILLEGAL_LINEF`, `STOP`, `RESET`, `TRAP`, `TRAPV`, `RTE`, the `to CCR`/`to
SR` forms and `MOVEfromSR`/`MOVEtoUSP` etc. Known limits from the README
and the issue tracker:

- Address-error transactions are typed `re`/`we` ("On real m68k, they still
  happen, AS just isn't asserted, so the results aren't committed").
- "TAS doesn't properly handle the special 5-cycle TAS read-modify-write
  timing."
- "There's some strange issue I don't understand with the TRAPV tests."
- Issue #2: about half the cases have the T bit set and `final` is captured
  before the trace exception.
- Issue #3: no divide-by-zero case; no `DIVU` edge case with dividend =
  divisor << 16.
- Issue #4 (closed): `61FF` is `BSR -1` on the 68000, not a long branch.
- "Any bugs that exist in Mame's microcoded M68000 emulator will exist here
  too."

**Record shape.** The container is a binary the repository's `decode.py`
turns into JSON; the fetch script walks the same structure. Little-endian
throughout. File: `u32 magic 0x1A3F5D71, u32 count`, then `count` tests.
Test: `u32 bytes, u32 magic 0xABC12367`; name (`u32 bytes, u32 0x89ABCDEF,
u32 len, utf-8`); initial state; final state; transactions. State: `u32
bytes, u32 0x01234567`, nineteen `u32` registers in the order `d0–d7,
a0–a6, usp, ssp, sr, pc`, two `u32` prefetch words, `u32 n` then `n` pairs
of `u32 address, u16 word`. Transactions: `u32 bytes, u32 0x456789AB, u32
cycles, u32 n`, then `n` entries of `u8 kind, u32 cycles` followed, when
`kind != 0`, by `u32 fc, u32 address, u32 data, u32 uds, u32 lds`. Kinds:
0 idle (`n`), 1 write, 2 read, 3 TAS RMW, 4 read address error, 5 write
address error. Decoded, the first case of `NOP.json.bin` is:

```text
name       "000 NOP 4e71"
initial    d0..d7, a0..a6, usp 0x72F162, ssp 0x2A3682, sr 0x0309, pc 0xDE9EC,
           prefetch [0x4E71, 0xD8B0],
           ram [[0xDE9E8, 0x4E71], [0xDE9EA, 0xD8B0], [0xDE9EC, 0x326B]]
final      pc 0xDE9EE, sr 0x0309, prefetch [0xD8B0, 0x326B]
cycles     4
transactions [["r", 4, fc 2, 0xDE9EC, ".w", 0x326B, uds 1, lds 1]]
```

Two conventions to get right: `pc` is MAME's `m_au`, "next prefetch
address", **the instruction's address + 4**, so the opcode word is at
`pc - 4` and equals `prefetch[0]`; and `ram` holds 16-bit words at even
addresses (the `decode.py` output splits them into bytes; `tests/corpus.py`
does not). The data bus for a byte access carries the byte in the
half the strobes select (`0xAB00` for an upper-byte read), as on the pins.

## T3: SingleStepTests/680x0 (Tom Harte)

<https://github.com/SingleStepTests/680x0>. **No license file**; issue #1
("License", 2024-06-06) is open with no reply. README: "To generate each
test set, an implementation is used that: conforms to all available
documentation, official and third-party; passes all other published test
sets; and has been verified by usage in an emulated machine." That is the
author's own emulator (CLK); no hardware run is claimed. Fetched only for
counting and as a detector; nothing from it is copied into this repository,
and the fetch script requires `--with-680x0` to get it:

```text
SingleStepTests/680x0 @ e0d5ece9670205cc84a0101081837deb446f86a3
  files: 124  cases: 1000060  bytes: 202591395
```

124 `68000/v1/*.json.gz` files of 8,065 cases each (the tree's 125th entry
is a README), 202,591,395 bytes compressed. It lacks `ILLEGAL_LINEA`,
`ILLEGAL_LINEF` and `STOP`, which the m68000 corpus has, and has the two
known-bad `ASL.b` cases of issue #4 plus the ASR.b question above. Its
`map/68000.official.json` (1.6 MB) maps all 65,536 opcode words to a
mnemonic-and-mode string or `None`; 19,721 are `None`. That map is useful
independent of the test data.

**Record shape** (plain JSON list per file). First case of `NOP.json.gz`:

```json
{"name": "4e71 [NOP] 1",
 "initial": {"d0": 1684444070, ..., "a6": 2013915490, "usp": 1469987768,
             "ssp": 2048, "sr": 9985, "pc": 3072, "prefetch": [20081, 10835],
             "ram": [[3077, 121], [3076, 6]]},
 "final":   {..., "pc": 3074, "prefetch": [10835, 1657], "ram": [[3077, 121], [3076, 6]]},
 "length": 4,
 "transactions": [["r", 4, 6, 3076, ".w", 1657]]}
```

Here `pc` **is** the instruction's address, `ram` is byte-addressed, and a
transaction is `[kind, cycles, function code, address, size, value]` with no
strobe fields; a byte value is the byte, not the bus half. The two corpora
therefore need two small adapters, not one.

## T3: MAME 0.285 as a trace oracle

`/usr/games/mame` reports `0.285 (unknown)`. Its default `M68000` device is
the microcoded core (Olivier Galibert, `m68000gen.py` generates the handlers
from the microcode and nanocode tables it embeds; `m68000musashi.cpp` keeps
the old core as an alternative device). A whole-game trace from a System
16 board is the long-sequence check this project uses in the role ZEXALL
plays for z80-python (rung 4 above): not a hardware claim, but millions of
instructions of real code with real interrupt timing. The recipe, a
verified run, and the register names are in [mame-oracle](mame-oracle.md).

## Manuals

PRM (M68000PRM/AD Rev 1, 1992) and UM (M68000UM/AD Rev 1, 1993), both from
nxp.com, cited by section in [start-here](start-here.md) and
[timing](timing.md). They are documentation: the authority for documented
behavior, silent or "undefined" on the rest, and known to carry
typographical errors in the timing tables. Not an oracle tier.

## Certification ladder

In the order the [handoff brief](history/handoff-brief.md) prescribed, with status:

1. SingleStepTests/m68000, rung-1 files (NOP, MOVEQ, Bcc, RTS, MOVE): pass.
2. BCD tables (T1): pass.
3. SingleStepTests/m68000 (T3, microcode), all 127 files: pass, no exclusions.
4. MAME trace lockstep (T3): 24,595,631 instructions of System 16B Altered
   Beast and 28,249,660 of Genesis Altered Beast identical.
5. SingleStepTests/680x0 (T3) as a detector: 787,660 of 1,000,060 agree,
   every disagreement named; stacked PCs of operand faults partly open.
6. Interrupts and STOP: 12 scenarios, consistent with the manual and MAME.
   (Coverage and mutation, 2026-09-21: every defined first word executed by
   the suite; 174 of 176 mutants killed, the two survivors equivalent; see
   [coverage](coverage.md) and [mutation](mutation.md).)
7. Referees (2026-09-21, [referees](referees.md)): WinUAE's CPU-tester core
   (T2 in scope) and Musashi (T3) built and run; calibrated against the gate
   (97.9% and 98.2% of judged cases, every residual named); the open
   questions and the 680x0 table re-derived by running.
8. WinUAE `cputest` on real hardware (T2 to T1 for the covered cases): when
   an Amiga is available.

A claim without the pins in the summary table is not reproducible; state
them.
