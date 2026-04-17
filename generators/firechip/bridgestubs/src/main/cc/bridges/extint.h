// See LICENSE for license details.

#ifndef __EXTINT_H
#define __EXTINT_H

#include "core/bridge_driver.h"

#include <cstdint>
#include <string>
#include <vector>

struct EXTINTBRIDGEMODULE_struct {
  uint64_t int_values;
  uint64_t width;
};

class extint_t final : public bridge_driver_t {
public:
  static char KIND;

  extint_t(simif_t &simif,
           const EXTINTBRIDGEMODULE_struct &mmio_addrs,
           int extintno,
           const std::vector<std::string> &args);

  ~extint_t() override;

  void tick() override;

private:
  const EXTINTBRIDGEMODULE_struct mmio_addrs;
  int extintno;
  uint32_t width;
  uint32_t current_ints;
  bool verbose;
};

#endif // __EXTINT_H
