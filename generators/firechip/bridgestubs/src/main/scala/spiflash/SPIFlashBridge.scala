package firechip.bridgestubs

import chisel3._
import chisel3.util._

import org.chipsalliance.cde.config.Parameters

import firesim.lib.bridgeutils._
import firechip.bridgeinterfaces._

import sifive.blocks.devices.spi.{SPIPortIO, SPIFlashParams}

class SPIFlashBridge(csWidth: Int, capacityBytes: Int)(implicit p: Parameters)
    extends BlackBox
    with Bridge[HostPortIO[SPIFlashBridgeTargetIO]] {

  val moduleName = "firechip.goldengateimplementations.SPIFlashBridgeModule"
  val io = IO(new SPIFlashBridgeTargetIO(csWidth))
  val bridgeIO = HostPort(io)
  val constructorArg = Some(SPIFlashKey(csWidth, capacityBytes))
  generateAnnotations()
}

object SPIFlashBridge {
  def apply(
      clock: Clock,
      spiPort: SPIPortIO,
      reset: Bool,
      params: SPIFlashParams,
      spiId: Int
  )(implicit p: Parameters): SPIFlashBridge = {
    val csWidth = spiPort.cs.length
    val capacityBytes = params.fSize.toInt
    val ep = Module(new SPIFlashBridge(csWidth, capacityBytes))
    ep.io.clock := clock
    ep.io.reset := reset
    ep.io.sck := spiPort.sck
    ep.io.cs.zip(spiPort.cs).foreach { case (b, s) => b := s }
    (0 until 4).foreach { j =>
      ep.io.dq_o(j) := spiPort.dq(j).o
      ep.io.dq_oe(j) := spiPort.dq(j).oe
      spiPort.dq(j).i := ep.io.dq_i(j)
    }
    ep
  }
}
