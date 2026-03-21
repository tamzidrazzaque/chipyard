// See LICENSE for license details.
// Pure C++ JTAG TAP state machine that translates JTAG bitbang to DMI transactions.
// No FireSim or simulation dependencies — testable standalone.

#ifndef __JTAG_DTM_TRANSLATOR_H
#define __JTAG_DTM_TRANSLATOR_H

#include <cstdint>
#include <optional>

// TAP states per IEEE 1149.1
enum TapState {
  TestLogicReset = 0,
  RunTestIdle,
  SelectDRScan,
  CaptureDR,
  ShiftDR,
  Exit1DR,
  PauseDR,
  Exit2DR,
  UpdateDR,
  SelectIRScan,
  CaptureIR,
  ShiftIR,
  Exit1IR,
  PauseIR,
  Exit2IR,
  UpdateIR
};

// JTAG IR values for RISC-V DTM
enum JtagIR {
  IR_IDCODE    = 0x01,
  IR_DTM_DMI   = 0x11, // DMI_ACCESS
  IR_DTM_DTMCS = 0x10, // DTMCS
  IR_BYPASS    = 0x1F,
};

// DMI operation codes
enum DmiOp {
  DMI_OP_NOP   = 0,
  DMI_OP_READ  = 1,
  DMI_OP_WRITE = 2,
};

// DMI response codes
enum DmiResp {
  DMI_RESP_OK      = 0,
  DMI_RESP_FAILURE = 1,
  DMI_RESP_HW_FAIL = 2,
  DMI_RESP_BUSY    = 3,
};

struct dmi_req_t {
  uint32_t addr;
  uint32_t data;
  uint32_t op;
};

struct dmi_resp_t {
  uint32_t data;
  uint32_t resp;
};

// JTAG TAP state machine that converts raw JTAG bitbang (TCK/TMS/TDI) into
// DMI transactions (addr/data/op) and consumes DMI responses to produce TDO.
//
// Usage:
//   1. Call clock_edge(tck, tms, tdi) on each TCK rising edge to advance state.
//   2. Call get_tdo() to read the current TDO output (valid after clock_edge).
//   3. Poll has_dmi_req() and call take_dmi_req() to extract a pending DMI transaction.
//   4. When the DMI response arrives, call set_dmi_resp(resp).
//   5. Call clear_dmi_resp() after issuing the MMIO request to trigger busy signalling.
class jtag_dtm_translator_t {
public:
  jtag_dtm_translator_t();

  // Advance the TAP state machine on one TCK cycle.
  // tck=1 means rising edge (latch), tck=0 means falling edge (shift).
  // This simplified model calls the TAP logic on the rising edge of TCK.
  void clock_edge(uint8_t tck, uint8_t tms, uint8_t tdi);

  // TDO output (valid after clock_edge)
  uint8_t get_tdo() const { return tdo_; }

  // DMI request output: set after UpdateDR with IR=DMI_ACCESS and non-NOP op
  bool has_dmi_req() const { return pending_req_.has_value(); }
  dmi_req_t take_dmi_req() {
    dmi_req_t req = pending_req_.value();
    pending_req_.reset();
    return req;
  }

  // DMI response input: called when MMIO response is available
  void set_dmi_resp(dmi_resp_t resp) { last_resp_ = resp; resp_valid_ = true; }
  // Clear validity so busy is reported until next response arrives
  void clear_dmi_resp() { resp_valid_ = false; }

  TapState get_tap_state() const { return tap_state_; }
  uint64_t get_ir() const { return ir_; }

private:
  TapState tap_state_;
  uint8_t  prev_tck_;

  // IR register (5 bits for RISC-V DTM)
  static const int IR_BITS = 5;
  uint32_t ir_;      // current instruction
  uint32_t ir_shift_; // shift register for IR

  // DR shift register (max 41 bits for DMI)
  static const int DR_MAX_BITS = 41;
  uint64_t dr_shift_;  // DR shift register
  int      dr_nbits_;  // number of bits being shifted for current DR

  uint8_t tdo_;        // current TDO output
  int     shift_count_; // bits shifted so far in ShiftDR/ShiftIR

  // DMI state
  std::optional<dmi_req_t> pending_req_;
  dmi_resp_t last_resp_;
  bool       resp_valid_; // true if last_resp_ is fresh (not yet consumed)

  // TAP transition
  TapState next_state(TapState s, uint8_t tms) const;

  // DR operations per instruction
  int       dr_length() const;
  uint64_t  capture_dr_value() const;
  void      on_update_dr();
};

#endif // __JTAG_DTM_TRANSLATOR_H
