// A one-instruction driver around WinUAE's 68000 CPU-tester core.
//
// WinUAE's CPU tester ("cputest", Toni Wilen) is the program whose output is
// run on real Amigas and corrected until the hardware agrees.  Its generator
// executes each test instruction on a special gencpu-generated core
// (cpuemu_90_test.cpp: the 68000, cycle-exact, prefetch, address and bus
// errors) and records the registers, SR, PC, memory writes, the exception
// number and stack frame, and the clock count.  This driver runs that same
// core, one instruction per case, on states read from stdin, and prints what
// the generator would have recorded.  See docs/referees.md.
//
// cputest.cpp (GPL-2.0+) is not copied: it is #included from the pinned,
// fetched WinUAE tree at build time, so this file can reach its static state.
// Its main() and one clashing helper are renamed on the way in.
//
// Protocol, one case per line on stdin (all numbers hexadecimal):
//   C <id> d0..d7 a0..a6 usp ssp sr pc <n> <addr>:<byte> ... (n pairs)
//   B <start> <size> <mode>   bus-error region for the cases that follow
//                             (mode: bit 0 data read, bit 1 write, bit 2
//                             program read), size 0 turns it off
//   F                         flush stdout (end of a batch)
//   Q                         quit
// pc is the instruction's own address.  One line per case on stdout:
//   R <id> exc=<n> pc= sr= r=<d0..a7> usp= ssp= cyc= excyc= trace= frame=
//   frame1= w=<addr>:<byte>,... flags=
// exc is the exception the instruction raised (0: none); the registers are
// those at the moment of the exception (WinUAE's tester never executes the
// exception itself; it builds the frame separately), frame is the stack
// frame it builds, frame1 the partial group 1/2 frame when an odd vector
// turns the exception into an address error.  cyc is the clock count up to
// the exception, excyc the exception's own cost from the tester's hardware
// side (cputest/main.c getexceptioncycles and check_cycles), which the
// Amiga run adds before comparing with the measured count.

#define main winuae_cputest_generator_main
#define my_trim winuae_cputest_my_trim
#include "cputest.cpp"
#undef my_trim
#undef main

#include <string>
#include <vector>

#define REFEREE_TOP 0xfff000

static uae_u8 referee_opcode[OPCODE_AREA + 8];
static std::vector<uae_u32> referee_touched;

static uae_u8 mem_byte(uae_u32 a) { return test_memory[a & 0xffffff]; }
static uae_u32 mem_long(uae_u32 a)
{
	return (mem_byte(a) << 24) | (mem_byte(a + 1) << 16) | (mem_byte(a + 2) << 8) | mem_byte(a + 3);
}

static void referee_init(void)
{
	currprefs.cpu_model = 68000;
	currprefs.address_space_24 = 1;
	currprefs.int_no_unimplemented = true;
	currprefs.fpu_model = 0;
	currprefs.fpu_mode = 1;
	addressing_mask = 0x00ffffff;
	cpu_lvl = 0;
	maincpu[0] = 1;

	// One test region covers the 24-bit space up to TOP; no low, high or
	// super-stack regions, and no protected opcode area.  The tester builds
	// exception frames in EXTRA_RESERVED_SPACE bytes just past the region,
	// addressed through the 24-bit mask, so the region must end below 16 MB:
	// an access in the top 4 KB is out of the tester's space and is flagged
	// (flags=oob) instead of judged.
	test_memory_start = 0;
	test_memory_size = REFEREE_TOP;
	test_memory_end = test_memory_start + test_memory_size;
	test_memory = (uae_u8 *)calloc(1, 0x1000000);
	test_memory_temp = NULL;
	low_memory_size = 0xffffffff;
	high_memory_size = 0xffffffff;
	test_low_memory_start = test_low_memory_end = 0xffffffff;
	test_high_memory_start = test_high_memory_end = 0xffffffff;
	safe_memory_start = safe_memory_end = 0xffffffff;
	safe_memory_mode = 0;
	super_stack_memory = 0;
	opcode_memory_start = 0xf0000000;
	opcode_memory = referee_opcode;

	for (int i = 0; i < 256; i++) {
		int j;
		for (j = 0; j < 8; j++) {
			if (i & (1 << j))
				break;
		}
		movem_index1[i] = j;
		movem_index2[i] = 7 - j;
		movem_next[i] = i & (~(1 << j));
	}

	init_table68k();
	const struct cputbl *tbl = op_smalltbl_90_test_ff;
	for (int opcode = 0; opcode < 65536; opcode++) {
		cpufunctbl[opcode] = op_illg_1;
		cpufunctbl_noret[opcode] = op_illg_1_noret;
	}
	for (int i = 0; tbl[i].handler_ff != NULL || tbl[i].handler_ff_noret != NULL; i++) {
		int opcode = tbl[i].opcode;
		cpufunctbl[opcode] = tbl[i].handler_ff;
		cpufunctbl_noret[opcode] = tbl[i].handler_ff_noret;
	}
	// The same filling of the table as cputest.cpp's test() for a 68000.
	for (int opcode = 0; opcode < 65536; opcode++) {
		instr *table = &table68k[opcode];
		if (table->mnemo == i_ILLG)
			continue;
		if (table->unimpclev > 0 && cpu_lvl >= table->unimpclev) {
			cpufunctbl_noret[opcode] = op_illg_1_noret;
			continue;
		}
		if (table->clev > cpu_lvl)
			continue;
		if (isfpp(table->mnemo))
			continue;
		if (table->handler != -1) {
			int idx = table->handler;
			cpufunctbl[opcode] = cpufunctbl[idx];
			cpufunctbl_noret[opcode] = cpufunctbl_noret[idx];
		}
	}

	x_get_long = get_long_test;
	x_get_word = get_word_test;
	x_get_byte = get_byte_test;
	x_put_long = put_long_test;
	x_put_word = put_word_test;
	x_put_byte = put_byte_test;
	x_next_iword = next_iword_test;
	x_cp_next_iword = next_iword_test;
	x_next_ilong = next_ilong_test;
	x_cp_next_ilong = next_ilong_test;
	x_cp_get_long = get_long_test;
	x_cp_get_word = get_word_test;
	x_cp_get_byte = get_byte_test;
	x_cp_put_long = put_long_test;
	x_cp_put_word = put_word_test;
	x_cp_put_byte = put_byte_test;
}

// cputest/main.c getexceptioncycles(), 68000 branch: the clocks the hardware
// side adds for exception processing before comparing with the measurement.
static int exception_cycles(int exc)
{
	switch (exc) {
	case 2: return 58;
	case 3: return 54;
	case 7: return 30;
	default:
		if (exc >= 24 && exc <= 31)
			return 44;
		return 34;
	}
}

static void hex_bytes(std::string &out, const uae_u8 *p, int n)
{
	char b[4];
	for (int i = 0; i < n; i++) {
		snprintf(b, sizeof b, "%02x", p[i]);
		out += b;
	}
}

struct referee_input {
	uae_u32 d[15];
	uae_u32 usp, ssp, pc;
	uae_u16 sr;
};

// Load the registers and run the instruction once, as execute_ins() does for
// the first instruction of a test.
static void execute_once(const struct referee_input *in)
{
	for (int i = 0; i < 15; i++)
		regs.regs[i] = in->d[i];
	// Enter user mode first so that MakeFromSR() switches stacks the way the
	// S bit says and sets up trace from T.
	regs.s = 0;
	regs.t1 = regs.t0 = regs.m = 0;
	regs.intmask = 0;
	regs.regs[15] = in->usp;
	regs.usp = in->usp;
	regs.isp = in->ssp;
	regs.msp = in->ssp;
	regs.sr = in->sr;
	regs.pc = in->pc;
	regs.instruction_pc = in->pc;
	regs.ir = (mem_byte(in->pc) << 8) | mem_byte(in->pc + 1);
	regs.irc = (mem_byte(in->pc + 2) << 8) | mem_byte(in->pc + 3);
	regs.ird = regs.ir;
	regs.opcode = regs.ir;
	referee_opcode[0] = regs.ir >> 8;
	referee_opcode[1] = (uae_u8)regs.ir;
	uae_u16 opc = regs.ir;

	flag_SPCFLAG_TRACE = 0;
	flag_SPCFLAG_DOTRACE = 0;
	trace_store_pc = 0xffffffff;
	mmufixup[0].reg = -1;
	mmufixup[1].reg = -1;
	cpu_stopped = 0;
	cpu_halted = 0;
	out_of_test_space = false;
	test_exception = 0;
	test_exception_extra = 0;
	test_exception_opcode = -1;
	exception_stack_frame_size = 0;
	ahcnt_current = ahcnt_written = 0;
	MakeFromSR();
	low_memory_accessed = high_memory_accessed = test_memory_accessed = 0;
	test_memory_access_mask = 0;
	testing_active = 1;
	testing_active_opcode = opc;
	hardware_bus_error = 0;
	hardware_bus_error_fake = 0;
	read_buffer_prev = regs.irc;
	regs.read_buffer = regs.irc;
	regs.write_buffer = 0xf00d;
	exception_extra_frame_size = 0;
	exception_extra_frame_type = 0;
	cpu_cycles = 0;
	regs.loop_mode = 0;
	regs.ipl_pin = 0;
	interrupt_level = 0;
	regs.ipl[0] = regs.ipl[1] = 0;
	regs.ipl_evt_pre = 0;
	regs.ipl_evt = 0;
	interrupt_cycle_cnt = 0;
	test_exception_orig = 0;
	waitstate_cycle_cnt = 0;
	cpuipldelay2 = 2;
	cpuipldelay4 = 4;
	if (flag_SPCFLAG_TRACE)
		do_trace();
	test_opcode = opc;
	(*cpufunctbl_noret[opc])(opc);
	testing_active = 0;
}

static void run_case(char *line)
{
	char id[256];
	uae_u32 v[20];
	int n, consumed;
	if (sscanf(line, "C %255s %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x %x%n",
		id, &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7], &v[8], &v[9], &v[10], &v[11],
		&v[12], &v[13], &v[14], &v[15], &v[16], &v[17], &v[18], &n, &consumed) != 21) {
		fprintf(stderr, "bad case line: %s\n", line);
		exit(2);
	}
	// Clear what the previous case touched, then load this case's RAM.
	for (uae_u32 a : referee_touched)
		test_memory[a] = 0;
	referee_touched.clear();
	char *p = line + consumed;
	for (int i = 0; i < n; i++) {
		uae_u32 a, b;
		int used;
		if (sscanf(p, " %x:%x%n", &a, &b, &used) != 2) {
			fprintf(stderr, "bad ram pair in %s\n", id);
			exit(2);
		}
		p += used;
		a &= 0xffffff;
		test_memory[a] = (uae_u8)b;
		referee_touched.push_back(a);
	}
	struct referee_input in;
	for (int i = 0; i < 15; i++)
		in.d[i] = v[i];
	in.usp = v[15];
	in.ssp = v[16];
	in.sr = (uae_u16)v[17];
	in.pc = v[18] & 0xffffff;

	feature_exception_vectors = 0;
	execute_once(&in);
	const char *note = "";
	if (test_exception >= 4 && (mem_long(test_exception * 4) & 1)) {
		// A group 1/2 exception whose vector is odd takes an address error
		// while it is being processed: the tester's ODDEXC mode.  Undo the
		// instruction's writes and run it again in that mode.
		uae_u32 vector = mem_long(test_exception * 4);
		undo_memory(ahist, 0);
		feature_exception_vectors = vector;
		execute_once(&in);
		feature_exception_vectors = 0;
	} else if ((test_exception == 2 || test_exception == 3) && (mem_long(test_exception * 4) & 1)) {
		note = "doublefault,"; // odd vector 2/3: the tester skips halting tests
	}
	if (test_exception > 0 && (in.ssp & 1))
		note = "oddssp,"; // the frame would fault: outside the tester's model
	int trace = flag_SPCFLAG_DOTRACE ? 1 : 0;

	MakeSR();
	uae_u32 fusp, fssp;
	if (regs.s) {
		fssp = regs.regs[15];
		fusp = regs.usp;
	} else {
		fusp = regs.regs[15];
		fssp = regs.isp;
	}

	std::string out;
	char buf[512];
	int excyc = 0;
	if (test_exception > 0) {
		excyc = exception_cycles(test_exception);
		if (exception_extra_frame_type) {
			// check_cycles(): an address error during group 1/2 stacking.
			excyc += 7 * 4;
			if (exception_extra_frame_type == 7)
				excyc -= 4;
			if (exception_extra_frame_type >= 24 && exception_extra_frame_type < 24 + 8)
				excyc += 2 + 4 + 4;
		}
	}
	snprintf(buf, sizeof buf, "R %s exc=%d pc=%x sr=%x r=", id, test_exception, regs.pc, regs.sr);
	out += buf;
	for (int i = 0; i < 16; i++) {
		snprintf(buf, sizeof buf, i ? ",%x" : "%x", regs.regs[i]);
		out += buf;
	}
	snprintf(buf, sizeof buf, " usp=%x ssp=%x cyc=%d excyc=%d trace=%d frame=", fusp, fssp,
		cpu_cycles, excyc, trace);
	out += buf;
	if (test_exception > 0 && exception_stack_frame_size > 0) {
		uae_u8 *sf = test_memory + test_memory_size + EXTRA_RESERVED_SPACE - exception_stack_frame_size;
		hex_bytes(out, sf, exception_stack_frame_size);
	}
	out += " frame1=";
	if (exception_extra_frame_size > 0)
		hex_bytes(out, exception_extra_frame, exception_extra_frame_size);
	snprintf(buf, sizeof buf, " extra=%d w=", exception_extra_frame_type);
	out += buf;
	// Every byte the instruction wrote, with its final value.
	bool first = true;
	for (int i = 0; i < ahcnt_current; i++) {
		struct accesshistory *ah = &ahist[i];
		int size = ah->size == sz_byte ? 1 : ah->size == sz_word ? 2 : 4;
		for (int k = 0; k < size; k++) {
			uae_u32 a = (ah->addr + k) & 0xffffff;
			snprintf(buf, sizeof buf, first ? "%x:%x" : ",%x:%x", a, test_memory[a]);
			out += buf;
			first = false;
			referee_touched.push_back(a);
		}
	}
	snprintf(buf, sizeof buf, " flags=%s%s%s%s%s\n", note, out_of_test_space ? "oob," : "",
		cpu_halted ? "halted," : "", cpu_stopped ? "stopped," : "",
		hardware_bus_error ? "buserror," : "");
	out += buf;
	fputs(out.c_str(), stdout);
}

int main(int argc, char *argv[])
{
	referee_init();
	static char line[1 << 20];
	while (fgets(line, sizeof line, stdin)) {
		if (line[0] == 'Q') {
			break;
		} else if (line[0] == 'C') {
			run_case(line);
		} else if (line[0] == 'F') {
			fflush(stdout);
		} else if (line[0] == 'B') {
			uae_u32 start, size, mode;
			if (sscanf(line, "B %x %x %x", &start, &size, &mode) != 3) {
				fprintf(stderr, "bad bus-error line\n");
				return 2;
			}
			if (size) {
				safe_memory_start = start;
				safe_memory_end = start + size;
				safe_memory_mode = mode;
			} else {
				safe_memory_start = safe_memory_end = 0xffffffff;
				safe_memory_mode = 0;
			}
		}
	}
	fflush(stdout);
	return 0;
}
