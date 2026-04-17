// See LICENSE for license details.

#include "extint.h"
#include "core/simif.h"

#include <cstdio>

char extint_t::KIND;

extint_t::extint_t(simif_t &simif,
                   const EXTINTBRIDGEMODULE_struct &mmio_addrs,
                   int extintno,
                   const std::vector<std::string> &args)
    : bridge_driver_t(simif, &KIND), mmio_addrs(mmio_addrs),
      extintno(extintno), width(0), current_ints(0), verbose(false) {
  std::string verbose_arg = "+extint-verbose";
  std::string val_arg =
      std::string("+extint") + std::to_string(extintno) + "=";

  for (const auto &arg : args) {
    if (arg == verbose_arg) {
      verbose = true;
    }
    if (arg.find(val_arg) == 0) {
      current_ints =
          static_cast<uint32_t>(strtoul(arg.c_str() + val_arg.length(), nullptr, 0));
    }
  }
}

extint_t::~extint_t() = default;

void extint_t::tick() {
  if (width == 0) {
    width = static_cast<uint32_t>(read(mmio_addrs.width));
    if (width == 0)
      return;
    if (verbose) {
      printf("ExtInt%d: width = %u interrupts\n", extintno, width);
    }
  }

  write(mmio_addrs.int_values, current_ints);
}
