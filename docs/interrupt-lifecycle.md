# Interrupt lifecycle: the host protocol

`m68000-python` models interrupts, traps and the other external inputs as
deterministic transitions at instruction boundaries. This page is the whole
protocol between a host and the core, in one place; the manual sections are
UM 6.2 and 6.3, and the evidence for each rule is in
[claims](claims.md) ("Interrupts and STOP" is *provisional*: the manual,
the MAME lockstep's 5,579 interrupts, and scenario tests).

## Reset

`cpu.reset()` is the reset exception (UM 6.3.1): S set, T cleared, the mask
raised to 7, SSP fetched from address 0 and PC from address 4, both in
supervisor program space, the queue refilled, nothing pushed. It returns 40
clocks, as UM Table 8-14 prints: the SSP vector is read 14 clocks in, where
a gate-level model of the chip reads it (see [claims](claims.md)). A fault while it fetches the vectors or the first
instruction (an odd initial PC, BERR on a vector) halts the processor: the
double bus fault of UM 5.4.4. The host calls `reset()` when its RESET pin
would be released; it may call `set_pc(address)` instead to start a program
it loaded itself, which refills the queue without a reset and counts no
clocks, and refuses an odd address (an instruction never lives at one).

The **RESET instruction** does not reset the processor. It pulses the RESET
line for 124 clocks (132 for the instruction); a host that wants to reset
its devices passes `reset_devices=` to the constructor and is called with
no arguments.

## Interrupts

1. The host encodes the request level, 0 (none) to 7, on the IPL inputs with
   `cpu.set_ipl(level)`, between calls to `step()`. The level stays as set
   until the host changes it: a device that keeps requesting is a level held
   high.
2. At the next boundary the core compares the level with the mask in SR. A
   level **greater than** the mask is accepted; level 7 is accepted once
   per 0-to-7 transition whatever the mask (edge-triggered, UM 6.3.2), and
   not again while it is held.
3. Acceptance is its own `step()`: it returns the entry's clock total, not
   an instruction's, and a `DebugSession` records it as an `interrupt`
   boundary. The core copies SR, sets S, clears T, raises the mask to the
   accepted level, runs the acknowledge cycle, pushes the frame and enters
   the handler (UM 6.3.2-6.3.4).
4. The **acknowledge cycle** asks the host's `acknowledge(level)` callable,
   given to the constructor, what the device answered:
   - a vector number 0-255: the device put it on the data bus;
   - `AUTOVECTOR`: the device asserted VPA, and the vector is 24 + level
     (25-31), what nearly every arcade board and the Mega Drive answer;
   - `SPURIOUS`: the device asserted BERR, and the vector is 24;
   - any other number: an uninitialised device, vector 15.

   Without an `acknowledge` callable every interrupt is autovectored.
5. The **frame** is three words on the supervisor stack: SR at SSP, PC at
   SSP+2, the PC being the address of the instruction the interrupt came
   before (written PC low, SR, PC high, the microcode's order, which a bus
   watcher sees).
6. The **clocks**: 44 for a vectored or spurious acknowledge (UM Table
   8-14). An autovectored acknowledge waits for the E clock (CLK/10):
   5 to 14 clocks more by the phase of `cpu.clock` when the cycle starts,
   MAME 0.285's rule, matched by the System 16B lockstep at all ten phases
   (T3; `cpu.last_acknowledge_phase` says which phase it was). A host that
   never sets `cpu.clock` gets the phase the core's own count gives.

The host lowers the level (`set_ipl(0)`, or the level of the next device
still requesting) when its device is satisfied, usually inside the write
that acknowledges the device. Hosts must not alter PC, SR or the stack
pointers to synthesise an entry: the core's entry is the only one that
takes the frame, the mask and the clocks together.

## Traps and other exceptions

Group 2 exceptions (`TRAP`, `TRAPV`, `CHK`, divide by zero) and group 1's
illegal instruction, line A/F and privilege violation are part of the
instruction's own `step()`; the host sees only the clock total and the new
PC. A **trace** exception (T set at the start of an instruction that
completed) is its own boundary: the next `step()` takes it, before any
pending interrupt (UM 6.3.8). An instruction that was never executed
(illegal, privileged in user mode) is not traced.

## Address and bus errors

A word or long access at an odd address is an **address error** the core
raises itself: the access never reaches the host, the instruction is
aborted inside the same `step()`, and the seven-word group 0 frame is
pushed (UM 6.3.10). A host that wants to know about the aborted access
passes `address_error(address, write, fc)` to the constructor.

A **bus error** is the host's: raise `BusError` from any bus callable to
assert BERR on that access. The core takes vector 2 with the group 0 frame;
what that frame contains is outside the contract ([claims](claims.md),
"Outside the contract").

A group 0 fault while the group 0 frame is being pushed **halts** the
processor (the double bus fault, UM 5.4.4): `cpu.halted` is set, every
`step()` returns 4 idle clocks, and only `reset()` leaves the state.

## STOP

`STOP #data` loads SR and stops the processor: `cpu.stopped` is set and
every `step()` returns 4 idle clocks until a level above the new mask, a
level-7 edge, or a pending trace ends it. The interrupt's frame stacks the
address after the STOP, where execution resumes on RTE.

## TAS and a bus that drops the write

`TAS` is the one indivisible read-modify-write cycle. A bus that does not
complete its write half (the Sega Genesis) is a host matter: pass
`tas_write(address, value)` to the constructor and drop it there. Without
it the write goes to `write_byte`.

## Function codes

A host that decodes function codes (few boards do) passes
`function_codes=True`; every bus callable then receives `fc=` (UM Table
3-2: 1 and 2 user data and program, 5 and 6 supervisor data and program).
The acknowledge cycle is in CPU space (7) but is a call to `acknowledge`,
not a bus access.

## Between steps

Everything above happens inside `step()`. Between steps the host may read
and write `R`, `SR` (or `set_sr()`, which also swaps A7 with the other
stack pointer when S changes), `ipl` through `set_ipl()`, `clock`, and the
queue (`ir`, `irc`) through `set_pc()`; may capture and restore the whole
processor with `capture_state()`/`restore_state()`; and may replace the bus
callables with `attach_bus()`. Calling `step()` from inside a bus callable
is not supported.

## Scope

This covers the lifecycle a single-CPU host, an arcade board, or the Mega
Drive's 68000 side needs. It does not model bus arbitration (BR/BG/BGACK),
the HALT pin, wait states, or the timing of the acknowledge cycle beyond
its clock total; a second processor's share of the bus is the host's,
through the clocks `step()` returns and `step_clocks` inside a callable.
