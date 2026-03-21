// See LICENSE for license details.
// rbb_dmi_bridge_t: accepts OpenOCD connections via remote_bitbang TCP,
// translates JTAG bitbang to DMI transactions, and drives the FireSim
// DMI bridge MMIO interface.

#ifndef __RBB_DMI_BRIDGE_H
#define __RBB_DMI_BRIDGE_H

#include "bridges/dmibridge.h"         // DMIBRIDGEMODULE_struct
#include "bridges/jtag_dtm_translator.h"
#include "bridges/remote_bitbang.h"
#include "core/bridge_driver.h"
#include "core/simif.h"

class rbb_dmi_bridge_t final : public bridge_driver_t {
public:
  static char KIND;

  rbb_dmi_bridge_t(simif_t &simif,
                   const DMIBRIDGEMODULE_struct &mmio_addrs,
                   int dmino,
                   const std::vector<std::string> &args);
  ~rbb_dmi_bridge_t();

  virtual void init() override;
  virtual void tick() override;
  virtual bool terminate() override { return rbb_ && rbb_->done(); }
  virtual int  exit_code() override { return rbb_ ? rbb_->exit_code() : 0; }

private:
  const DMIBRIDGEMODULE_struct mmio_addrs_;
  remote_bitbang_t *rbb_;
  jtag_dtm_translator_t translator_;
  bool  waiting_for_resp_;
  int   rbb_port_;

  void step_once();  // Advance simulation by one token
};

#endif // __RBB_DMI_BRIDGE_H
