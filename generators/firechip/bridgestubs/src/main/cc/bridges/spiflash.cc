#include "spiflash.h"
#include "core/simif.h"

#include <cstdio>
#include <cstring>
#include <fstream>

char spiflash_t::KIND;

spiflash_t::spiflash_t(simif_t &simif,
                       const SPIFLASHBRIDGEMODULE_struct &mmio_addrs,
                       int spiflashno,
                       const std::vector<std::string> &args)
    : bridge_driver_t(simif, &KIND), mmio_addrs(mmio_addrs),
      spiflashno(spiflashno), verbose(false), capacity(0) {

  std::string prefix_verbose = "+spiflash-verbose";
  char prefix_file[64];
  snprintf(prefix_file, sizeof(prefix_file), "+spiflash%d=", spiflashno);

  for (const auto &arg : args) {
    if (arg == prefix_verbose) {
      verbose = true;
    }
    if (arg.find(prefix_file) == 0) {
      std::string path = arg.substr(strlen(prefix_file));
      load_image(path);
    }
  }
}

spiflash_t::~spiflash_t() = default;

void spiflash_t::load_image(const std::string &path) {
  std::ifstream f(path, std::ios::binary | std::ios::ate);
  if (!f.is_open()) {
    fprintf(stderr, "SPIFLASH%d: WARNING: could not open image '%s'\n",
            spiflashno, path.c_str());
    return;
  }
  auto size = f.tellg();
  f.seekg(0);
  mem.resize(size);
  f.read(reinterpret_cast<char *>(mem.data()), size);
  if (verbose) {
    fprintf(stderr, "SPIFLASH%d: loaded %ld bytes from '%s'\n",
            spiflashno, (long)size, path.c_str());
  }
}

uint8_t spiflash_t::read_byte(uint32_t address) {
  if (address < mem.size()) {
    return mem[address];
  }
  return 0x00;
}

void spiflash_t::tick() {
  if (capacity == 0) {
    capacity = read(mmio_addrs.capacity);
    if (capacity > 0 && mem.empty()) {
      mem.resize(capacity, 0);
      if (verbose) {
        fprintf(stderr, "SPIFLASH%d: capacity=%u, no image loaded (all zeros)\n",
                spiflashno, capacity);
      }
    }
  }

  uint32_t req = read(mmio_addrs.data_req);
  if (!req)
    return;

  uint32_t cmd  = read(mmio_addrs.cmd);
  uint32_t addr = read(mmio_addrs.addr);
  uint8_t  byte = read_byte(addr);

  if (verbose) {
    fprintf(stderr, "SPIFLASH%d: cmd=0x%02x addr=0x%08x data=0x%02x\n",
            spiflashno, cmd, addr, byte);
  }

  write(mmio_addrs.data_resp, byte);
  write(mmio_addrs.data_resp_valid, 1);
}
