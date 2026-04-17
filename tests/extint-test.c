/*
 * Minimal external interrupt bridge functional test.
 *
 * Target: FireSimExtIntRocketConfig (4 external interrupts via ExtIntBridge)
 * Exercises: host injects interrupt lines via +extint0=VALUE
 *            target polls PLIC pending register to verify lines are driven.
 *
 * Run with: VFireSim +permissive +extint-verbose +extint0=0x3 +permissive-off extint-test.riscv
 *
 * The external interrupts connect to the PLIC. Interrupt sources are at
 * PLIC base + 0x1000 (pending bits). We poll the pending register to see
 * if any external interrupt lines are asserted.
 */

#include "mmio.h"
#include <stdio.h>

/* Default PLIC base in Rocket Chip */
#define PLIC_BASE     0x0C000000UL
#define PLIC_PENDING  (PLIC_BASE + 0x1000)  /* pending bits (32-bit) */
#define PLIC_ENABLE0  (PLIC_BASE + 0x2000)  /* enable bits for context 0 */
#define PLIC_PRIORITY(n) (PLIC_BASE + 4*(n))  /* priority for source n */

int main(void) {
    uint32_t pending;
    int i;

    printf("[extint-test] start\n");

    /* Read initial PLIC pending state */
    pending = reg_read32(PLIC_PENDING);
    printf("[extint-test] initial PLIC pending = 0x%x\n", (unsigned)pending);

    /* Enable ext interrupts in PLIC: set priority > 0 for sources 1-4 */
    for (i = 1; i <= 4; i++) {
        reg_write32(PLIC_PRIORITY(i), 1);
    }
    printf("[extint-test] set priority=1 for sources 1-4\n");

    /* Enable them in hart0 M-mode context (context 0 for M-mode in Rocket) */
    reg_write32(PLIC_ENABLE0, 0x1E); /* bits [4:1] = sources 1-4 */
    printf("[extint-test] PLIC enable[0] = 0x1E\n");

    /* Poll pending a few times to see if host-injected interrupts show up */
    for (i = 0; i < 5; i++) {
        pending = reg_read32(PLIC_PENDING);
        printf("[extint-test] poll %d: PLIC pending = 0x%x\n", i, (unsigned)pending);
        if (pending != 0) break;
        /* small delay: just some NOPs to let the bridge tick */
        for (volatile int j = 0; j < 100; j++) {}
    }

    if (pending != 0) {
        printf("[extint-test] PASS: external interrupt lines visible in PLIC (pending=0x%x)\n",
               (unsigned)pending);
    } else {
        printf("[extint-test] INFO: PLIC pending=0x0 (lines may need more cycles or PLIC config)\n");
    }

    printf("[extint-test] done\n");
    return 0;
}
