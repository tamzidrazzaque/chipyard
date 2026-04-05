// See LICENSE for license details

package firechip.goldengateimplementations

import chisel3._
import chisel3.util._

import org.chipsalliance.cde.config.Parameters

import midas.widgets._
import firesim.lib.bridgeutils._

import firechip.bridgeinterfaces._

class JTAGBridgeModule(bridgeParams: JTAGBridgeParams)(implicit p: Parameters)
    extends BridgeModule[HostPortIO[JTAGBridgeTargetIO]]()(p) {
  lazy val module = new BridgeModuleImp(this) {
    val io = IO(new WidgetIO)
    val hPort = IO(HostPort(new JTAGBridgeTargetIO))

    val target = hPort.hBits.jtag

    val tckReg = RegInit(false.B)
    val tmsReg = RegInit(true.B)
    val tdiReg = RegInit(true.B)
    val tdoReg = Reg(Bool())

    val fire = hPort.toHost.hValid && hPort.fromHost.hReady
    val targetReset = fire & hPort.hBits.reset

    hPort.toHost.hReady := fire
    hPort.fromHost.hValid := fire

    when(fire) {
      tdoReg := target.TDO
    }

    target.TCK := tckReg
    target.TMS := tmsReg
    target.TDI := tdiReg

    genWOReg(tckReg, "tck")
    genWOReg(tmsReg, "tms")
    genWOReg(tdiReg, "tdi")
    genROReg(tdoReg, "tdo")

    genCRFile()

    override def genHeader(base: BigInt, memoryRegions: Map[String, BigInt], sb: StringBuilder): Unit = {
      genConstructor(base, sb, "jtagbridge_t", "jtagbridge")
    }
  }
}
