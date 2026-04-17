// See LICENSE for license details.

package firechip.goldengateimplementations

import chisel3._

import org.chipsalliance.cde.config.Parameters

import midas.widgets._
import firesim.lib.bridgeutils._

import firechip.bridgeinterfaces._

class ExtIntBridgeModule(key: ExtIntKey)(implicit p: Parameters)
    extends BridgeModule[HostPortIO[ExtIntBridgeTargetIO]]()(p) {
  lazy val module = new BridgeModuleImp(this) {
    val io = IO(new WidgetIO())
    val hPort = IO(HostPort(new ExtIntBridgeTargetIO(key.nInts)))

    val fire = hPort.toHost.hValid && hPort.fromHost.hReady
    val targetReset = fire & hPort.hBits.reset

    hPort.toHost.hReady := fire
    hPort.fromHost.hValid := fire

    val intsReg = RegInit(0.U(key.nInts.W))

    when(targetReset) {
      intsReg := 0.U
    }

    hPort.hBits.ints := intsReg

    genWOReg(intsReg, "int_values")
    genROReg(key.nInts.U(32.W), "width")

    genCRFile()

    override def genHeader(
        base: BigInt,
        memoryRegions: Map[String, BigInt],
        sb: StringBuilder
    ): Unit = {
      genConstructor(base, sb, "extint_t", "extint")
    }
  }
}
