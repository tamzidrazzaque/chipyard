package firechip.goldengateimplementations

import chisel3._
import chisel3.util._

import org.chipsalliance.cde.config.Parameters
import midas.widgets._
import firesim.lib.bridgeutils._
import firechip.bridgeinterfaces._

class SPIFlashBridgeModule(key: SPIFlashKey)(implicit p: Parameters)
    extends BridgeModule[HostPortIO[SPIFlashBridgeTargetIO]]()(p) {

  lazy val module = new BridgeModuleImp(this) {
    val io = IO(new WidgetIO())
    val hPort = IO(HostPort(new SPIFlashBridgeTargetIO(key.csWidth)))

    // SPI protocol FSM states
    val sIdle :: sCmd :: sAddr :: sDummy :: sDataReq :: sData :: Nil = Enum(6)
    val state = RegInit(sIdle)

    val prevSck = RegInit(false.B)
    val prevCs  = RegInit(true.B)

    val cmdReg      = RegInit(0.U(8.W))
    val addrReg     = RegInit(0.U(32.W))
    val bitCount    = RegInit(0.U(6.W))

    val dataShiftReg = RegInit(0.U(8.W))
    val dataBitCount = RegInit(0.U(4.W))

    // Host-side data request/response handshake
    val dataReqPending = RegInit(false.B)
    val dataRespByte   = RegInit(0.U(8.W))
    val dataRespValidWire = Wire(Bool())
    dataRespValidWire := false.B

    val misoReg = RegInit(false.B)

    // Stall target when waiting for host to provide a data byte
    val fire = hPort.toHost.hValid && hPort.fromHost.hReady && !dataReqPending
    val targetReset = fire & hPort.hBits.reset
    hPort.toHost.hReady  := fire
    hPort.fromHost.hValid := fire

    val curSck  = hPort.hBits.sck
    val curCs   = hPort.hBits.cs(0)
    val curMosi = hPort.hBits.dq_o(0)

    val risingEdge  = fire && !prevSck && curSck
    val fallingEdge = fire && prevSck && !curSck
    val csAsserted   = fire && prevCs && !curCs
    val csDeasserted = fire && !prevCs && curCs
    val csActive     = fire && !curCs

    hPort.hBits.dq_i(0) := false.B
    hPort.hBits.dq_i(1) := misoReg
    hPort.hBits.dq_i(2) := false.B
    hPort.hBits.dq_i(3) := false.B

    when(fire) {
      prevSck := curSck
      prevCs  := curCs
    }

    val cmdIs4Byte = cmdReg === 0x13.U || cmdReg === 0x0C.U ||
                     cmdReg === 0x6C.U || cmdReg === 0xEC.U
    val cmdHasDummy = cmdReg === 0x0B.U || cmdReg === 0x0C.U ||
                      cmdReg === 0x6B.U || cmdReg === 0x6C.U ||
                      cmdReg === 0xEB.U || cmdReg === 0xEC.U
    val addrBits = Mux(cmdIs4Byte, 32.U(6.W), 24.U(6.W))

    // Rising edge: sample MOSI during cmd/addr, count bits during data
    when(risingEdge && csActive) {
      switch(state) {
        is(sCmd) {
          cmdReg   := Cat(cmdReg(6, 0), curMosi)
          bitCount := bitCount + 1.U
          when(bitCount === 7.U) {
            state    := sAddr
            bitCount := 0.U
            addrReg  := 0.U
          }
        }
        is(sAddr) {
          addrReg  := Cat(addrReg(30, 0), curMosi)
          bitCount := bitCount + 1.U
          when(bitCount === (addrBits - 1.U)) {
            bitCount := 0.U
            when(cmdHasDummy) {
              state := sDummy
            }.otherwise {
              state          := sDataReq
              dataReqPending := true.B
              dataBitCount   := 0.U
            }
          }
        }
        is(sDummy) {
          bitCount := bitCount + 1.U
          when(bitCount === 7.U) {
            state          := sDataReq
            dataReqPending := true.B
            dataBitCount   := 0.U
            bitCount       := 0.U
          }
        }
        is(sData) {
          dataBitCount := dataBitCount + 1.U
          when(dataBitCount === 7.U) {
            addrReg        := addrReg + 1.U
            state          := sDataReq
            dataReqPending := true.B
            dataBitCount   := 0.U
          }
        }
      }
    }

    // Falling edge during data phase: shift out next MISO bit
    when(fallingEdge && state === sData && csActive) {
      misoReg      := dataShiftReg(7)
      dataShiftReg := Cat(dataShiftReg(6, 0), 0.U(1.W))
    }

    // Host response: load data byte and resume target
    when(dataRespValidWire) {
      dataReqPending := false.B
      dataShiftReg   := dataRespByte
      state          := sData
      dataBitCount   := 0.U
      misoReg        := dataRespByte(7)
    }

    // CS deassert resets protocol (higher priority than rising edge logic)
    when(csDeasserted) {
      state        := sIdle
      bitCount     := 0.U
      cmdReg       := 0.U
      addrReg      := 0.U
      dataBitCount := 0.U
      misoReg      := false.B
    }

    when(csAsserted) {
      state    := sCmd
      bitCount := 0.U
      cmdReg   := 0.U
    }

    when(targetReset) {
      state          := sIdle
      prevSck        := false.B
      prevCs         := true.B
      cmdReg         := 0.U
      addrReg        := 0.U
      bitCount       := 0.U
      dataBitCount   := 0.U
      dataReqPending := false.B
      misoReg        := false.B
      dataShiftReg   := 0.U
    }

    val fireCountReg = RegInit(0.U(32.W))
    when(fire) { fireCountReg := fireCountReg + 1.U }
    val sckEdgeCount = RegInit(0.U(32.W))
    when(risingEdge) { sckEdgeCount := sckEdgeCount + 1.U }

    // MMIO registers — order determines struct field order in generated header
    genWOReg(dataRespByte, "data_resp")
    Pulsify(genWORegInit(dataRespValidWire, "data_resp_valid", false.B), pulseLength = 1)
    genROReg(cmdReg, "cmd")
    genROReg(addrReg, "addr")
    genROReg(dataReqPending, "data_req")
    genROReg(key.csWidth.U(32.W), "cs_width")
    genROReg(key.capacityBytes.U(32.W), "capacity")
    genROReg(fireCountReg, "fire_count")
    genROReg(sckEdgeCount, "sck_edge_count")

    genCRFile()

    override def genHeader(
        base: BigInt,
        memoryRegions: Map[String, BigInt],
        sb: StringBuilder
    ): Unit = {
      genConstructor(base, sb, "spiflash_t", "spiflash")
    }
  }
}
