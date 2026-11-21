/* SPDX-License-Identifier: MIT
 *
 * Print Musashi's verdict on every 68000 first word, one line each:
 *   <word hex> <valid 0/1> <disassembly>
 *
 * Musashi (Karl Stenerud, MIT) is built from its own m68kdasm.c, fetched at
 * the pin in build_referees.py; no Musashi source is copied here.  Used by
 * scripts/check_decoder_vs_musashi.py to check the opcode map
 * (docs/validation.md, rung 1).
 */

#include <stdio.h>

#include "m68k.h"

static unsigned int word;

/* The word under test sits at address 0; extension words read as zero. */
unsigned int m68k_read_disassembler_16(unsigned int address) { return address == 0 ? word : 0; }
unsigned int m68k_read_disassembler_32(unsigned int address) { return address == 0 ? word << 16 : 0; }
unsigned int m68k_read_memory_8(unsigned int address) { (void)address; return 0; }
unsigned int m68k_read_memory_16(unsigned int address) { (void)address; return 0; }
unsigned int m68k_read_memory_32(unsigned int address) { (void)address; return 0; }

int main(void)
{
    char text[128];
    for (word = 0; word < 0x10000; word++) {
        unsigned int valid = m68k_is_valid_instruction(word, M68K_CPU_TYPE_68000);
        m68k_disassemble(text, 0, M68K_CPU_TYPE_68000);
        printf("%04x %u %s\n", word, valid ? 1u : 0u, text);
    }
    return 0;
}
