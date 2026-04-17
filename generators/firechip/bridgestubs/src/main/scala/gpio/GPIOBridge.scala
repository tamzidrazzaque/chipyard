// See LICENSE for license details.

package firechip.bridgestubs

import chisel3._

import org.chipsalliance.cde.config.Parameters

import firesim.lib.bridgeutils._

import firechip.bridgeinterfaces._

class GPIOBridge(nGPIO: Int, gpioId: Int)(implicit p: Parameters)
    extends BlackBox
    with Bridge[HostPortIO[GPIOBridgeTargetIO]] {
  val moduleName = "firechip.goldengateimplementations.GPIOBridgeModule"
  val io = IO(new GPIOBridgeTargetIO(nGPIO))
  val bridgeIO = HostPort(io)
  val constructorArg = Some(GPIOKey(nGPIO, gpioId))
  generateAnnotations()
}

object GPIOBridge {
  def apply(
      clock: Clock,
      gpio: sifive.blocks.devices.gpio.GPIOPortIO,
      reset: Bool,
      gpioId: Int
  )(implicit p: Parameters): GPIOBridge = {
    val nGPIO = gpio.pins.length
    val ep = Module(new GPIOBridge(nGPIO, gpioId))
    ep.io.clock := clock
    ep.io.reset := reset
    ep.io.pins_out := VecInit(gpio.pins.map(_.o.oval)).asUInt
    ep.io.pins_oe := VecInit(gpio.pins.map(_.o.oe)).asUInt
    gpio.pins.zipWithIndex.foreach { case (pin, i) =>
      pin.i.ival := ep.io.pins_in(i)
      pin.i.po.foreach(_ := false.B)
    }
    ep
  }
}
