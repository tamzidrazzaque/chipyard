// See LICENSE for license details.

#include "bridges/jtagbridge.h"

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>

char jtagbridge_t::KIND;

static const int DEFAULT_RBB_PORT = 25000;

jtagbridge_t::jtagbridge_t(simif_t &simif,
                           const JTAGBRIDGEMODULE_struct &mmio_addrs,
                           int jtagno,
                           const std::vector<std::string> &args)
    : bridge_driver_t(simif, &KIND),
      mmio_addrs_(mmio_addrs),
      rbb_(nullptr),
      rbb_port_(DEFAULT_RBB_PORT + jtagno) {
  for (auto &arg : args) {
    if (arg.find("+jtag_rbb_port=") == 0) {
      rbb_port_ = std::atoi(arg.c_str() + 15);
    }
  }
}

jtagbridge_t::~jtagbridge_t() { delete rbb_; }

void jtagbridge_t::init() {
  rbb_ = new remote_bitbang_t((uint16_t)rbb_port_);
  std::cout << "[JTAGBridge] remote_bitbang listening on port " << rbb_port_
            << std::endl;
}

void jtagbridge_t::tick() {
  if (!rbb_)
    return;

  unsigned char tck = 0, tms = 0, tdi = 0, trstn = 0;
  unsigned char tdo = (unsigned char)read(mmio_addrs_.tdo);

  rbb_->tick(&tck, &tms, &tdi, &trstn, tdo);

  write(mmio_addrs_.tck, tck);
  write(mmio_addrs_.tms, tms);
  write(mmio_addrs_.tdi, tdi);
}
