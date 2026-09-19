# Disassembly

`disassemble(read_word, address)` decodes one instruction with the core's own
opcode map (`_dispatch.NAMES`), so the disassembler and the core cannot
disagree about what a word is. The text is MAME 0.285's (`m68kdasm.cpp` at
`mame0285`): lowercase mnemonics with a size suffix, `$` hex, `D0`/`A0`,
`(d16,An)` as `($10,A0)`, PC-relative operands as their target, `dbra` for
DBF, register lists as `D0-D7/A0-A6`. Undefined words print as `dc.w`.

`validation/disasm_vs_mame.py` compares it with MAME's own disassembly of
every distinct instruction a lockstep trace ran (the debugger's trace file
beside `error.log`); the counts are in docs/validation.md.
