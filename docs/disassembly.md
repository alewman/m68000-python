# Disassembly

`disassemble(read_word, address)` decodes one instruction without creating
or touching an `M68000CPU`. The reader is called with 24-bit even addresses
and returns 16-bit words. `disassemble_bytes(data, address)` decodes from a
copied byte sequence placed at `address` and refuses anything that is not
exactly one instruction; `disassemble_range(read_word, start, end)` walks
instruction lengths from `start` up to `end`.

All three return an immutable `Instruction` with:

- `address`, and `words`: the opcode word and its extension words;
- `data`, the same as big-endian bytes, and `length` in bytes;
- `mnemonic` and structured `operands`; and
- `text`, the canonical line, also `str(instruction)`.

Which instruction a first word is comes from `_dispatch.NAMES`, the table
the core itself dispatches on, so the disassembler and the core cannot
disagree about what a word means; every one of the 65,536 first words
decodes and round-trips through its bytes (`tests/test_disasm.py`).

## MAME's spelling

The text follows MAME 0.285's 68000 disassembler (`m68kdasm.cpp` at
`mame0285`): lowercase mnemonics with a size suffix, `$` hexadecimal,
`D0`/`A0`, `($10,A0)` and `($4,A0,D1.l)`, PC-relative operands shown as
their target, `dbra` for DBF, `illegal` for `$4AFC`, `dc.w $xxxx; ILLEGAL`
for every other undefined word and `dc.w $xxxx; opcode 1010`/`1111` for
the line A and F words, register lists as `D0-D7/A0-A6`, arithmetic
immediates signed and logical ones unsigned. A disassembly can therefore
be diffed against a MAME trace line by line, which is how the lockstep's
debugger traces are read.

That spelling is checked two ways: `validation/disasm_vs_mame.py` compares
every distinct instruction a lockstep trace ran with MAME's own line (880 of
880 on System 16B Altered Beast, 3,771 of 3,771 on the Genesis), and
`tests/disasm_mame.txt`, 1,300 of those instructions written out by the
same script, is checked in CI without MAME or the ROMs.

## Side-effect-free reads

Disassembly is observation, so it must not alter the machine observed. A
normal emulator read may acknowledge an interrupt, advance a FIFO or clear
a status bit. For that reason there is no `cpu.disassemble()` and nothing
here calls the CPU's bus: the host passes an explicit side-effect-free
word reader, the same `peek_word` a `DebugSession` takes.

```python
instruction = disassemble(machine.peek_word, cpu.PC)
print(f"{instruction.address:06X}: {instruction.text}")
```

A host that cannot safely peek a region should say so rather than route
debugging reads through device access methods.

## Formatting is presentation

Debugger and agent integrations should consume `mnemonic`, `operands`,
`words` and `data` rather than parse `text`. A trace record written by a
port in another language carries only the address and the bytes; this
package's disassembler supplies the text ([trace schema](trace-schema.md)).
