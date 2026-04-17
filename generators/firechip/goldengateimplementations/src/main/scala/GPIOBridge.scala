// See LICENSE for license details.

package firechip.goldengateimplementations

import chisel3._
import chisel3.util._

import org.chipsalliance.cde.config.Parameters

import midas.widgets._
import firesim.lib.bridgeutils._

import firechip.bridgeinterfaces._

class GPIOBridgeModule(key: GPIOKey)(implicit p: Parameters)
    extends BridgeModule[HostPortIO[GPIOBridgeTargetIO]]()(p) {
  lazy val module = new BridgeModuleImp(this) {
    val io = IO(new WidgetIO())
    val hPort = IO(HostPort(new GPIOBridgeTargetIO(key.nGPIO)))

    val fire = hPort.toHost.hValid && hPort.fromHost.hReady
    val targetReset = fire & hPort.hBits.reset

    hPort.toHost.hReady := fire
    hPort.fromHost.hValid := fire

    val outReg = RegInit(0.U(key.nGPIO.W))
    val oeReg = RegInit(0.U(key.nGPIO.W))
    val inReg = RegInit(0.U(key.nGPIO.W))

    when(fire) {
      outReg := hPort.hBits.pins_out
      oeReg := hPort.hBits.pins_oe
    }
    when(targetReset) {
      outReg := 0.U
      oeReg := 0.U
      inReg := 0.U
    }

    hPort.hBits.pins_in := inReg

    genROReg(outReg, "out_values")
    genROReg(oeReg, "out_enables")
    genWOReg(inReg, "in_values")
    genROReg(key.nGPIO.U(32.W), "width")

    genCRFile()

    override def genHeader(
        base: BigInt,
        memoryRegions: Map[String, BigInt],
        sb: StringBuilder
    ): Unit = {
      genConstructor(base, sb, "gpio_t", "gpio")
    }
  }
}
