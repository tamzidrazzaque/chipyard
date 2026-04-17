// See LICENSE for license details.

#include "gpio.h"
#include "core/simif.h"

#include <cstdio>

char gpio_t::KIND;

gpio_t::gpio_t(simif_t &simif,
               const GPIOBRIDGEMODULE_struct &mmio_addrs,
               int gpiono,
               const std::vector<std::string> &args)
    : bridge_driver_t(simif, &KIND), mmio_addrs(mmio_addrs), gpiono(gpiono),
      width(0), current_in(0), last_out(~0u), last_oe(~0u), verbose(false) {
  std::string verbose_arg = "+gpio-verbose";
  std::string in_arg =
      std::string("+gpio-in") + std::to_string(gpiono) + "=";

  for (const auto &arg : args) {
    if (arg == verbose_arg) {
      verbose = true;
    }
    if (arg.find(in_arg) == 0) {
      current_in =
          static_cast<uint32_t>(strtoul(arg.c_str() + in_arg.length(), nullptr, 0));
    }
  }
}

gpio_t::~gpio_t() = default;

void gpio_t::tick() {
  if (width == 0) {
    width = static_cast<uint32_t>(read(mmio_addrs.width));
    if (width == 0)
      return;
    if (verbose) {
      printf("GPIO%d: width = %u pins\n", gpiono, width);
    }
  }

  uint32_t out = static_cast<uint32_t>(read(mmio_addrs.out_values));
  uint32_t oe = static_cast<uint32_t>(read(mmio_addrs.out_enables));

  if (verbose && (out != last_out || oe != last_oe)) {
    printf("GPIO%d: out=0x%08x oe=0x%08x\n", gpiono, out, oe);
  }

  last_out = out;
  last_oe = oe;

  write(mmio_addrs.in_values, current_in);
}
