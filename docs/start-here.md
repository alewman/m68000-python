# Start here: the 68000 as this core models it

This page is for someone who has written a Z80 or 6502 interpreter (the two
sibling cores, `z80-python` and `6502-python`) and has never touched a 68000.
It gives the key the source assumes you hold: the register file, the status
register, how a 16-bit opcode word splits into fields, the twelve
effective-address modes and their extension words, the instruction families,
the exception model, and the prefetch queue. The code under
`src/m68000_python/` is the reference; this page is its map, and each
section names the module that implements it.

Every fact names its source. The two Motorola documents are:

- **PRM**: *M68000 Family Programmer's Reference Manual* (M68000PRM/AD Rev 1,
  Motorola 1992), <https://www.nxp.com/docs/en/reference-manual/M68000PRM.pdf>.
  Sections cited as "PRM 2.2".
- **UM**: *M68000 8-/16-/32-Bit Microprocessors User's Manual* (M68000UM/AD
  Rev 1, Motorola 1993), <https://www.nxp.com/docs/en/reference-manual/MC68000UM.pdf>.
  Sections cited as "UM 6.3".

Both are Motorola/NXP copyright, freely downloadable, not redistributable
here; the repository keeps none of their text beyond short quotations.

## Register file

Implemented in `_core.py` (`R`, the sixteen registers; `usp`/`ssp`; `SR`).

| Name | Width | Notes | Source |
| --- | --- | --- | --- |
| D0–D7 | 32 | Data registers. Byte and word operations touch only the low 8 or 16 bits; the rest is preserved | PRM 1.1, 1.7 |
| A0–A6 | 32 | Address registers. Word operations on an An sign-extend to 32 bits (`MOVEA.W`, `ADDA.W`, `SUBA.W`, `CMPA.W`); there are no byte operations on An | PRM 1.1, 2.3 |
| A7 | 32 | The active stack pointer. It is USP in user mode and SSP in supervisor mode; the inactive one is a separate register reachable only by `MOVE USP` (supervisor) | PRM 1.1, 1.3 |
| USP, SSP | 32 | User and supervisor stack pointers; `A7` aliases whichever the S bit selects | PRM 1.3 |
| PC | 32 (24 used) | Program counter. The 68000 drives A23–A1 only; a core must mask addresses to 24 bits when it touches memory and keep the full 32-bit value in the register | UM 3.1, 6.2.1 |
| SR | 16 | Status register; the low byte is the CCR, the high byte is the system byte | PRM 1.1, 1.3 |

The 68000 has no vector base register, no cache, no MMU; those arrive with the
68010 and 68020 and are out of scope (README).

Byte-size operations with `-(A7)` and `(A7)+` move the stack pointer by 2, not
1, to keep it word-aligned (PRM 2.2.4 and 2.2.5). Every core forgets this
once.

## The status register

The bits are constants at the top of `_core.py`; the flag rules of PRM
Table 3-18 are `_flags.py`, the condition tests of Table 3-19 `_flags.CONDITION`.

```text
bit:  15  14  13  12  11  10  9   8   7   6   5   4   3   2   1   0
      T   0   S   0   0   I2  I1  I0  0   0   0   X   N   Z   V   C
      |-------- system byte ----------|  |------------ CCR ------------|
```

- **C** carry/borrow out of the most significant bit of the operation size.
- **V** two's-complement overflow.
- **Z** result is zero. For `ADDX`, `SUBX`, `NEGX`, `ABCD`, `SBCD`, `NBCD`, Z
  is *cleared* if the result is nonzero and otherwise *unchanged*, so a
  multiprecision loop can test the whole number at the end (PRM Table 3-18,
  the "Z = Z ∧ ¬Rm ∧ … ∧ ¬R0" rows).
- **N** most significant bit of the result.
- **X** extend: a copy of C for arithmetic, shifts and rotates that say so,
  and *unchanged* by everything else (`MOVE`, logic, `CMP`, `TST`, `CLR`,
  `NEG` sets it, `ROL`/`ROR` do not). It exists so multiprecision arithmetic
  can be interleaved with instructions that clobber C.
- **I2–I0** the interrupt priority mask. Requests at a level less than or
  equal to the mask are held pending; level 7 is non-maskable (UM 6.3.2).
- **S** supervisor mode when set; selects SSP as A7 and unlocks the
  privileged instructions (UM 6.1, 6.3.7).
- **T** trace: when set at the *start* of an instruction, a trace exception
  follows its completion (UM 6.3.8).

Bits 14, 12, 11, 7, 6, 5 read as zero on the 68000; `MOVE to SR` and `RTE`
write them as zero (PRM 1.3.1). Which instructions set which flags is PRM
Table 3-18; the condition tests are PRM Table 3-19, reproduced below.

Condition-code table (PRM Table 3-19; encoding is the 4-bit `cc` field in
`Bcc`, `Scc`, `DBcc`):

| cc | Mnemonic | Test | | cc | Mnemonic | Test |
| --- | --- | --- | --- | --- | --- | --- |
| 0000 | T (true) | 1 | | 1000 | VC | ¬V |
| 0001 | F (false) | 0 | | 1001 | VS | V |
| 0010 | HI | ¬C ∧ ¬Z | | 1010 | PL | ¬N |
| 0011 | LS | C ∨ Z | | 1011 | MI | N |
| 0100 | CC (HS) | ¬C | | 1100 | GE | N ≡ V |
| 0101 | CS (LO) | C | | 1101 | LT | N ⊕ V |
| 0110 | NE | ¬Z | | 1110 | GT | ¬Z ∧ (N ≡ V) |
| 0111 | EQ | Z | | 1111 | LE | Z ∨ (N ⊕ V) |

`Bcc` does not accept T or F: `0110 0000` is `BRA` and `0110 0001` is `BSR`
(PRM 4, Bcc/BRA/BSR). `Scc` and `DBcc` accept all sixteen; `DBT` is a 16-bit
NOP-with-decrement that never loops and `DBF` (`DBRA`) always counts.

## How an opcode word is decoded

`_dispatch.py` holds the map as `RULES`, one line per PRM Section 8 encoding,
and builds the 65,536-entry table from it once.

Every instruction starts with one 16-bit word, always at an even address.
Bits 15–12 select a family (PRM Table 8-2, "Operation Code Map"):

| 15–12 | Family | 15–12 | Family |
| --- | --- | --- | --- |
| 0000 | Bit manipulation, `MOVEP`, immediate-to-EA (`ORI`, `ANDI`, `SUBI`, `ADDI`, `EORI`, `CMPI`, and the `to CCR` / `to SR` forms) | 1000 | `OR`, `DIVU`, `DIVS`, `SBCD` |
| 0001 | `MOVE.B` | 1001 | `SUB`, `SUBA`, `SUBX` |
| 0010 | `MOVE.L`, `MOVEA.L` | 1010 | Line A: unimplemented, always traps (vector 10) |
| 0011 | `MOVE.W`, `MOVEA.W` | 1011 | `CMP`, `CMPA`, `CMPM`, `EOR` |
| 0100 | Miscellaneous: `NEGX`, `CLR`, `NEG`, `NOT`, `MOVE from/to SR/CCR`, `EXT`, `NBCD`, `SWAP`, `PEA`, `ILLEGAL`, `TAS`, `TST`, `MOVEM`, `TRAP`, `LINK`, `UNLK`, `MOVE USP`, `RESET`, `NOP`, `STOP`, `RTE`, `RTS`, `TRAPV`, `RTR`, `JSR`, `JMP`, `CHK`, `LEA` | 1100 | `AND`, `MULU`, `MULS`, `ABCD`, `EXG` |
| 0101 | `ADDQ`, `SUBQ`, `Scc`, `DBcc` | 1101 | `ADD`, `ADDA`, `ADDX` |
| 0110 | `Bcc`, `BRA`, `BSR` | 1110 | Shifts and rotates |
| 0111 | `MOVEQ` | 1111 | Line F: unimplemented, always traps (vector 11) |

Within a family the recurring fields are:

```text
bits:  15 14 13 12 | 11 10  9 | 8 | 7  6 | 5  4  3 | 2  1  0
       family      | register | d | size | ea mode | ea register
```

- **size** (bits 7–6) is `00` byte, `01` word, `10` long for the arithmetic
  and logic families; `11` is reused for the address-register forms (`ADDA`,
  `SUBA`, `CMPA`, `MULU/MULS`, `DIVU/DIVS`, `ANDI to SR` and so on). `MOVE`
  uses bits 13–12 instead: `01` byte, `11` word, `10` long (PRM 4, MOVE).
- **register** (bits 11–9) names the Dn or An that is not in the EA field.
- **d** (bit 8) is the direction for the two-operand families: 0 means
  `<ea> op Dn → Dn`, 1 means `Dn op <ea> → <ea>`. `EOR` only has the second
  form; `CMP` only the first (PRM 4, ADD/AND/OR/SUB/EOR/CMP).
- **ea mode, ea register** (bits 5–0) are the effective-address field
  described next. `MOVE` has two of them: the source in bits 5–0 and the
  destination in bits 11–6 *with mode and register swapped* (register in
  11–9, mode in 8–6), which is why `MOVE` disassembly tables look inverted.

The complete bit-level encoding of every instruction is PRM Section 8
("Instruction Format Summary"), about forty pages; the per-instruction pages
in PRM Section 4 (integer) and Section 6 (supervisor) repeat the encoding
with the allowed EA modes marked.

## Effective-address modes

`_ea.py`: `EA_KIND` maps the field to a kind once; `_ea_address` and
`_ea_fetch` compute and read an operand.

The 6-bit EA field is `mode (3 bits) : register (3 bits)`. Mode 7 uses the
register field to select five more forms. The 68000 has exactly these
twelve (PRM 2.2.1–2.2.7, 2.2.11–2.2.12, 2.2.16–2.2.18; the memory-indirect
and base-displacement modes of PRM 2.2.8–2.2.10 and 2.2.13–2.2.15 are 68020+
and out of scope):

| Mode | Reg | Syntax | Extension words | Address | Category |
| --- | --- | --- | --- | --- | --- |
| 000 | n | `Dn` | 0 | (register) | Data, Alterable |
| 001 | n | `An` | 0 | (register) | Alterable (word/long only) |
| 010 | n | `(An)` | 0 | An | Data, Memory, Control, Alterable |
| 011 | n | `(An)+` | 0 | An, then An += size (2 for byte on A7) | Data, Memory, Alterable |
| 100 | n | `-(An)` | 0 | An -= size (2 for byte on A7), then An | Data, Memory, Alterable |
| 101 | n | `(d16,An)` | 1: signed 16-bit displacement | An + d16 | Data, Memory, Control, Alterable |
| 110 | n | `(d8,An,Xn)` | 1: brief extension word | An + Xn + d8 | Data, Memory, Control, Alterable |
| 111 | 000 | `(xxx).W` | 1: signed 16-bit address | sign-extended word | Data, Memory, Control, Alterable |
| 111 | 001 | `(xxx).L` | 2: 32-bit address, high word first | the long | Data, Memory, Control, Alterable |
| 111 | 010 | `(d16,PC)` | 1: signed 16-bit displacement | PC + d16, PC = address of the extension word | Data, Memory, Control |
| 111 | 011 | `(d8,PC,Xn)` | 1: brief extension word | PC + Xn + d8, PC = address of the extension word | Data, Memory, Control |
| 111 | 100 | `#<data>` | 1 (byte in the low half, word) or 2 (long) | (operand is the extension) | Data |

Mode 111 with register 101, 110 or 111 is undefined on the 68000; MAME's
decode table treats those encodings as illegal instructions (vector 4), see
[undocumented-behavior](undocumented-behavior.md).

The **brief extension word** of the 68000 (PRM 2.4, Figure 2-3(a)):

```text
bit:  15   14 13 12   11    10 9 8   7 ... 0
      D/A  register   W/L   0  0 0   signed 8-bit displacement
```

`D/A` selects Dn (0) or An (1) as the index register Xn; `W/L` uses the sign-
extended low word (0) or the full long (1) of Xn. Bits 10–8 are the 68020's
scale field; PRM 2.4 says the 68000 ignores them ("the scaling factor would
be ignored"), so a core decodes only bits 15–11 and 7–0 and never traps on
the rest. The cycle tables count the brief-word modes as 10 or 14 clocks
(byte/word or long), see [timing](timing.md).

The **category** column is how the PRM says which modes an instruction
allows (PRM 2.3, Table 2-4): `Data` excludes An; `Memory` excludes Dn and
An; `Control` excludes registers, `(An)+`, `-(An)` and `#`; `Alterable`
excludes PC-relative and immediate. `JMP`, `JSR`, `LEA`, `PEA` and `MOVEM`
to memory take Control (plus `-(An)` for `MOVEM` to memory, `(An)+` for
`MOVEM` from memory); `MOVE` destination takes Data Alterable; `CLR`, `NEG`,
`NOT`, `TST`, `Scc`, `TAS` take Data Alterable; `ADDA`/`SUBA`/`CMPA`/`MOVEA`
sources take any mode.

Extension words are fetched in order after the opcode word. For `MOVE` the
source extension words precede the destination's. The order matters for
prefetch and for which address an address error reports (below).

## Operand sizes

Byte, word (16), and long (32). Memory is big-endian: a word at address A
has its high byte at A and its low byte at A+1; a long at A has its high
word at A (PRM 1.7, UM 2.4). Word and long *operand* accesses at an odd
address raise an address error (UM 6.3.10); byte accesses may be at any
address. Instruction words are always fetched at even addresses; a jump or
return to an odd address raises an address error on the fetch.

## Instruction families

The set is about 80 mnemonics (PRM Table 3-2 through 3-10 list them by
group). Each row here gives the family, its 68000 encoding sketch, and the
flag rule from PRM Table 3-18; the per-instruction pages of PRM Section 4
and 6 are the authority for every operand-mode restriction.

### Data movement (PRM Table 3-2)

| Instruction | Encoding | Flags |
| --- | --- | --- |
| `MOVE <ea>,<ea>` (.b/.w/.l) | `00 ss RRR MMM mmm rrr` (destination reg/mode swapped) | N Z from result, V C cleared, X unchanged |
| `MOVEA <ea>,An` (.w/.l) | `MOVE` with destination mode 001 | none |
| `MOVEQ #d8,Dn` | `0111 nnn 0 dddddddd`, sign-extended to long | N Z, V C cleared |
| `MOVEM list,<ea>` / `MOVEM <ea>,list` | `01001 d 001 s MMM rrr` + mask word; d=0 to memory, s=0 word; mask bit order reversed for `-(An)` | none |
| `MOVEP Dn,(d16,Ay)` / `MOVEP (d16,Ay),Dn` | `0000 nnn 1 dd 001 yyy` + d16; alternate bytes | none |
| `MOVE to CCR`, `MOVE to SR` (privileged), `MOVE from SR` (not privileged on the 68000) | `0100 0100 11 ea`, `0100 0110 11 ea`, `0100 0000 11 ea` | all (to), none (from) |
| `MOVE USP,An` / `MOVE An,USP` (privileged) | `0100 1110 0110 d nnn` | none |
| `LEA <ea>,An`, `PEA <ea>` | `0100 nnn 111 ea`, `0100 1000 01 ea` | none |
| `EXG Rx,Ry` | `1100 xxx 1 ooooo yyy` (opmode 01000 D/D, 01001 A/A, 10001 D/A) | none |
| `LINK An,#d16`, `UNLK An` | `0100 1110 0101 0 nnn` + d16, `0100 1110 0101 1 nnn` | none |
| `SWAP Dn` | `0100 1000 0100 0 nnn` | N Z of the long, V C cleared |
| `EXT.W Dn`, `EXT.L Dn` | `0100 1000 1 s 000 nnn` | N Z, V C cleared |

### Integer arithmetic (PRM Table 3-3)

| Instruction | Encoding | Flags |
| --- | --- | --- |
| `ADD`, `SUB` (`<ea>,Dn` or `Dn,<ea>`) | `1101 nnn d ss ea`, `1001 nnn d ss ea` | X N Z V C |
| `ADDA`, `SUBA` (`<ea>,An`) | same families, bits 8–6 = `011` word, `111` long | none |
| `ADDI`, `SUBI`, `CMPI` (`#,<ea>`) | `0000 0110 ss ea`, `0000 0100 ss ea`, `0000 1100 ss ea` + immediate | X N Z V C (CMPI: no X) |
| `ADDQ`, `SUBQ` (`#1–8,<ea>`) | `0101 qqq d ss ea` (qqq=000 means 8) | X N Z V C; none when the destination is An |
| `ADDX`, `SUBX` (`Dy,Dx` or `-(Ay),-(Ax)`) | `1101 xxx 1 ss 00 m yyy`, `1001 …` | X N Z(sticky) V C |
| `CMP <ea>,Dn`, `CMPA <ea>,An`, `CMPM (Ay)+,(Ax)+` | `1011 nnn 0 ss ea`, `1011 nnn s11 ea`, `1011 xxx 1 ss 001 yyy` | N Z V C |
| `NEG`, `NEGX` `<ea>` | `0100 0100 ss ea`, `0100 0000 ss ea` | X N Z V C (NEGX: Z sticky) |
| `CLR <ea>` | `0100 0010 ss ea` (reads the operand before writing on the 68000) | N=0 Z=1 V=0 C=0 |
| `MULU`, `MULS` `<ea>,Dn` (16×16→32) | `1100 nnn 011 ea`, `1100 nnn 111 ea` | N Z of the long, V C cleared |
| `DIVU`, `DIVS` `<ea>,Dn` (32÷16 → 16r:16q) | `1000 nnn 011 ea`, `1000 nnn 111 ea` | N Z of the quotient, V on overflow, C cleared; divide by zero traps (vector 5) |
| `TST <ea>` | `0100 1010 ss ea` | N Z, V C cleared |
| `TAS <ea>` | `0100 1010 11 ea`; indivisible read-modify-write bus cycle | N Z of the byte read, V C cleared, then bit 7 set |
| `CHK <ea>,Dn` | `0100 nnn 110 ea`; traps (vector 6) if Dn < 0 or Dn > operand | N per manual, others undefined |

### Logic, shifts, rotates, bits (PRM Tables 3-4, 3-5, 3-6)

| Instruction | Encoding | Flags |
| --- | --- | --- |
| `AND`, `OR` (`<ea>,Dn` / `Dn,<ea>`), `EOR Dn,<ea>` | `1100 nnn d ss ea`, `1000 nnn d ss ea`, `1011 nnn 1 ss ea` | N Z, V C cleared |
| `ANDI`, `ORI`, `EORI` `#,<ea>` | `0000 0010 ss ea`, `0000 0000 ss ea`, `0000 1010 ss ea` | N Z, V C cleared |
| `ANDI/ORI/EORI to CCR` | `0000 0x10 0011 1100` + byte | as written |
| `ANDI/ORI/EORI to SR` (privileged) | `0000 0x10 0111 1100` + word | as written |
| `NOT <ea>` | `0100 0110 ss ea` | N Z, V C cleared |
| `ASL/ASR`, `LSL/LSR`, `ROXL/ROXR`, `ROL/ROR` (register: count in `#1–8` or `Dn`, .b/.w/.l) | `1110 ccc d ss i tt rrr` (i=0 immediate count, 1 register; tt selects AS/LS/ROX/RO) | X N Z V C; ROL/ROR leave X; V only meaningful for ASL |
| Memory forms (`<ea>` word, shift by one) | `1110 0tt d 11 ea` | same |
| `BTST`, `BCHG`, `BCLR`, `BSET` (`Dn,<ea>` or `#n,<ea>`) | `0000 nnn 1 oo ea` / `0000 1000 oo ea` + bit-number word; long on Dn (bit mod 32), byte on memory (bit mod 8) | Z = tested bit inverted |

### Binary-coded decimal (PRM Table 3-8)

`ABCD Dy,Dx` / `ABCD -(Ay),-(Ax)` (`1100 xxx 10000 m yyy`), `SBCD` (`1000 …`),
`NBCD <ea>` (`0100 1000 00 ea`). Flags: X and C decimal carry/borrow, Z
sticky, **N and V undefined** on paper and deterministic on silicon, see
[undocumented-behavior](undocumented-behavior.md).

### Program control (PRM Table 3-9)

| Instruction | Encoding | Notes |
| --- | --- | --- |
| `Bcc`, `BRA`, `BSR` | `0110 cccc dddddddd`; d8 = 0 means a 16-bit displacement word follows | Displacement is from the address of the extension word (PC+2). `d8 = 0xFF` is a 68020 long form; on the 68000 it is a byte displacement of −1 |
| `DBcc Dn,<label>` | `0101 cccc 11001 nnn` + d16 | If cc false: Dn.w −= 1; if Dn.w ≠ −1 branch. Counts the low word only |
| `Scc <ea>` | `0101 cccc 11 ea` | Byte 0xFF if true else 0x00 |
| `JMP <ea>`, `JSR <ea>` | `0100 1110 11 ea`, `0100 1110 10 ea` | Control modes only |
| `RTS`, `RTR`, `RTE` (privileged) | `4E75`, `4E77`, `4E73` | `RTR` pops CCR then PC; `RTE` pops SR then PC |
| `NOP` | `4E71` | Also completes any pending prefetch |

### System control (PRM Table 3-10)

`TRAP #n` (`0100 1110 0100 nnnn`, vector 32+n), `TRAPV` (`4E76`, vector 7 if
V), `ILLEGAL` (`4AFC`, vector 4), `RESET` (`4E70`, privileged, drives the
RESET pin for 124 clocks and does not reset the CPU), `STOP #imm` (`4E72`
+ word, privileged, loads SR and halts until an interrupt above the mask or
a reset), plus the `to SR` and `MOVE USP` forms above.

## The exception model

`_core.py` (`_exception`, `_group_zero`, `_interrupt` in `cpu.py`) and
`_system.py` (the instructions that raise one).

Sources: UM 6.2 (Exception Processing), 6.3 (Processing of Specific
Exceptions), PRM Appendix B (Table B-1, vector assignments).

### Vector table (UM Table 6-2)

The table is 256 long-word entries at addresses 0–0x3FF; the 68000 has no
VBR, so it always lives at 0. The entries a 68000 core needs:

| Vector | Address | Assignment | Vector | Address | Assignment |
| --- | --- | --- | --- | --- | --- |
| 0 | 0x000 | Reset: initial SSP | 10 | 0x028 | Line 1010 emulator (A-line) |
| 1 | 0x004 | Reset: initial PC | 11 | 0x02C | Line 1111 emulator (F-line) |
| 2 | 0x008 | Bus error | 15 | 0x03C | Uninitialized interrupt vector |
| 3 | 0x00C | Address error | 24 | 0x060 | Spurious interrupt |
| 4 | 0x010 | Illegal instruction | 25–31 | 0x064–0x07C | Level 1–7 interrupt autovectors |
| 5 | 0x014 | Zero divide | 32–47 | 0x080–0x0BC | `TRAP #0`–`#15` |
| 6 | 0x018 | CHK instruction | 64–255 | 0x100–0x3FC | User interrupt vectors |
| 7 | 0x01C | TRAPV instruction | 12, 13, 16–23, 48–63 | | Reserved (14, format error, is 68010) |
| 8 | 0x020 | Privilege violation | | | |
| 9 | 0x024 | Trace | | | |

Vectors 0 and 1 are fetched from supervisor *program* space (function code
6); every other vector from supervisor data space (FC 5). Hosts that decode
function codes (few arcade boards do) see the difference.

### Groups and priority (UM 6.2.3, Table 6-3)

| Group | Exceptions | When processing begins |
| --- | --- | --- |
| 0 | Reset, address error, bus error | Within two clocks; the current instruction is aborted |
| 1 | Trace, interrupt, illegal instruction, privilege violation | Before the next instruction; the current one completes (trace, interrupt) or is never started (illegal, privilege) |
| 2 | `TRAP`, `TRAPV`, `CHK`, zero divide | As part of the instruction |

Priority within group 0 is reset, then address error, then bus error; within
group 1 trace beats interrupt, which beats illegal/privilege. When several
are pending the *lowest*-priority handler runs first: a traced `TRAP` with an
interrupt pending processes the trap, then the trace, then the interrupt, and
execution resumes in the interrupt handler (UM 6.3.8).

### The processing sequence (UM 6.2.5)

1. Copy SR internally; set S, clear T. For reset and interrupts also set the
   mask (7 for reset; the accepted level for an interrupt).
2. Determine the vector number: internally for everything except interrupts,
   which run an interrupt-acknowledge bus cycle (below).
3. Push, on the SSP, the PC (long) then the saved SR (word), so the frame
   reads SR at SSP, PC at SSP+2 (UM Figure 6-5). Reset pushes nothing.
   Address and bus errors push four more words first (below).
4. Load PC from the vector; resume execution.

The group 1/2 frame is three words: `SSP+0` SR, `SSP+2` PC high, `SSP+4` PC
low. Which PC is pushed depends on the exception:

- Interrupt, trace, `TRAP`, `TRAPV`, `CHK`, zero divide: the address of the
  next instruction (UM 6.3.2, 6.3.5, 6.3.8).
- Privilege violation: the address of the first word of the offending
  instruction (UM 6.3.7). Illegal, A-line and F-line: UM 6.3.6 says only
  "similar to that for traps"; the 68000 pushes the address of the offending
  word, see [undocumented-behavior](undocumented-behavior.md) for the
  evidence tier.
- Address and bus error: "unpredictable and may be incremented from the
  address of the instruction that caused the error" (UM 6.2.5), because the
  prefetch has already advanced. The corpora pin the exact values.

### Group 0 frame: address error and bus error (UM 6.3.9.1, 6.3.10, Figure 6-7)

Seven words are pushed (the stack pointer moves by 14):

```text
SSP+0   access information word:  bit 4 R/W (1 = read), bit 3 I/N (0 = instruction),
                                   bits 2-0 function code; bits 15-5 undefined
SSP+2   access address, high word
SSP+4   access address, low word
SSP+6   instruction register: the first word of the instruction being executed
SSP+8   status register (as copied in step 1)
SSP+10  program counter, high word
SSP+12  program counter, low word
```

An address error is "an internally generated bus error" (UM 6.3.10): a word
or long operand or instruction fetch at an odd address aborts the bus cycle
and takes vector 3 with this frame. A bus error is external (the BERR pin,
vector 2) and needs the host to assert it; most arcade hosts never do. A
group 0 exception during the processing of a group 0 exception halts the
processor until reset (double bus fault, UM 5.4.4, 6.3.9.1). The undefined
bits of the information word and the exact stacked PC are the subject of
hardware-corrected emulator work, see [undocumented-behavior](undocumented-behavior.md).

### Interrupts and the acknowledge cycle (UM 6.3.2–6.3.4)

The host encodes a request level 1–7 on IPL2–IPL0 (level 0 = none). Between
instructions the core compares the pending level with the mask: strictly
greater is accepted; level 7 is accepted on every 0-to-7 transition
regardless of the mask (edge-triggered, UM 6.3.2). Acceptance runs an
interrupt-acknowledge cycle in CPU space (FC 7) with the level on A3–A1; the
device answers with a vector number on D7–D0, or asserts VPA for an
**autovector** (vector 24 + level, the row 25–31 above), or asserts BERR for
a **spurious interrupt** (vector 24). A device with an uninitialized vector
register returns 15. Arcade boards nearly always autovector: Sega System 16
holds IRQ4 at vblank and the 68000 takes vector 28 at 0x70 (see
[timing](timing.md), MAME `irq4_line_hold`). The host sets the level with
`set_ipl()` and its `acknowledge(level)` callable answers the cycle with a
vector number, `AUTOVECTOR` or `SPURIOUS` (README, "The embedding contract"),
mirroring z80-python's IM 2 data-bus callback.

`STOP #imm` loads SR from the immediate (privileged) and halts until an
interrupt above the new mask, a level 7 edge, or reset (PRM 6, STOP). A
pending trace after `STOP` is a documented corner (PRM: "if the T bit is set,
a trace exception occurs"; the corpus `STOP.json.bin` decides the frame).

### Instruction-generated exceptions

`TRAP #n` (vector 32+n), `TRAPV` (vector 7, only if V), `CHK` (vector 6),
`DIVU`/`DIVS` by zero (vector 5): all group 2, all push the next-instruction
PC. `ILLEGAL` and every undefined first word take vector 4; words with bits
15–12 = 1010 take vector 10 and 1111 take vector 11 (UM 6.3.6). Privileged
instructions in user mode take vector 8 (UM 6.3.7). Trace takes vector 9
after any instruction that started with T set and completed; it does not
follow an instruction that trapped as illegal or privileged, nor one aborted
by a group 0 exception (UM 6.3.8).

### Reset (UM 6.3.1)

External reset (pin) sets S, clears T, sets the mask to 7, then fetches SSP
from address 0 and PC from address 4 (both from supervisor program space)
and starts executing. Nothing is pushed. `RESET` the instruction does none
of this; it pulses the RESET output for external devices (UM 6.3.1, PRM 6).

## Prefetch: what a host can observe

`_core.py`: `ir`, `irc`, `_pc`, `_prefetch`, `_extension`.

The 68000 fetches instruction words ahead of execution through a two-word
queue: when an instruction starts, its opcode word has been decoded from the
instruction register and the *next* word is already in the second stage
(the corpora call the pair `prefetch`: the executing word and the word after
it). Every instruction ends by fetching the word two ahead so the queue is
full for its successor. Three consequences matter to a host:

1. **Self-modifying code is one word late.** A store to the word immediately
   after the current instruction has no effect on that word's execution; it
   was prefetched before the store's bus cycle. The classic test is
   `MOVE.W #$4E71,(PC+2)` followed by a word that is still executed
   unmodified. A host that emulates copy protection or trace-based
   decryption sees this; a host running ordinary arcade game code does not.
2. **The fetch pattern is part of the bus trace.** In SingleStepTests both
   corpora, `NOP` is a single 4-clock read of the word at PC+4 (the sample
   records in [validation](validation.md)); a core that models "fetch
   opcode, then execute" reads the wrong address at the wrong time and fails
   the transaction comparison even when every register matches.
3. **Reads past the end of code are real.** A program ending at the top of
   ROM has its last instruction prefetch the word beyond it; if that address
   is unmapped and the host asserts BERR, the real chip takes a bus error.
   Hosts that return open-bus values must do so for prefetch too.

The 1993 UM does not describe the 68000 queue in a dedicated section (its
prefetch text at 6.3.9.2 is about the 68010's queue advancing the stacked
PC by "as many as five words"). The concrete model this core follows is the
one the MAME microcoded core implements from the die-transcribed microcode
and the two corpora record in their `prefetch` and `transactions` fields;
the core reproduces every one of the gate's 317,500 cases on them
([validation](validation.md)), so a statement here that goes beyond the UM
rests on that evidence (T3, MAME's lineage) unless a higher tier is named.
Cycle-level consequences are in [timing](timing.md).

## Suggested reading order

1. This page.
2. PRM Section 2 (addressing) and Table 3-18/3-19 (flags and conditions).
3. UM Section 6 (exceptions) end to end; it is 20 pages.
4. UM Section 8 (timing tables), restated in [timing](timing.md).
5. [undocumented-behavior](undocumented-behavior.md), then [validation](validation.md)
   and [claims](claims.md).
6. The code: `_core.py` first (the bus, the queue, exception entry), then
   `_ea.py`, then the family module a question is about; every handler's
   docstring names the manual page or corpus file its rule comes from.
