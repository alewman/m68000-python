# CPU state: capture and restore

`M68000CPU.capture_state()` returns a frozen `CPUState`; `restore_state(state)`
puts it back. Both touch only what the processor owns: no host read, no
device, no memory. Restoring a state restores the processor, not a machine.

| Field | Meaning |
| --- | --- |
| `d` | D0-D7, eight 32-bit values |
| `a` | A0-A6, seven 32-bit values (A7 is `usp` or `ssp`, whichever S selects; `a7` is a property) |
| `usp`, `ssp` | the two stack pointers |
| `sr` | the status register; bits 14, 12, 11 and 7-5 must be zero |
| `pc` | the address of the instruction in `ir` |
| `ir`, `irc` | the prefetch queue: that instruction's first word and the word after it |
| `ipl` | the interrupt level the host last set (0-7) |
| `nmi_edge` | a level 7 edge seen and not yet taken |
| `trace_pending` | the last instruction ran with T set; the next step takes the trace exception |
| `stopped` | inside STOP (`pc` is the STOP's own address; execution resumes at `pc + 4`) |
| `halted` | double bus fault: only `reset()` leaves it |
| `clock` | clocks run so far; the E-clock phase of an autovectored acknowledge comes from it |

The queue is part of the state because the chip's is: a program that
modifies the word after the current instruction sees the old word run
([start-here](start-here.md), "Prefetch"). A state captured between
instructions restores exactly; one captured by a host inside a bus callback
is not a boundary and is not supported.

Construction validates every field's type and range; the value is
comparable, hashable and `dataclasses.asdict()`-friendly. This release does
not promise that the dictionary is a permanent cross-version save format;
the versioned form is the state object of [the trace schema](trace-schema.md).

## Machine boundary

`CPUState` excludes everything the host owns: memory, mappers and devices;
video, audio and input; frame and interrupt scheduling and the host's own
clocks; queued device events. Restoring only `CPUState` is correct when the
host's state has not changed, or when the host restores its own matching
state beside it. It is not whole-machine rewind.

## Example

```python
before = cpu.capture_state()
memory_before = bytes(memory)  # the host's, not the CPU's

cpu.step()

memory[:] = memory_before
cpu.restore_state(before)
assert cpu.capture_state() == before
```
