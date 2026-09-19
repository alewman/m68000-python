# Validation: the certification record, and the oracles behind it

## Claim

`m68000-python` agrees with the **hardware-captured** BCD tables of
flamewing's verifier on every input of `ABCD`, `SBCD` and `NBCD` (result and
all five flags), and with **every case** of the pinned, **microcode-derived**
SingleStepTests/m68000 corpus: 317,500 of 317,500, each compared on
registers, SR, both stack pointers, the prefetch queue, RAM, the clock total
and the ordered bus transactions with their function codes. No case is
excluded. Everything beyond BCD therefore rests on an emulator-derived
oracle (MAME 0.285's microcode transcription): a strong detector, not a
hardware judgement. Not yet run: the MAME whole-game lockstep (rung 4), the
680x0 corpus as a detector (rung 5), and the interrupt scenarios (rung 6);
see [worklog](worklog.md) for where each stands.

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
  `1977af501f6c3389c2eefe119ecb10c82d6582f3`, T2), so all 2,500 TAS cases are
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
| WinUAE `cputest` and its 68000 core | T2 | GPL-2.0+ | `tonioni/WinUAE` master (not pinned; pin when used) | Integer instructions, undefined flags, address/bus error frames, cycle counts (7 MHz Amiga) | Not fetched; needs a Windows build and an Amiga |
| SingleStepTests/m68000 | T3 (microcode-derived) | MIT | `64b253116a3de04aaac4346c43680960dc9b67e5` (2024-08-01) | 127 files, 317,500 cases, registers + RAM + prefetch + bus transactions + cycles | **Gate: 317,500 / 317,500** |
| MAME 0.285 microcoded 68000 | T3 (microcode-derived) | BSD-3-Clause core in GPL-2.0+ MAME | `mame0285` = `3bd358f74ce504be519247ac9eddff4d6b46cb70`; `/usr/games/mame` 0.285 | Whole-game traces, see [mame-oracle](mame-oracle.md) | **Trace run verified** |
| SingleStepTests/680x0 (Harte) | T3 | **none** (issue #1 open) | `e0d5ece9670205cc84a0101081837deb446f86a3` (2024-05-14) | 124 files, 1,000,060 cases, registers + RAM + prefetch + transactions + cycles | **Fetched and counted**, detector only |
| Musashi | T3 | MIT | `313ebf1bd9f4d0d93341eb5ce21fd8a119e9dbdd` (2026-03-08) | Reference reading for undefined-flag choices | Not fetched |
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
expected tables are generated by the source; a Python port of the table
generator, with the rule stated in [undocumented-behavior](undocumented-behavior.md),
is the planned T1 gate for the three instructions. Limits: only BCD; only
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

What this repository can use without an Amiga: the 68000 branches of
`setdivuflags`, `setdivsflags`, `setchkundefinedflags` in
`newcpu_common.cpp`, quoted in [undocumented-behavior](undocumented-behavior.md),
and the exception-frame code. What it cannot claim: a hardware run of its
own. The published test-data license is not stated in the readme; nothing
of it is copied here.

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
addresses (the `decode.py` output splits them into bytes, this project's
runner will not). The data bus for a byte access carries the byte in the
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
16 board is the long-sequence check this project will use in the role
ZEXALL plays for z80-python: not a hardware claim, but millions of
instructions of real code with real interrupt timing. The recipe, a
verified run, and the register names are in [mame-oracle](mame-oracle.md).

## Manuals

PRM (M68000PRM/AD Rev 1, 1992) and UM (M68000UM/AD Rev 1, 1993), both from
nxp.com, cited by section in [start-here](start-here.md) and
[timing](timing.md). They are documentation: the authority for documented
behavior, silent or "undefined" on the rest, and known to carry
typographical errors in the timing tables. Not an oracle tier.

## Certification ladder

In the order the [handoff brief](handoff-brief.md) prescribes, with status:

1. SingleStepTests/m68000, rung-1 files (NOP, MOVEQ, Bcc, RTS, MOVE): pass.
2. BCD tables (T1): pass.
3. SingleStepTests/m68000 (T3, microcode), all 127 files: pass, no exclusions.
4. MAME trace lockstep (T3): a System 16 game and a Mega Drive game, N
   million instructions, registers per instruction: see the worklog.
5. SingleStepTests/680x0 (T3) as a detector: see the worklog.
6. Interrupts and STOP scenarios: see the worklog.
7. WinUAE `cputest` on real hardware (T2 to T1 for the covered cases): when
   an Amiga is available.

A claim without the pins in the summary table is not reproducible; state
them.
