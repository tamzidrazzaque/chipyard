// See LICENSE for license details.

#ifndef __GPIO_H
#define __GPIO_H

#include "core/bridge_driver.h"

#include <cstdint>
#include <string>
#include <vector>

struct GPIOBRIDGEMODULE_struct {
  uint64_t out_values;
  uint64_t out_enables;
  uint64_t in_values;
  uint64_t width;
};

class gpio_t final : public bridge_driver_t {
public:
  static char KIND;

  gpio_t(simif_t &simif,
         const GPIOBRIDGEMODULE_struct &mmio_addrs,
         int gpiono,
         const std::vector<std::string> &args);

  ~gpio_t() override;

  void tick() override;

private:
  const GPIOBRIDGEMODULE_struct mmio_addrs;
  int gpiono;
  uint32_t width;
  uint32_t current_in;
  uint32_t last_out;
  uint32_t last_oe;
  bool verbose;
};

#endif // __GPIO_H
