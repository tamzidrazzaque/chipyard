package firechip.bridgeinterfaces

import chisel3._

class SPIFlashBridgeTargetIO(val csWidth: Int) extends Bundle {
  val clock = Input(Clock())
  val reset = Input(Bool())
  val sck   = Input(Bool())
  val cs    = Vec(csWidth, Input(Bool()))
  val dq_o  = Vec(4, Input(Bool()))
  val dq_oe = Vec(4, Input(Bool()))
  val dq_i  = Vec(4, Output(Bool()))
}

case class SPIFlashKey(csWidth: Int, capacityBytes: Int)
