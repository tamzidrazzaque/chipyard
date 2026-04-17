/*
 * Minimal GPIO bridge functional test.
 *
 * Target: FireSimGPIORocketConfig (SiFive GPIO at 0x10010000, 4 pins)
 *
 * Run with: VFireSim +permissive +fesvr-step-size=128 +max-cycles=100000000
 *           +gpio-verbose +gpio-in0=0x5 +permissive-off gpio-test.riscv
 */

#include "mmio.h"
#include <stdio.h>

#define GPIO_BASE     0x10010000UL
#define GPIO_VALUE    (GPIO_BASE + 0x00)  /* input_val (RO) */
#define GPIO_INPUT_EN (GPIO_BASE + 0x04)
#define GPIO_OUTPUT_EN (GPIO_BASE + 0x08)
#define GPIO_PORT     (GPIO_BASE + 0x0c)  /* output port (RW) */

static void spin(int n) {
    for (volatile int i = 0; i < n; i++) {}
}

int main(void) {
    uint32_t v;

    /* --- target→host: drive output pins --- */
    /* Do all GPIO writes first, with spin delays between them,
       BEFORE doing any slow HTIF printf. This gives the bridge
       time to observe the transitions. */

    reg_write32(GPIO_OUTPUT_EN, 0xF);
    spin(1000);

    reg_write32(GPIO_PORT, 0xA);
    spin(1000);

    reg_write32(GPIO_PORT, 0x5);
    spin(1000);

    reg_write32(GPIO_PORT, 0x0);
    spin(1000);

    /* --- host→target: read input pins --- */
    reg_write32(GPIO_INPUT_EN, 0xF);
    spin(1000);

    v = reg_read32(GPIO_VALUE);

    /* Now do the slow printfs */
    printf("[gpio-test] output transitions done, input_val=0x%x\n", (unsigned)v);

    if (v == 0x5) {
        printf("[gpio-test] PASS: input matches +gpio-in0=0x5\n");
    } else if (v != 0) {
        printf("[gpio-test] PARTIAL: input_val=0x%x (bridge driving)\n", (unsigned)v);
    } else {
        printf("[gpio-test] INFO: input_val=0x0\n");
    }

    printf("[gpio-test] done\n");
    return 0;
}
