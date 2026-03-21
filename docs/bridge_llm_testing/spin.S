/* Minimal RISC-V bare-metal test: set a0=42 then spin forever.
 * Used to verify OpenOCD can halt the target and read registers.
 *
 * Build:
 *   riscv64-unknown-elf-gcc -march=rv64ima -mabi=lp64 -nostdlib \
 *     -T spin.ld spin.S -o spin.elf
 *
 * Expected state after halt:
 *   a0 = 0x2a (42)
 *   pc = somewhere inside the spin loop
 */
.section .text
.globl _start
_start:
    li   a0, 42
spin:
    j    spin
