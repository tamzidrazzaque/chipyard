// See LICENSE for license details.

package firechip.bridgeinterfaces

import chisel3._

class ExtIntBridgeTargetIO(val nInts: Int) extends Bundle {
  val clock = Input(Clock())
  val ints = Output(UInt(nInts.W))
  val reset = Input(Bool())
}

case class ExtIntKey(nInts: Int)
