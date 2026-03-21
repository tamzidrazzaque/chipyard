// See LICENSE for license details.
// JTAG TAP state machine implementation.

#include "bridges/jtag_dtm_translator.h"
#include <cstring>
#include <iostream>

jtag_dtm_translator_t::jtag_dtm_translator_t()
    : tap_state_(TestLogicReset),
      prev_tck_(0),
      ir_(IR_IDCODE),      // power-on default = IDCODE
      ir_shift_(0),
      dr_shift_(0),
      dr_nbits_(0),
      tdo_(0),
      shift_count_(0),
      resp_valid_(true)    // start valid so initial IDCODE/DTMCS reads work
{
  last_resp_ = {0, 0};
}

// TAP state transition table
TapState jtag_dtm_translator_t::next_state(TapState s, uint8_t tms) const {
  switch (s) {
    case TestLogicReset: return tms ? TestLogicReset : RunTestIdle;
    case RunTestIdle:    return tms ? SelectDRScan   : RunTestIdle;
    case SelectDRScan:   return tms ? SelectIRScan   : CaptureDR;
    case CaptureDR:      return tms ? Exit1DR        : ShiftDR;
    case ShiftDR:        return tms ? Exit1DR        : ShiftDR;
    case Exit1DR:        return tms ? UpdateDR       : PauseDR;
    case PauseDR:        return tms ? Exit2DR        : PauseDR;
    case Exit2DR:        return tms ? UpdateDR       : ShiftDR;
    case UpdateDR:       return tms ? SelectDRScan   : RunTestIdle;
    case SelectIRScan:   return tms ? TestLogicReset : CaptureIR;
    case CaptureIR:      return tms ? Exit1IR        : ShiftIR;
    case ShiftIR:        return tms ? Exit1IR        : ShiftIR;
    case Exit1IR:        return tms ? UpdateIR       : PauseIR;
    case PauseIR:        return tms ? Exit2IR        : PauseIR;
    case Exit2IR:        return tms ? UpdateIR       : ShiftIR;
    case UpdateIR:       return tms ? SelectDRScan   : RunTestIdle;
    default:             return TestLogicReset;
  }
}

int jtag_dtm_translator_t::dr_length() const {
  switch (ir_) {
    case IR_IDCODE:    return 32;
    case IR_DTM_DMI:   return 41; // 2b_op + 7b_addr + 32b_data
    case IR_DTM_DTMCS: return 32;
    case IR_BYPASS:    return 1;
    default:           return 1;
  }
}

// Value loaded into DR shift register on CaptureDR
uint64_t jtag_dtm_translator_t::capture_dr_value() const {
  switch (ir_) {
    case IR_IDCODE:
      return 0x10000001ULL; // version=1, dummy manufact/part

    case IR_DTM_DTMCS: {
      // dtmcs: abridgegement bits [31:16]=0, [15:12]=idle=5, [11:10]=dmistat=0,
      //        [9:4]=abits=7, [3:0]=version=1
      uint32_t abits = 7;
      uint32_t idle  = 5;
      return (idle << 12) | (abits << 4) | 0x1;
    }

    case IR_DTM_DMI: {
      // DMI response format (41 bits): [40:34]=addr_echo, [33:2]=data, [1:0]=resp
      if (!resp_valid_) {
        // Not yet a response — signal busy
        return (uint64_t)DMI_RESP_BUSY; // bits[1:0] = 3, rest = 0
      }
      uint64_t dr_val = ((uint64_t)(last_resp_.resp & 0x3)) |
                        ((uint64_t)(last_resp_.data & 0xFFFFFFFFULL) << 2);
      return dr_val;
    }

    case IR_BYPASS:
    default:
      return 0;
  }
}

void jtag_dtm_translator_t::on_update_dr() {
  if (ir_ == IR_DTM_DMI) {
    // DR layout (41 bits shifted LSB-first, so after shift dr_shift_ holds):
    //   bits[40:34] = addr (7 bits) -- top bits shifted in last
    //   bits[33:2]  = data (32 bits)
    //   bits[1:0]   = op   (2 bits) -- bottom bits shifted in first
    uint32_t op   = (uint32_t)(dr_shift_ & 0x3);
    uint32_t data = (uint32_t)((dr_shift_ >> 2) & 0xFFFFFFFFULL);
    uint32_t addr = (uint32_t)((dr_shift_ >> 34) & 0x7F);

    if (op != DMI_OP_NOP) {
      pending_req_ = dmi_req_t{addr, data, op};
      resp_valid_  = false; // response for this new request not yet available
    }
  }
  // DTMCS writes (e.g. dmireset) are ignored for now
}

void jtag_dtm_translator_t::clock_edge(uint8_t tck, uint8_t tms, uint8_t tdi) {
  // Only act on the rising edge of TCK
  if (!prev_tck_ && tck) {
    TapState next = next_state(tap_state_, tms);

    switch (tap_state_) {
      case TestLogicReset:
        ir_ = IR_IDCODE;  // reset IR to IDCODE
        tdo_ = 0;
        break;

      case CaptureDR:
        // Load DR with captured value; TDO outputs LSB
        dr_shift_    = capture_dr_value();
        dr_nbits_    = dr_length();
        shift_count_ = 0;
        tdo_         = (uint8_t)(dr_shift_ & 1);
        break;

      case ShiftDR:
        // Shift first (TDI goes to MSB), then output the new LSB as TDO.
        // OpenOCD reads TDO before the rising edge (while TCK=0), so tdo_ must
        // reflect the bit that will be valid *after* the current shift cycle.
        dr_shift_ = (dr_shift_ >> 1) | ((uint64_t)(tdi & 1) << (dr_nbits_ - 1));
        tdo_      = (uint8_t)(dr_shift_ & 1);
        shift_count_++;
        break;

      case UpdateDR:
        on_update_dr();
        tdo_ = 0;
        break;

      case CaptureIR:
        // Load IR shift register with current IR (LSBs = 01 per spec)
        ir_shift_    = (ir_ & ~0x3U) | 0x1U;
        shift_count_ = 0;
        tdo_         = (uint8_t)(ir_shift_ & 1);
        break;

      case ShiftIR:
        // Same shift-first model as ShiftDR.
        ir_shift_ = (ir_shift_ >> 1) | ((uint32_t)(tdi & 1) << (IR_BITS - 1));
        tdo_      = (uint8_t)(ir_shift_ & 1);
        shift_count_++;
        break;

      case UpdateIR:
        ir_  = ir_shift_ & ((1U << IR_BITS) - 1);
        tdo_ = 0;
        break;

      default:
        tdo_ = 0;
        break;
    }

    tap_state_ = next;
  }
  prev_tck_ = tck;
}
