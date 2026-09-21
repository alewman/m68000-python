# Documents

Read in this order if you are new to the project; each page names its
sources and the tier of every oracle it leans on.

| Page | What it is |
| --- | --- |
| [start-here.md](start-here.md) | The 68000 primer: registers, SR, opcode fields, the twelve EA modes and extension words, instruction families with encodings and flag effects, the exception model (vectors, groups, frames, interrupts, traps, reset), prefetch |
| [timing.md](timing.md) | The User's Manual cycle tables restated (Tables 8-1 to 8-14), what prefetch does to them, and the System 16 clocks and interrupt from MAME's driver |
| [undocumented-behavior.md](undocumented-behavior.md) | DIV/CHK/BCD undefined flags, MOVEM corner cases, odd-address faults, illegal-instruction families, TAS, trace: each with source and tier, `[unverified]` where inferred |
| [validation.md](validation.md) | Every oracle found, its tier, license, pin, size, coverage, limits and record shape; what was fetched and counted |
| [coverage.md](coverage.md) | What the evidence reaches: the encodings, behavioural paths and source lines each corpus and the whole suite run; how the 7,796 words the gate never runs are now covered; the gaps that need an oracle this repository does not have |
| [mutation.md](mutation.md) | Mutation testing of the suite: 176 seeded mutants, the score per area at three points, every survivor and what would settle it |
| [mame-oracle.md](mame-oracle.md) | Producing 68000 instruction traces from MAME 0.285 headlessly: command line, Lua script, register names, verified output |
| [handoff-brief.md](handoff-brief.md) | Context, task, milestones with acceptance tests in oracle-tier order, constraints, size estimate, what done looks like |

Sources used throughout: the Motorola *M68000 Family Programmer's Reference
Manual* (PRM) and *M68000 8-/16-/32-Bit Microprocessors User's Manual* (UM),
both from nxp.com; MAME 0.285 sources at tag `mame0285`; the repositories
pinned in [validation.md](validation.md).
