# AI-assisted development and validation

This core was written with extensive AI assistance, "vibe coded" in the
colloquial sense, and that is not the basis for its correctness claim.

One agent wrote the core overnight (2026-09-18/19) from a brief that ordered
the work by oracle tier: the corpus runner and the first files, the
hardware-captured BCD tables, the whole corpus, the MAME lockstep, the second
corpus as a detector, the interrupt scenarios. Three verification rounds
followed, each with a human deciding what the evidence meant: a coverage map
and mutation testing of the suite (2026-09-21), two referees built from
pinned sources and run one instruction at a time (2026-09-21), and the claim
boundary that labels every behaviour by the independent lineages that
support it ([claims](claims.md)). A polish round (2026-09-25) brought the
documents, the tests and the citations to the family's bar.

Generated emulator code can be plausible and wrong. On a 68000 the traps
are the prefetch queue, the PC an address error stacks, the halfway flags
of a faulting long, the undefined flags of DIV and CHK, and the I/N bit.
The engineering decision was therefore to make the feedback loop stronger
than the model's confidence:

- **the gate first**: 317,500 single-step cases compared on every bus
  access, no case excluded, run in CI on every push;
- **independent lineages**: WinUAE's hardware-corrected tester core and
  Musashi built and run, and the gate's MAME lineage counted once, not
  twice, when they agree;
- **the suite measured**: coverage of every defined first word and every
  declared behavioural path, and 176 seeded mutants of which the suite
  kills every non-equivalent one;
- **bugs as failing tests first**: the four core bugs the gate could not
  see (trace after an unexecuted instruction, TRAPV's IR under an odd
  vector, a bus error escaping from TAS, I/N during group 2 processing)
  each landed as a failing test in one commit and a fix in the next; and
- **a claim boundary**: where the evidence runs out the pages say so and
  name what would settle it, rather than choosing a winner.

Future contributions should preserve that discipline: a semantic change
needs a focused test and the full gate; a change to a contested rule needs
evidence closer to silicon than the gate's; the numbers in the documents
are regenerated, not remembered ([CONTRIBUTING](../CONTRIBUTING.md)).
