# Documents

Read in this order if you are new to the project; each page names its
sources and the tier of every oracle it leans on.

| Page | What it is |
| --- | --- |
| [claims.md](claims.md) | **The contract**: every behaviour with its status (verified, strong, provisional, contested, undecidable here, outside the contract), the lineages of evidence behind it, and what would settle what is open |
| [start-here.md](start-here.md) | The 68000 primer: registers, SR, opcode fields, the twelve EA modes and extension words, instruction families with encodings and flag effects, the exception model (vectors, groups, frames, interrupts, traps, reset), prefetch; each section names the module that implements it |
| [interrupt-lifecycle.md](interrupt-lifecycle.md) | The host protocol in one place: reset, `set_ipl`, the acknowledge answers and the E-clock wait, traps, address and bus errors, the double fault, STOP, TAS, function codes, what the host may touch between steps |
| [timing.md](timing.md) | The User's Manual cycle tables restated (Tables 8-1 to 8-14), what prefetch does to them, where the corpus decided against a misprint, and the System 16 clocks and interrupt from MAME's driver |
| [undocumented-behavior.md](undocumented-behavior.md) | DIV/CHK/BCD undefined flags, MOVEM corner cases, odd-address faults, illegal-instruction families, TAS, trace: each with source, tier and the code that encodes it |
| [validation.md](validation.md) | The certification record; every oracle found, its tier, license, pin, size, coverage, limits and record shape; the speed ladder |
| [referees.md](referees.md) | WinUAE's CPU-tester core (T2 in its checked scope) and Musashi (T3), built from pinned sources and run one instruction at a time: lineages, calibration against the gate, what each can judge, the open questions put to them, the 680x0 table re-derived, a bus-error sweep |
| [coverage.md](coverage.md) | What the evidence reaches: the encodings, behavioural paths and source lines each corpus and the whole suite run; how the 7,796 words the gate never runs are covered; the gaps that need an oracle this repository does not have |
| [mutation.md](mutation.md) | Mutation testing of the suite: 176 seeded mutants, the score per area at three points, every survivor and what would settle it |
| [mame-oracle.md](mame-oracle.md) | Producing 68000 instruction traces from MAME 0.285 headlessly: command line, Lua script, register names, verified output |
| [api-stability.md](api-stability.md) | What is public, the three spellings of the program counter, the writable attributes, and the compatibility policy |
| [cpu-state.md](cpu-state.md) | `CPUState`: capture and restore of everything the processor owns, and the machine boundary |
| [disassembly.md](disassembly.md) | The disassembler: MAME's spelling, the `Instruction` value, ranges, the side-effect-free reader |
| [debug-session.md](debug-session.md) | `DebugSession`, `CommandDebugger` and `python -m m68000_python`: stop reasons, records, watchpoints, targets, every command |
| [trace-comparison.md](trace-comparison.md) | First-divergence comparison of two traces or two live sessions |
| [trace-schema.md](trace-schema.md) | The JSON Lines trace format, version 1: every key, the state object, an example record, the comparison and versioning rules |
| [ai-assisted-development.md](ai-assisted-development.md) | How the core was built and why that is not the basis of its claim |
| [releases/](releases/) | Release notes |

Records, not contracts, kept under `history/` for provenance: the
[handoff brief](history/handoff-brief.md) the core was built from (its
size estimate and milestones are what was planned, not what is), and the
[worklog](history/worklog.md) of what was run, when, with what result, and
what was decided. The current state of every question they raise is in
[claims.md](claims.md).

Sources used throughout: the Motorola *M68000 Family Programmer's Reference
Manual* (PRM) and *M68000 8-/16-/32-Bit Microprocessors User's Manual* (UM),
both from nxp.com; MAME 0.285 sources at tag `mame0285`; the repositories
pinned in [validation.md](validation.md).
