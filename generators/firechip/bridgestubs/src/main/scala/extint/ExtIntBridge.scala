// See LICENSE for license details.

package firechip.bridgestubs

import chisel3._

import org.chipsalliance.cde.config.Parameters

import firesim.lib.bridgeutils._

import firechip.bridgeinterfaces._

class ExtIntBridge(nInts: Int)(implicit p: Parameters)
    extends BlackBox
    with Bridge[HostPortIO[ExtIntBridgeTargetIO]] {
  val moduleName = "firechip.goldengateimplementations.ExtIntBridgeModule"
  val io = IO(new ExtIntBridgeTargetIO(nInts))
  val bridgeIO = HostPort(io)
  val constructorArg = Some(ExtIntKey(nInts))
  generateAnnotations()
}

object ExtIntBridge {
  def apply(
      clock: Clock,
      intBundle: UInt,
      reset: Bool
  )(implicit p: Parameters): ExtIntBridge = {
    val nInts = intBundle.getWidth
    val ep = Module(new ExtIntBridge(nInts))
    ep.io.clock := clock
    ep.io.reset := reset
    intBundle := ep.io.ints
    ep
  }
}
