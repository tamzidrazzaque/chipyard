package chipyard.stage.phases

import circt.stage.{ChiselStage, CIRCTTargetAnnotation, CIRCTTarget}
import firrtl.options.PhaseManager.PhaseDependency
import firrtl.options.{Shell}
import firrtl.options.Viewer.view
import firrtl.{AnnotationSeq}
import firrtl.stage.{FirrtlCircuitAnnotation}
import firrtl.options.{Phase, PhaseManager, Shell, Stage, StageError, StageMain, Dependency, StageOptions}
import chipyard.stage._

final class LegacyFirrtl2Emission extends Phase with PreservesAll with HasChipyardStageUtils {
  override val prerequisites = Seq(Dependency[chipyard.stage.ChipyardChiselStage])

  override def transform(annotations: AnnotationSeq): AnnotationSeq = {
    val targetDir = view[StageOptions](annotations).targetDir
    val fileName = s"${view[ChipyardOptions](annotations).longName.get}.sfc.fir"

    val annos = annotations.filterNot(_.isInstanceOf[firrtl.options.TargetDirAnnotation])

    val converted = firrtl2.bridge.ChiselBridge.annosToState(annos)
    val file = new java.io.File(targetDir, fileName)
    // Stream the serialized circuit (same text ChirrtlEmitter produces, Circuit.serialize == lazily.mkString)
    // so that circuits over the JVM's 2 GiB String limit can be emitted.
    val chars = emit(converted.circuit, file)
    // Consumers parse the file with ANTLR (firrtl2 Parser.parseFile, e.g. Golden Gate), which holds it in one
    // int-indexed buffer, so a text past ~2^31 chars cannot be read back. Source locators are ~40% of the
    // text, so drop them for such circuits.
    if (chars > ParserCharLimit) {
      println(s"[LegacyFirrtl2Emission] $fileName is $chars chars, over the FIRRTL parser limit " +
        s"($ParserCharLimit); re-emitting without source locators")
      val stripped = emit(stripInfo(converted.circuit), file)
      println(s"[LegacyFirrtl2Emission] $fileName without source locators: $stripped chars")
    }

    annotations
  }

  private val ParserCharLimit: Long = Int.MaxValue - 64

  // Returns the number of chars written.
  private def emit(circuit: firrtl2.ir.Circuit, file: java.io.File): Long = {
    var chars = 0L
    val writer = new java.io.BufferedWriter(new java.io.FileWriter(file))
    try {
      firrtl2.ir.Serializer.lazily(circuit).foreach { s => chars += s.length; writer.write(s) }
    } finally {
      writer.close()
    }
    chars
  }

  private def stripInfo(circuit: firrtl2.ir.Circuit): firrtl2.ir.Circuit = {
    import firrtl2.ir._
    def stmt(s: Statement): Statement = s.mapInfo(_ => NoInfo).mapStmt(stmt)
    circuit.mapInfo(_ => NoInfo).mapModule(
      _.mapInfo(_ => NoInfo).mapPort(_.copy(info = NoInfo)).mapStmt(stmt))
  }
}
