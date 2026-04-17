#ifndef __SPIFLASH_BRIDGE_H
#define __SPIFLASH_BRIDGE_H

#include "core/bridge_driver.h"

#include <cstdint>
#include <string>
#include <vector>

struct SPIFLASHBRIDGEMODULE_struct {
  uint64_t data_resp;
  uint64_t data_resp_valid;
  uint64_t cmd;
  uint64_t addr;
  uint64_t data_req;
  uint64_t cs_width;
  uint64_t capacity;
  uint64_t fire_count;
  uint64_t sck_edge_count;
};

class spiflash_t final : public bridge_driver_t {
public:
  static char KIND;

  spiflash_t(simif_t &simif,
             const SPIFLASHBRIDGEMODULE_struct &mmio_addrs,
             int spiflashno,
             const std::vector<std::string> &args);
  ~spiflash_t() override;

  void init() override {}
  void tick() override;
  bool terminate() override { return false; }
  int exit_code() override { return 0; }
  void finish() override {}

private:
  const SPIFLASHBRIDGEMODULE_struct mmio_addrs;
  int spiflashno;
  bool verbose;

  uint32_t capacity;
  std::vector<uint8_t> mem;

  void load_image(const std::string &path);
  uint8_t read_byte(uint32_t address);
};

#endif // __SPIFLASH_BRIDGE_H
