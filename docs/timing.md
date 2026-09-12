# Timing: clock counts the core will return

`step()` in this project's cores returns the documented cycle total of the
instruction it ran, and the vector gate compares that number against the
oracle's `length`/`num_cycles` for every case. This page restates the 68000
tables from the User's Manual so the future handlers can cite a row, then
says what the prefetch queue does to those numbers, and what an arcade host
does with them.

Source for every table below: *M68000 8-/16-/32-Bit Microprocessors User's
Manual* (M68000UM/AD Rev 1, 1993), Section 8, "16-Bit Instruction Execution
Times", Tables 8-1 to 8-14,
<https://www.nxp.com/docs/en/reference-manual/MC68000UM.pdf>. Restated, not
copied: the layout is changed and the footnotes are paraphrased. The
notation is the manual's: `n(r/w)` is `n` clock periods of which `r` are
read bus cycles and `w` write bus cycles, each bus cycle being 4 clocks with
no wait states. `+` means "add the effective-address time from Table 8-1".

The tables are documentation, not an oracle. Where the manual and the
microcode-derived corpus disagree (the manual has typographical errors, and
its DIVS/DIVU and MULS/MULU rows are maxima), the corpus wins and the
disagreement gets a line in [undocumented-behavior](undocumented-behavior.md).

## Table 8-1: effective-address calculation

| Mode | Byte, Word | Long |
| --- | --- | --- |
| `Dn`, `An` | 0(0/0) | 0(0/0) |
| `(An)` | 4(1/0) | 8(2/0) |
| `(An)+` | 4(1/0) | 8(2/0) |
| `-(An)` | 6(1/0) | 10(2/0) |
| `(d16,An)` | 8(2/0) | 12(3/0) |
| `(d8,An,Xn)` | 10(2/0) | 14(3/0) |
| `(xxx).W` | 8(2/0) | 12(3/0) |
| `(xxx).L` | 12(3/0) | 16(4/0) |
| `(d16,PC)` | 8(2/0) | 12(3/0) |
| `(d8,PC,Xn)` | 10(2/0) | 14(3/0) |
| `#<data>` | 4(1/0) | 8(2/0) |

The size of Xn (word or long) does not change the time. The totals include
fetching the extension words and reading the operand; `-(An)` costs 2 idle
clocks more than `(An)+` for the decrement.

## Tables 8-2 and 8-3: MOVE

`MOVE` is 4(1/0) plus the source EA time from Table 8-1 plus a destination
cost: 0 for `Dn`/`An`; 4(0/1) byte/word or 8(0/2) long for `(An)`, `(An)+`
and `-(An)` (the destination predecrement is *not* charged the 2 idle
clocks); 8(1/1) / 12(1/2) for `(d16,An)` and `(xxx).W`; 10(1/1) / 14(1/2)
for `(d8,An,Xn)`; 12(2/1) / 16(2/2) for `(xxx).L`. The manual prints the
full matrices; both are restated here because handlers will cite cells.

Byte and word (Table 8-2), rows are the source, columns the destination:

| Source \ Dest | Dn | An | (An) | (An)+ | -(An) | (d16,An) | (d8,An,Xn) | (xxx).W | (xxx).L |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dn | 4(1/0) | 4(1/0) | 8(1/1) | 8(1/1) | 8(1/1) | 12(2/1) | 14(2/1) | 12(2/1) | 16(3/1) |
| An | 4(1/0) | 4(1/0) | 8(1/1) | 8(1/1) | 8(1/1) | 12(2/1) | 14(2/1) | 12(2/1) | 16(3/1) |
| (An) | 8(2/0) | 8(2/0) | 12(2/1) | 12(2/1) | 12(2/1) | 16(3/1) | 18(3/1) | 16(3/1) | 20(4/1) |
| (An)+ | 8(2/0) | 8(2/0) | 12(2/1) | 12(2/1) | 12(2/1) | 16(3/1) | 18(3/1) | 16(3/1) | 20(4/1) |
| -(An) | 10(2/0) | 10(2/0) | 14(2/1) | 14(2/1) | 14(2/1) | 18(3/1) | 20(3/1) | 18(3/1) | 22(4/1) |
| (d16,An) | 12(3/0) | 12(3/0) | 16(3/1) | 16(3/1) | 16(3/1) | 20(4/1) | 22(4/1) | 20(4/1) | 24(5/1) |
| (d8,An,Xn) | 14(3/0) | 14(3/0) | 18(3/1) | 18(3/1) | 18(3/1) | 22(4/1) | 24(4/1) | 22(4/1) | 26(5/1) |
| (xxx).W | 12(3/0) | 12(3/0) | 16(3/1) | 16(3/1) | 16(3/1) | 20(4/1) | 22(4/1) | 20(4/1) | 24(5/1) |
| (xxx).L | 16(4/0) | 16(4/0) | 20(4/1) | 20(4/1) | 20(4/1) | 24(5/1) | 26(5/1) | 24(5/1) | 28(6/1) |
| (d16,PC) | 12(3/0) | 12(3/0) | 16(3/1) | 16(3/1) | 16(3/1) | 20(4/1) | 22(4/1) | 20(4/1) | 24(5/1) |
| (d8,PC,Xn) | 14(3/0) | 14(3/0) | 18(3/1) | 18(3/1) | 18(3/1) | 22(4/1) | 24(4/1) | 22(4/1) | 26(5/1) |
| #<data> | 8(2/0) | 8(2/0) | 12(2/1) | 12(2/1) | 12(2/1) | 16(3/1) | 18(3/1) | 16(3/1) | 20(4/1) |

Long (Table 8-3):

| Source \ Dest | Dn | An | (An) | (An)+ | -(An) | (d16,An) | (d8,An,Xn) | (xxx).W | (xxx).L |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dn | 4(1/0) | 4(1/0) | 12(1/2) | 12(1/2) | 12(1/2) | 16(2/2) | 18(2/2) | 16(2/2) | 20(3/2) |
| An | 4(1/0) | 4(1/0) | 12(1/2) | 12(1/2) | 12(1/2) | 16(2/2) | 18(2/2) | 16(2/2) | 20(3/2) |
| (An) | 12(3/0) | 12(3/0) | 20(3/2) | 20(3/2) | 20(3/2) | 24(4/2) | 26(4/2) | 24(4/2) | 28(5/2) |
| (An)+ | 12(3/0) | 12(3/0) | 20(3/2) | 20(3/2) | 20(3/2) | 24(4/2) | 26(4/2) | 24(4/2) | 28(5/2) |
| -(An) | 14(3/0) | 14(3/0) | 22(3/2) | 22(3/2) | 22(3/2) | 26(4/2) | 28(4/2) | 26(4/2) | 30(5/2) |
| (d16,An) | 16(4/0) | 16(4/0) | 24(4/2) | 24(4/2) | 24(4/2) | 28(5/2) | 30(5/2) | 28(5/2) | 32(6/2) |
| (d8,An,Xn) | 18(4/0) | 18(4/0) | 26(4/2) | 26(4/2) | 26(4/2) | 30(5/2) | 32(5/2) | 30(5/2) | 34(6/2) |
| (xxx).W | 16(4/0) | 16(4/0) | 24(4/2) | 24(4/2) | 24(4/2) | 28(5/2) | 30(5/2) | 28(5/2) | 32(6/2) |
| (xxx).L | 20(5/0) | 20(5/0) | 28(5/2) | 28(5/2) | 28(5/2) | 32(6/2) | 34(6/2) | 32(6/2) | 36(7/2) |
| (d16,PC) | 16(4/0) | 16(4/0) | 24(4/2) | 24(4/2) | 24(4/2) | 28(5/2) | 30(5/2) | 28(5/2) | 32(6/2)* |
| (d8,PC,Xn) | 18(4/0) | 18(4/0) | 26(4/2) | 26(4/2) | 26(4/2) | 30(5/2) | 32(5/2) | 30(5/2) | 34(6/2) |
| #<data> | 12(3/0) | 12(3/0) | 20(3/2) | 20(3/2) | 20(3/2) | 24(4/2) | 26(4/2) | 24(4/2) | 28(5/2) |

`*` The manual prints `32(5/2)` for `(d16,PC)` to `(xxx).L`; the additive
rule and the neighbouring cells give `32(6/2)`. Treated as a typographical
error; the corpus decides.

## Table 8-4: standard two-operand instructions

| Instruction | Size | `op <ea>,An` | `op <ea>,Dn` | `op Dn,<M>` |
| --- | --- | --- | --- | --- |
| ADD/ADDA | B, W | 8(1/0)+ | 4(1/0)+ | 8(1/1)+ |
| | L | 6(1/0)+ ** | 6(1/0)+ ** | 12(1/2)+ |
| AND | B, W | — | 4(1/0)+ | 8(1/1)+ |
| | L | — | 6(1/0)+ ** | 12(1/2)+ |
| CMP/CMPA | B, W | 6(1/0)+ | 4(1/0)+ | — |
| | L | 6(1/0)+ | 6(1/0)+ | — |
| DIVS | — | — | 158(1/0)+ * | — |
| DIVU | — | — | 140(1/0)+ * | — |
| EOR | B, W | — | 4(1/0) *** | 8(1/1)+ |
| | L | — | 8(1/0) *** | 12(1/2)+ |
| MULS | — | — | 70(1/0)+ * | — |
| MULU | — | — | 70(1/0)+ * | — |
| OR | B, W | — | 4(1/0)+ | 8(1/1)+ |
| | L | — | 6(1/0)+ ** | 12(1/2)+ |
| SUB/SUBA | B, W | 8(1/0)+ | 4(1/0)+ | 8(1/1)+ |
| | L | 6(1/0)+ ** | 6(1/0)+ ** | 12(1/2)+ |

`*` maximum; `**` the base of 6 becomes 8 when the EA is register direct or
immediate (EA time is still added); `***` `EOR` to Dn is only `Dn,Dn`.
Multiply is 38 + 2n clocks, n = number of 1 bits in the source for `MULU`,
number of `01`/`10` transitions in the 17-bit value (source with a 0
appended) for `MULS`, worst case `$5555`. Divide is data-dependent within
"less than 10%" per the manual; the exact algorithm is Jorge Cwik's
`getDivu68kCycles`/`getDivs68kCycles` (2005, GPL-2.0+, carried in WinUAE
`newcpu_common.cpp`): DIVU overflow always 10, else 76–136; DIVS absolute
overflow 16–18, else 120–156. The corpus records the exact count per case.

## Table 8-5: immediate

| Instruction | Size | `op #,Dn` | `op #,An` | `op #,M` |
| --- | --- | --- | --- | --- |
| ADDI | B, W | 8(2/0) | — | 12(2/1)+ |
| | L | 16(3/0) | — | 20(3/2)+ |
| ADDQ | B, W | 4(1/0) | 4(1/0)* | 8(1/1)+ |
| | L | 8(1/0) | 8(1/0) | 12(1/2)+ |
| ANDI | B, W | 8(2/0) | — | 12(2/1)+ |
| | L | 14(3/0) | — | 20(3/2)+ |
| CMPI | B, W | 8(2/0) | — | 8(2/0)+ |
| | L | 14(3/0) | — | 12(3/0)+ |
| EORI | B, W | 8(2/0) | — | 12(2/1)+ |
| | L | 16(3/0) | — | 20(3/2)+ |
| MOVEQ | L | 4(1/0) | — | — |
| ORI | B, W | 8(2/0) | — | 12(2/1)+ |
| | L | 16(3/0) | — | 20(3/2)+ |
| SUBI | B, W | 8(2/0) | — | 12(2/1)+ |
| | L | 16(3/0) | — | 20(3/2)+ |
| SUBQ | B, W | 4(1/0) | 8(1/0)* | 8(1/1)+ |
| | L | 8(1/0) | 8(1/0) | 12(1/2)+ |

`*` word only. Note the manual's asymmetry: `ADDQ.W #,An` is 4 and
`SUBQ.W #,An` is 8; both long forms are 8. The corpus decides.

## Table 8-6: single operand

| Instruction | Size | Register | Memory |
| --- | --- | --- | --- |
| CLR | B, W | 4(1/0) | 8(1/1)+ |
| | L | 6(1/0) | 12(1/2)+ |
| NBCD | B | 6(1/0) | 8(1/1)+ |
| NEG, NEGX, NOT | B, W | 4(1/0) | 8(1/1)+ |
| | L | 6(1/0) | 12(1/2)+ |
| Scc | B, false | 4(1/0) | 8(1/1)+ |
| | B, true | 6(1/0) | 8(1/1)+ |
| TAS | B | 4(1/0) | 14(2/1)+ |
| TST | B, W, L | 4(1/0) | 4(1/0)+ |

`CLR` on memory reads the operand before writing it (the 8(1/1) includes
that read), an observable bus transaction on hosts with read-sensitive
registers.

## Table 8-7: shifts and rotates

| Instruction | Size | Register | Memory |
| --- | --- | --- | --- |
| ASL, ASR, LSL, LSR, ROL, ROR, ROXL, ROXR | B, W | 6+2n(1/0) | 8(1/1)+ |
| | L | 8+2n(1/0) | — |

`n` is the shift count, 0–63 from a register (count mod 64) or 1–8
immediate. Memory forms shift by exactly one, word size only.

## Table 8-8: bit manipulation

| Instruction | Size | Dynamic (`Dn,<ea>`) register / memory | Static (`#n,<ea>`) register / memory |
| --- | --- | --- | --- |
| BCHG | B (memory) / L (register) | 8(1/0)* / 8(1/1)+ | 12(2/0)* / 12(2/1)+ |
| BCLR | | 10(1/0)* / 8(1/1)+ | 14(2/0)* / 12(2/1)+ |
| BSET | | 8(1/0)* / 8(1/1)+ | 12(2/0)* / 12(2/1)+ |
| BTST | | 6(1/0) / 4(1/0)+ | 10(2/0) / 8(2/0)+ |

`*` maximum; the register forms cost 2 fewer clocks when the bit number is
below 16 (the corpus confirms which).

## Table 8-9: conditional and branch

| Instruction | Displacement | Taken | Not taken |
| --- | --- | --- | --- |
| Bcc | byte | 10(2/0) | 8(1/0) |
| | word | 10(2/0) | 12(2/0) |
| BRA | byte, word | 10(2/0) | — |
| BSR | byte, word | 18(2/2) | — |
| DBcc | cc true | — | 12(2/0) |
| | cc false, count not expired | 10(2/0) | — |
| | cc false, count expired | — | 14(3/0) |

## Table 8-10: JMP, JSR, LEA, PEA, MOVEM

| Instruction | (An) | (An)+ | -(An) | (d16,An) | (d8,An,Xn) | (xxx).W | (xxx).L | (d16,PC) | (d8,PC,Xn) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| JMP | 8(2/0) | — | — | 10(2/0) | 14(3/0) | 10(2/0) | 12(3/0) | 10(2/0) | 14(3/0) |
| JSR | 16(2/2) | — | — | 18(2/2) | 22(2/2) | 18(2/2) | 20(3/2) | 18(2/2) | 22(2/2) |
| LEA | 4(1/0) | — | — | 8(2/0) | 12(2/0) | 8(2/0) | 12(3/0) | 8(2/0) | 12(2/0) |
| PEA | 12(1/2) | — | — | 16(2/2) | 20(2/2) | 16(2/2) | 20(3/2) | 16(2/2) | 20(2/2) |
| MOVEM M→R, word | 12+4n(3+n/0) | 12+4n(3+n/0) | — | 16+4n(4+n/0) | 18+4n(4+n/0) | 16+4n(4+n/0) | 20+4n(5+n/0) | 16+4n(4+n/0) | 18+4n(4+n/0) |
| MOVEM M→R, long | 12+8n(3+2n/0) | 12+8n(3+2n/0) | — | 16+8n(4+2n/0) | 18+8n(4+2n/0) | 16+8n(4+2n/0) | 20+8n(5+2n/0) | 16+8n(4+2n/0) | 18+8n(4+2n/0) |
| MOVEM R→M, word | 8+4n(2/n) | — | 8+4n(2/n) | 12+4n(3/n) | 14+4n(3/n) | 12+4n(3/n) | 16+4n(4/n) | — | — |
| MOVEM R→M, long | 8+8n(2/2n) | — | 8+8n(2/2n) | 12+8n(3/2n) | 14+8n(3/2n) | 12+8n(3/2n) | 16+8n(4/2n) | — | — |

`n` is the number of registers moved. The memory-to-register read counts
(`3+n`) include one read more than the registers: the 68000 reads one extra
word past the last register (the well-known MOVEM extra read; the corpus
transactions show it; see [undocumented-behavior](undocumented-behavior.md)).

## Table 8-11: multiprecision

| Instruction | Size | `op Dn,Dn` | `op M,M` |
| --- | --- | --- | --- |
| ADDX, SUBX | B, W | 4(1/0) | 18(3/1) |
| | L | 8(1/0) | 30(5/2) |
| CMPM | B, W | — | 12(3/0) |
| | L | — | 20(5/0) |
| ABCD, SBCD | B | 6(1/0) | 18(3/1) |

## Tables 8-12 and 8-13: miscellaneous, MOVEP

| Instruction | Register | Memory |
| --- | --- | --- |
| ANDI/EORI/ORI to CCR or SR | 20(3/0) | — |
| CHK (no trap) | 10(1/0)+ | — |
| MOVE from SR | 6(1/0) | 8(1/1)+ |
| MOVE to CCR | 12(1/0) | 12(1/0)+ |
| MOVE to SR | 12(2/0) | 12(2/0)+ |
| EXG | 6(1/0) | — |
| EXT (W, L) | 4(1/0) | — |
| LINK | 16(2/2) | — |
| MOVE from USP, MOVE to USP | 4(1/0) | — |
| NOP | 4(1/0) | — |
| RESET | 132(1/0) | — |
| RTE | 20(5/0) | — |
| RTR | 20(2/0) | — |
| RTS | 16(4/0) | — |
| STOP | 4(0/0) | — |
| SWAP | 4(1/0) | — |
| TRAPV (no trap) | 4(1/0) | — |
| UNLK | 12(3/0) | — |
| MOVEP word | R→M 16(2/2) | M→R 16(4/0) |
| MOVEP long | R→M 24(2/4) | M→R 24(6/0) |

## Table 8-14: exception processing

Totals include the stacking, the vector fetch and the fetch of the handler's
first instruction.

| Exception | Clocks |
| --- | --- |
| Address error | 50(4/7) |
| Bus error | 50(4/7) |
| CHK (trap taken) | 40(4/3)+ |
| Divide by zero | 38(4/3)+ |
| Illegal instruction | 34(4/3) |
| Interrupt | 44(5/3), assuming a 4-clock acknowledge cycle |
| Privilege violation | 34(4/3) |
| Reset | 40(6/0), from RESET/HALT negated to the first instruction |
| Trace | 34(4/3) |
| TRAP | 34(4/3) |
| TRAPV (trap taken) | 34(5/3) |

An autovectored interrupt on the real chip takes the VPA path and its
acknowledge cycle is synchronised to the E clock, so the 44 above becomes
44–54 depending on phase; an instruction-level core returns a fixed number
and says so (z80-python's convention). What the MAME core does here is a
question for the trace run in [mame-oracle](mame-oracle.md).

## What prefetch does to these numbers

Every `n(r/w)` above already contains the instruction's own opcode fetch
*and* the fetch that refills the queue for the next instruction; that is
why `NOP` is 4(1/0) with one read at PC+4 and not two reads. Consequences a
core must reproduce to match the corpus `length` and transaction list:

- Extension words are not "fetched then used": they are in the queue when
  the instruction starts, and the reads the table counts happen at the
  positions the microcode fixes, interleaved with operand accesses. The
  `transactions` field of both corpora orders them; `(d16,An)` for example
  reads the displacement word before the operand, and `MOVE (xxx).L,(xxx).L`
  reads both source words, then the operand, then both destination words,
  then writes.
- Taken branches throw the queue away and refill it (the two reads in
  `Bcc` taken, 10(2/0)); not-taken byte branches keep it (8(1/0)); a
  not-taken word branch has to fetch past the displacement (12(2/0)).
- `JMP`/`JSR`/`RTS` refill from the target, which is why `RTS` is 16(4/0):
  two pops and two prefetches.
- The address-error frame's stacked PC depends on how far the queue had
  advanced, which is why UM 6.2.5 calls it unpredictable and why the corpus
  is the only practical source for it.

The corpus `length` is the total for the instruction *including* any
exception it raised in the same step (the address-error cases carry the
50-clock frame push); a core that reports the instruction and the exception
as two boundaries must sum them when comparing.

## What arcade hosts need

The host schedules everything from the cycle totals the core returns. The
numbers below are from MAME 0.285 driver sources, restated (BSD-3-Clause
files in the GPL-2.0+ MAME tree; commit `3bd358f` is tag `mame0285`):

**Sega System 16B** (`src/mame/sega/segas16b.cpp`, e.g. `altbeast`,
`goldnaxe`, `shinobi2`):

- `MASTER_CLOCK_10MHz = XTAL(20'000'000) / 2`; `M68000(config, m_maincpu, MASTER_CLOCK_10MHz)`.
  The 68000 runs at **10 MHz**.
- Z80 sound CPU at `MASTER_CLOCK_10MHz/2` = 5 MHz; YM2151 at 8 MHz / 2.
- Screen: `set_raw(MASTER_CLOCK_25MHz/4, 400, 0, 320, 262, 0, 224)` with
  `MASTER_CLOCK_25MHz = XTAL(25'174'800)`: a 6.2937 MHz pixel clock, 400
  pixels by 262 lines per frame, 320×224 visible, so **60.054 Hz** and
  15,734 Hz line rate; **166,517 CPU clocks per frame**, 636 per line.
- `m_maincpu->set_vblank_int("screen", FUNC(segas16b_state::irq4_line_hold))`:
  one **level-4 interrupt per vblank**, asserted with `HOLD_LINE` (held
  until acknowledged), **autovectored** (vector 28 at 0x70). Some boards add
  an i8751 MCU whose vblank hook the driver simulates.
- Memory is 24-bit with a 315-5195 mapper device in front of the 68000;
  FD1089/FD1094 sets have encrypted program ROMs the driver decrypts. The
  core sees none of this: the host owns the map.

**Sega System 16A** (`src/mame/sega/segas16a.cpp`, e.g. `shinobi`,
`alexkidd`): `M68000(config, m_maincpu, 10000000)`, same `irq4_line_hold`
on vblank; the Z80 is 4 MHz and the sound path goes through an NEC 7751.
`shinobi` in MAME is the System 16A set, which is why its `-listxml` shows
a 4 MHz Z80; `altbeast` is 16B.

Other 68000 boards this core is meant for use the same shape with other
numbers: CPS-1 (`capcom/cps1.cpp`) runs the 68000 at 10 MHz (12 MHz on
some) with a level-2 vblank interrupt; Neo Geo (`neogeo/neogeo.cpp`) at 12
MHz with level 1 vblank and level 2 timer interrupts; Atari System 1 at 7.16
MHz with several levels; Williams/Midway Y-unit at 12 MHz. Each is one
driver file to read when its host is written. The host contract is the one
z80-python and 6502-python use: the core returns clocks per step; the host
counts down to the next scanline or vblank, raises or lowers the IPL level
between steps, and answers the acknowledge with "autovector".
