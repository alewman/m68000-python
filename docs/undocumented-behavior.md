# Undocumented behavior: undefined on paper, deterministic on silicon

The Programmer's Reference Manual marks a handful of results "undefined"
(PRM Table 3-18 uses `U`; UM 6.2.5 says "unpredictable"). The silicon does
one specific thing in each case, real programs occasionally depend on it,
and every oracle in [validation](validation.md) has to take a position. This
page lists each behavior, what each source says it is, and the tier of the
evidence, so the future handler comments can point at a line here. Where
only inference is available the item is marked `[unverified]`; where an
emulator's choice is the only account, it says so.

Tiers (from [validation](validation.md)): **T1** hardware-captured, **T2**
hardware-corrected emulator, **T3** emulator-derived. A T3 source can raise
a question; it cannot settle one.

Sources named on this page, with licenses:

- **WinUAE** `newcpu_common.cpp` (`setdivuflags`, `setdivsflags`,
  `setchkundefinedflags`, Toni Wilen; GPL-2.0+),
  <https://github.com/tonioni/WinUAE>. Its 68000 core is exercised by
  `cputest` on real Amigas (readme: "68000: Complete. Including bus and
  address error stack frame/register/CCR modification undocumented
  behavior. Full cycle count support."), so its 68000 branch is **T2**.
- **Musashi** `m68k_in.c` (Karl Stenerud; MIT per `readme.txt`; `master`
  at `313ebf1`, 2026-03-08), <https://github.com/kstenerud/Musashi>. Pure
  emulator, **T3**; it is the core MAME used before 2023 and the one many
  arcade emulators still use.
- **MAME 0.285** microcoded core (`src/devices/cpu/m68000/m68000gen.py`,
  Olivier Galibert, BSD-3-Clause; introduced in commit `74971c2`,
  2023-02-22, "New implementation, generated from the micro/nanocode"). The
  generator embeds the microcode and nanocode ROM contents transcribed from
  a die photograph. Still an emulator, so **T3**, but one whose undefined
  results are not choices: they fall out of the transcribed microcode.
- **flamewing/68k-bcd-verifier** (GPL-3.0, commit `39a01be`, 2018-08-31):
  exhaustive ABCD/SBCD/NBCD tables captured from a Model 1 Sega Genesis and
  confirmed on a Model 3 VA2. **T1**.
- **SingleStepTests/m68000** (MIT) and **SingleStepTests/680x0** (no
  license): the corpora, T3, pinned in [validation](validation.md).
- **PRM** and **UM**: the Motorola manuals cited in [start-here](start-here.md).

## Flags after DIVU overflow

PRM: N and Z "undefined if overflow or divide by zero occurs"; V set; C
cleared (PRM 4, DIVU). Overflow means the quotient does not fit in 16 bits;
the destination register is unchanged.

| Source | Tier | 68000 result |
| --- | --- | --- |
| WinUAE `setdivuflags` | T2 | `V=1, N=1, Z=0, C=0` (comment: "68000: V=1, N=1, C=0, Z=0"; the 68010 differs, N depends on the operand signs) |
| Musashi `divu` | T3 | `V=1`; N, Z, C **unchanged** |
| MAME microcoded / m68000 corpus | T3 | as the microcode computes; `DIVU.json.bin` records it |

WinUAE's release notes (3.6.0, 2018-01-18) describe the 68020+ variants as
newly emulated and the 68000 as already correct ("N is also always set").
The m68000 corpus has no divide-by-zero case (its issue #3), so the trap
path's flags come from WinUAE alone: "DIVU sets Z-flag if dividend upper
word is zero, N-flag if dividend upper word is negative" (WinUAE changelog,
version not pinned here, `[unverified]`).

## Flags after DIVS overflow

| Source | Tier | 68000 result |
| --- | --- | --- |
| WinUAE `setdivsflags` | T2 | `CLEAR_CZNV; V=1; N=1` so `V=1, N=1, Z=0, C=0` |
| Musashi `divs` | T3 | `V=1`, others unchanged; special-cases `$80000000 / -1` as quotient 0 with **Z=1, N=V=C=0** and writes 0 to the register, which no other source does |
| WinUAE cycle model (Cwik) | T2 | "absolute overflow" (|dividend|>>16 ≥ |divisor|) is detected early at 16–18 clocks; signed overflow is not detected prematurely, 120–156 clocks |

Divide by zero: "DIVS always sets Z-flag" per WinUAE's changelog
(`[unverified]`, same caveat as above).

## Flags after CHK

PRM: N set if Dn < 0, cleared if Dn > bound, "undefined otherwise"; Z, V, C
undefined (PRM 4, CHK).

| Source | Tier | 68000 result |
| --- | --- | --- |
| WinUAE `setchkundefinedflags` | T2 | `C=V=0; Z=(Dn==0); N=(Dn<0)` on every path, trap or not (comment: "68000: CV=0. Z: dst==0. N: dst < 0. !N: dst > src.") |
| Musashi `chk` | T3 | `Z=(Dn==0); V=C=0` always; `N=(Dn<0)` only when trapping, unchanged otherwise |

The two agree on trap paths and differ on the non-negative, in-range path
(N cleared vs. unchanged). WinUAE is the higher tier. The stacked PC for
the CHK trap is the next instruction (UM 6.3.5).

## ABCD, SBCD, NBCD: N and V

PRM Table 3-18: X and C are the decimal carry/borrow, Z is sticky, N and V
are `U`. The T1 source is flamewing's exhaustive verifier, whose expected
tables were captured from a Model 1 Genesis; emulators that pass it
(BlastEm, Genesis Plus GX, Higan, BizHawk, Exodus, Mednafen per its README)
and WinUAE (3.6.0 notes: "68000 was already correct") all implement:

- **N** = bit 7 of the corrected result.
- **V** for `ABCD`: set when bit 7 of the *uncorrected* binary sum was 0 and
  bit 7 of the *corrected* result is 1 (the +6 / +$60 adjustment carried
  into the sign). Musashi writes exactly this as `FLAG_V = ~res` before the
  correction and `FLAG_V &= res` after.
- **V** for `SBCD` and `NBCD`: the mirror image, set when the correction
  turned bit 7 from 1 to 0. Musashi: `FLAG_V = res` then `FLAG_V &= ~res`.
- **Z** for `NBCD` of 0 with X clear: Musashi treats result `$9A` (meaning
  no adjustment needed, operand was 0) as a special case that leaves Z
  sticky and clears X, C, V.

Only the *rule* above is T1-backed (the verifier's tables are the rule
evaluated over all 262,144 inputs per instruction); the description of it
in terms of an uncorrected intermediate is Musashi's, `[unverified]` as a
mechanism but not as a result.

## MOVEM with the address register in its own list

Documented, not undocumented, but every core gets it wrong once (PRM 4,
MOVEM, "Description"):

- **Predecrement, register to memory**: "The MC68000 and MC68010 write the
  initial register value (not decremented)"; the 68020 and later write the
  decremented value.
- **Postincrement, memory to register**: "If the addressing register is also
  loaded from memory, the memory value is ignored and the register is
  written with the postincremented effective address."
- **Memory to register reads one extra word** past the last register in the
  list (the Table 8-10 read counts of `3+n` carry it; both corpora record
  the transaction). PRM does not mention it; the corpora and WinUAE do.
  `[unverified]` beyond those sources.

The mask word is bit 0 = D0 … bit 15 = A7 for every mode except
predecrement, where it is reversed (bit 0 = A7 … bit 15 = D0), so the
registers land in memory in the same order either way (PRM 4, MOVEM).

## Odd addresses

Word and long operand accesses, and any instruction fetch, at an odd
address raise an address error (UM 6.3.10). What is deterministic but not
documented:

- **The stacked PC** ("unpredictable", UM 6.2.5). It is the queue's state at
  the moment of the fault, which the microcode fixes per instruction; the
  m68000 corpus records it, WinUAE reproduces it (cputest verifies "68000/010
  bus address error" frames on hardware). Neither Motorola manual gives a
  rule. T2 via WinUAE, T3 via the corpus; `[unverified]` here as a rule.
- **Bits 15–5 of the access-information word** at `SSP+0` are undefined in
  Figure 6-7. WinUAE's cputest readme says the 68000's are "complete"
  including "CCR modification undocumented behavior". This project will
  model whatever the m68000 corpus records and flag the claim as T3 until a
  cputest run on real hardware is available to it.
- **The aborted bus cycle is not asserted.** The m68000 corpus README: "On
  real m68k, they still happen, AS just isn't asserted, so the results
  aren't committed"; the corpus marks them `re`/`we` so a runner can tell a
  faulted access from a completed one. A host never sees a memory read or
  write for the faulting access.
- **Which access faults first** in a multi-access instruction (`MOVE.L
  (odd),(odd)`, `MOVEM`) determines the frame; the transaction order in the
  corpus fixes it.
- **Byte accesses never fault**, and `MOVEP` is byte-wise, so `MOVEP` at an
  odd address is legal (PRM 4, MOVEP).
- **`BSR`/`Bcc` with displacement −1** (`61FF`) is a legal byte displacement
  on the 68000 (the 68020's long form does not exist), branches to an odd
  address, and faults on the fetch; m68000 corpus issue #4 confirms the
  corpus treats it that way.

## Illegal instruction families

UM 6.3.6: any first word that matches no instruction takes vector 4;
`$4AFA`, `$4AFB`, `$4AFC` always do; words with bits 15–12 = `1010` take
vector 10 and `1111` take vector 11. Beyond that:

- **Undefined EA encodings inside valid opcodes** (mode 7 with register
  5–7; `An` as the destination of a data-only instruction; byte size on
  `An`; `MOVE` to `#` or PC-relative) are illegal instructions on the 68000.
  The MAME decode table (`m68000.lst`) leaves them unmapped so they fall to
  the illegal handler; the 680x0 corpus's `map/68000.official.json`
  enumerates 65,536 words of which 19,721 are `None` (undefined). T3;
  `[unverified]` that *every* such word traps identically on silicon, though
  no source claims otherwise.
- **The stacked PC for illegal, A-line and F-line** is the address of the
  offending word itself (so an emulator trap handler can decode it), the
  same as privilege violation (UM 6.3.7) and unlike `TRAP`. UM 6.3.6 only
  says "similar to that for traps". The corpus files `ILLEGAL_LINEA.json.bin`
  and `ILLEGAL_LINEF.json.bin` record it; T3, `[unverified]` against the
  manual's wording.
- **`MOVE from SR` is not privileged on the 68000** (UM 6.3.7 lists it
  "68010 only"); a core that traps it in user mode breaks 68000 software.
- **Bits 10–8 of the brief extension word** are ignored, not trapped (PRM
  2.4).
- **Shift counts** from a register are taken mod 64, and a count of 0 still
  clears C and V and sets N/Z from the unchanged operand (PRM Table 3-18,
  the `(r = 0)` rows); `ROXL`/`ROXR` by 0 copy X into C.

## TAS

`TAS` performs an indivisible read-modify-write bus cycle of 10 clocks (UM
4.1.3, 5.1.3), the only 68000 instruction that does. Some boards do not
complete the write (the Sega Genesis famously does not, because its bus
arbiter does not decode the RMW cycle); that is a host matter, not the
core's. The m68000 corpus README says its TAS timing "doesn't properly
handle the special 5-cycle TAS read-modify-write timing", so `TAS.json.bin`
is a **detector only** for cycle counts, and the flag/result part is T3
like the rest.

## The T bit and STOP

Trace after `STOP`: PRM (STOP) says the T bit set by the immediate causes a
trace exception before the processor stops. The m68000 corpus sets T in
about half of its initial states but captures `final` before the trace
exception is taken (its issue #2), so a runner must either strip T before
comparing or model the exception as a separate boundary. Documented here so
the runner design in [handoff-brief](handoff-brief.md) is not a surprise.

## Where the truth will live

When the core exists, the order of authority is:

1. flamewing's BCD tables (T1) for `ABCD`/`SBCD`/`NBCD`.
2. WinUAE's 68000 branch (T2) for DIV/CHK flags and address-error frames,
   read from source and, when a cputest run on real hardware becomes
   available, from that.
3. The pinned SingleStepTests/m68000 corpus (T3, microcode-derived) for
   everything, including cycle counts and transaction order.
4. Musashi and the 680x0 corpus (T3) as detectors: a disagreement is a
   question to answer with a higher tier, never a verdict.
5. The manuals for documented behavior and as the tie-breaker of last
   resort when two T3 sources disagree and no higher tier speaks.

Every rule adopted from this page gets a comment on the line that
implements it, naming the tier.
