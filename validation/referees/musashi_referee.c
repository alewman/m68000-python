/* A one-instruction driver around Musashi (Karl Stenerud, MIT).
 *
 * Musashi is a hand-written 680x0 interpreter with its own lineage: it does
 * not model the prefetch queue, the order of bus transactions, or the
 * microcode's address-error frames the way MAME's microcoded core and
 * WinUAE do.  It is used here only for what it does model: the
 * architectural result of an instruction (registers, SR, PC, memory), and
 * the entry into simple group 1/2 exceptions.  See docs/referees.md.
 *
 * Built against Musashi's own m68kcpu.c and generated m68kops.c, with its
 * m68kconf.h adjusted at build time (68000 only, address errors on); no
 * Musashi source is copied into this repository.
 *
 * Protocol: the same as winuae_referee.cpp's case lines (C ..., F, Q).  One
 * line per case on stdout:
 *   R <id> pc=<next pc> sr= r=<d0..a7> usp= ssp= cyc=<clocks> stopped=<n> w=<addr>:<byte>,...
 * (stopped: 1 after STOP, 2 halted by a double fault).
 * Musashi executes an exception's entry inside the same step, so the state
 * printed is the state after it (PC at the handler, frame on the stack).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "m68k.h"
#include "m68kcpu.h" /* m68ki_cpu: the stopped and run-mode state */

static unsigned char memory[0x1000000];
static unsigned int touched[1 << 16];
static int touched_count;
static unsigned int written[1 << 12];
static int written_count;

static void touch(unsigned int address)
{
	if (touched_count < (int)(sizeof touched / sizeof touched[0]))
		touched[touched_count++] = address;
}

static void note_write(unsigned int address)
{
	address &= 0xffffff;
	touch(address);
	if (written_count < (int)(sizeof written / sizeof written[0]))
		written[written_count++] = address;
}

unsigned int m68k_read_memory_8(unsigned int address) { return memory[address & 0xffffff]; }
unsigned int m68k_read_memory_16(unsigned int address)
{
	return (m68k_read_memory_8(address) << 8) | m68k_read_memory_8(address + 1);
}
unsigned int m68k_read_memory_32(unsigned int address)
{
	return (m68k_read_memory_16(address) << 16) | m68k_read_memory_16(address + 2);
}
unsigned int m68k_read_disassembler_8(unsigned int address) { return m68k_read_memory_8(address); }
unsigned int m68k_read_disassembler_16(unsigned int address) { return m68k_read_memory_16(address); }
unsigned int m68k_read_disassembler_32(unsigned int address) { return m68k_read_memory_32(address); }

void m68k_write_memory_8(unsigned int address, unsigned int value)
{
	memory[address & 0xffffff] = (unsigned char)value;
	note_write(address);
}
void m68k_write_memory_16(unsigned int address, unsigned int value)
{
	m68k_write_memory_8(address, value >> 8);
	m68k_write_memory_8(address + 1, value);
}
void m68k_write_memory_32(unsigned int address, unsigned int value)
{
	m68k_write_memory_16(address, value >> 16);
	m68k_write_memory_16(address + 2, value);
}

static int compare_address(const void *a, const void *b)
{
	unsigned int x = *(const unsigned int *)a, y = *(const unsigned int *)b;
	return x < y ? -1 : x > y;
}

static void run_case(char *line)
{
	char id[256];
	unsigned int v[20];
	int n, consumed;
	if (sscanf(line, "C %255s %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x%n",
		id, &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7], &v[8], &v[9], &v[10], &v[11],
		&v[12], &v[13], &v[14], &v[15], &v[16], &v[17], &v[18], &n, &consumed) != 21) {
		fprintf(stderr, "bad case line: %s\n", line);
		exit(2);
	}
	for (int i = 0; i < touched_count; i++)
		memory[touched[i]] = 0;
	touched_count = 0;
	written_count = 0;
	char *p = line + consumed;
	for (int i = 0; i < n; i++) {
		unsigned int a, b;
		int used;
		if (sscanf(p, " %x:%x%n", &a, &b, &used) != 2) {
			fprintf(stderr, "bad ram pair in %s\n", id);
			exit(2);
		}
		p += used;
		a &= 0xffffff;
		memory[a] = (unsigned char)b;
		touch(a);
	}

	static const m68k_register_t order[15] = {
		M68K_REG_D0, M68K_REG_D1, M68K_REG_D2, M68K_REG_D3, M68K_REG_D4, M68K_REG_D5,
		M68K_REG_D6, M68K_REG_D7, M68K_REG_A0, M68K_REG_A1, M68K_REG_A2, M68K_REG_A3,
		M68K_REG_A4, M68K_REG_A5, M68K_REG_A6,
	};
	for (int i = 0; i < 15; i++)
		m68k_set_reg(order[i], v[i]);
	/* SR first (it does not swap stacks), then each stack pointer by name. */
	m68k_set_reg(M68K_REG_SR, v[17]);
	m68k_set_reg(M68K_REG_USP, v[15]);
	m68k_set_reg(M68K_REG_ISP, v[16]);
	m68k_set_reg(M68K_REG_PC, v[18]);
	/* A STOP or a halt in the previous case must not carry over. */
	CPU_STOPPED = 0;
	CPU_RUN_MODE = RUN_MODE_NORMAL;
	written_count = 0;

	int cycles = m68k_execute(1);

	printf("R %s pc=%x sr=%x r=", id, m68k_get_reg(NULL, M68K_REG_PC), m68k_get_reg(NULL, M68K_REG_SR));
	static const m68k_register_t all[16] = {
		M68K_REG_D0, M68K_REG_D1, M68K_REG_D2, M68K_REG_D3, M68K_REG_D4, M68K_REG_D5,
		M68K_REG_D6, M68K_REG_D7, M68K_REG_A0, M68K_REG_A1, M68K_REG_A2, M68K_REG_A3,
		M68K_REG_A4, M68K_REG_A5, M68K_REG_A6, M68K_REG_A7,
	};
	for (int i = 0; i < 16; i++)
		printf(i ? ",%x" : "%x", m68k_get_reg(NULL, all[i]));
	printf(" usp=%x ssp=%x cyc=%d stopped=%d w=", m68k_get_reg(NULL, M68K_REG_USP),
		m68k_get_reg(NULL, M68K_REG_ISP), cycles, CPU_STOPPED);
	qsort(written, written_count, sizeof written[0], compare_address);
	unsigned int last = 0xffffffff;
	int first = 1;
	for (int i = 0; i < written_count; i++) {
		if (written[i] == last)
			continue;
		last = written[i];
		printf(first ? "%x:%x" : ",%x:%x", last, memory[last]);
		first = 0;
	}
	printf("\n");
}

int main(void)
{
	m68k_init();
	m68k_set_cpu_type(M68K_CPU_TYPE_68000);
	m68k_pulse_reset();
	m68k_execute(1); /* the first call only spends the reset's clocks */
	static char line[1 << 20];
	while (fgets(line, sizeof line, stdin)) {
		if (line[0] == 'Q')
			break;
		if (line[0] == 'C')
			run_case(line);
		else if (line[0] == 'F')
			fflush(stdout);
	}
	fflush(stdout);
	return 0;
}
