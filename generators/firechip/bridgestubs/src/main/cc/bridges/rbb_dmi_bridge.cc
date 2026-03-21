// See LICENSE for license details.
// rbb_dmi_bridge_t implementation.

#include "bridges/rbb_dmi_bridge.h"
#include "core/simif.h"

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>

char rbb_dmi_bridge_t::KIND;

static const int DEFAULT_RBB_PORT = 23000;

rbb_dmi_bridge_t::rbb_dmi_bridge_t(simif_t &simif,
                                    const DMIBRIDGEMODULE_struct &mmio_addrs,
                                    int dmino,
                                    const std::vector<std::string> &args)
    : bridge_driver_t(simif, &KIND),
      mmio_addrs_(mmio_addrs),
      rbb_(nullptr),
      waiting_for_resp_(false),
      rbb_port_(DEFAULT_RBB_PORT + dmino)
{
  for (auto &arg : args) {
    if (arg.find("+rbb-dmi-port=") == 0) {
      rbb_port_ = std::atoi(arg.c_str() + 14);
    }
  }
}

rbb_dmi_bridge_t::~rbb_dmi_bridge_t() {
  delete rbb_;
}

void rbb_dmi_bridge_t::init() {
  rbb_ = new remote_bitbang_t((uint16_t)rbb_port_);
  std::cout << "[rbb_dmi_bridge] Listening for OpenOCD on port " << rbb_port_
            << " (use: openocd -f interface/remote_bitbang.cfg)\n";

  // Start with step_size=1 so each tick() advances exactly one target cycle.
  write(mmio_addrs_.step_size, 1);
  step_once();
}

void rbb_dmi_bridge_t::step_once() {
  write(mmio_addrs_.start, 1);
}

void rbb_dmi_bridge_t::tick() {
  // ---- 1. Poll for a pending DMI response from the target ----
  if (waiting_for_resp_) {
    if (read(mmio_addrs_.out_valid)) {
      dmi_resp_t resp;
      resp.data = (uint32_t)read(mmio_addrs_.out_bits_data);
      resp.resp = (uint32_t)read(mmio_addrs_.out_bits_resp);
      write(mmio_addrs_.out_ready, 1); // dequeue the response
      translator_.set_dmi_resp(resp);
      waiting_for_resp_ = false;
    } else {
      // Response not yet ready — advance simulation and return
      if (read(mmio_addrs_.done)) step_once();
      return;
    }
  }

  // ---- 2. Process one JTAG bitbang cycle from OpenOCD ----
  if (rbb_) {
    unsigned char tck = 0, tms = 0, tdi = 0, trstn = 0;
    unsigned char tdo = translator_.get_tdo();
    rbb_->tick(&tck, &tms, &tdi, &trstn, tdo);
    translator_.clock_edge(tck, tms, tdi);
  }

  // ---- 3. If translator has a DMI request, enqueue it ----
  if (translator_.has_dmi_req() && read(mmio_addrs_.in_ready)) {
    dmi_req_t req = translator_.take_dmi_req();
    write(mmio_addrs_.in_bits_addr, req.addr);
    write(mmio_addrs_.in_bits_data, req.data);
    write(mmio_addrs_.in_bits_op,   req.op);
    write(mmio_addrs_.in_valid, 1); // enqueue (pulsified in hardware)
    waiting_for_resp_ = true;
    translator_.clear_dmi_resp(); // signal busy until response arrives
  }

  // ---- 4. Advance simulation by one token ----
  if (read(mmio_addrs_.done)) {
    step_once();
  }
}
