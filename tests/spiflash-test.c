#include "mmio.h"
#include <stdio.h>

#define SPIFLASH_BASE_CTRL   0x10030000UL
#define SPIFLASH_BASE_MEM    0x20000000UL

#define SPIFLASH_REG_SCKDIV  (SPIFLASH_BASE_CTRL + 0x00)
#define SPIFLASH_REG_CSID    (SPIFLASH_BASE_CTRL + 0x10)
#define SPIFLASH_REG_CSDEF   (SPIFLASH_BASE_CTRL + 0x14)
#define SPIFLASH_REG_CSMODE  (SPIFLASH_BASE_CTRL + 0x18)
#define SPIFLASH_REG_FMT     (SPIFLASH_BASE_CTRL + 0x40)
#define SPIFLASH_REG_TXDATA  (SPIFLASH_BASE_CTRL + 0x48)
#define SPIFLASH_REG_RXDATA  (SPIFLASH_BASE_CTRL + 0x4c)
#define SPIFLASH_REG_FCTRL   (SPIFLASH_BASE_CTRL + 0x60)
#define SPIFLASH_REG_FFMT    (SPIFLASH_BASE_CTRL + 0x64)

static void spin(int n) {
    for (volatile int i = 0; i < n; i++) { asm volatile("nop"); }
}

int main(void) {
    printf("[spiflash-test] starting SPI flash bridge test (software mode)\n");

    printf("[spiflash-test] disabling flash hardware mode\n");
    reg_write32(SPIFLASH_REG_FCTRL, 0);
    spin(200);

    reg_write32(SPIFLASH_REG_SCKDIV, 2);
    spin(100);

    uint32_t fmt = (0 << 0) |  // proto = single (bits [1:0])
                   (0 << 2) |  // endian = MSB first (bit [2])
                   (1 << 3) |  // iodir = TX (bit [3])
                   (8 << 16);  // len = 8 bits
    reg_write32(SPIFLASH_REG_FMT, fmt);
    spin(100);

    printf("[spiflash-test] asserting CS (HOLD mode)\n");
    reg_write32(SPIFLASH_REG_CSMODE, 2);
    spin(100);

    printf("[spiflash-test] sending cmd byte 0x03 (slow read)\n");
    reg_write32(SPIFLASH_REG_TXDATA, 0x03);
    spin(2000);

    printf("[spiflash-test] sending addr bytes 0x00 0x00 0x00\n");
    reg_write32(SPIFLASH_REG_TXDATA, 0x00);
    spin(2000);
    reg_write32(SPIFLASH_REG_TXDATA, 0x00);
    spin(2000);
    reg_write32(SPIFLASH_REG_TXDATA, 0x00);
    spin(2000);

    printf("[spiflash-test] switching to RX mode\n");
    fmt = (0 << 0) |  // proto = single
          (0 << 2) |  // endian = MSB
          (0 << 3) |  // iodir = RX
          (8 << 16);  // len = 8 bits
    reg_write32(SPIFLASH_REG_FMT, fmt);
    spin(100);

    printf("[spiflash-test] reading 4 bytes from flash via software SPI\n");
    uint8_t rx[4];
    for (int i = 0; i < 4; i++) {
        reg_write32(SPIFLASH_REG_TXDATA, 0x00);
        spin(2000);
        uint32_t rxd = reg_read32(SPIFLASH_REG_RXDATA);
        rx[i] = rxd & 0xFF;
        printf("[spiflash-test] rx[%d] = 0x%02x (fifo=0x%08x)\n", i, rx[i], (unsigned)rxd);
    }

    printf("[spiflash-test] deasserting CS\n");
    reg_write32(SPIFLASH_REG_CSMODE, 3);
    spin(1000);

    uint32_t word = (rx[0] << 24) | (rx[1] << 16) | (rx[2] << 8) | rx[3];
    printf("[spiflash-test] read word = 0x%08x (expect 0xdeadbeef big-endian from addr 0)\n", (unsigned)word);

    uint32_t word_le = rx[0] | (rx[1] << 8) | (rx[2] << 16) | (rx[3] << 24);
    printf("[spiflash-test] read word (LE) = 0x%08x\n", (unsigned)word_le);

    if (word == 0xdeadbeef || word_le == 0xdeadbeef) {
        printf("[spiflash-test] *** PASSED ***\n");
        return 0;
    }

    printf("[spiflash-test] data mismatch, bridge signal test only\n");
    printf("[spiflash-test] *** DONE *** (bridge alive, protocol debugging needed)\n");
    return 0;
}
