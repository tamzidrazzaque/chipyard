// See LICENSE for license details.

package firechip.bridgeinterfaces

import chisel3._

class GPIOBridgeTargetIO(val nGPIO: Int) extends Bundle {
  val clock = Input(Clock())
  val pins_out = Input(UInt(nGPIO.W))
  val pins_oe = Input(UInt(nGPIO.W))
  val pins_in = Output(UInt(nGPIO.W))
  val reset = Input(Bool())
}

case class GPIOKey(nGPIO: Int, gpioId: Int)
