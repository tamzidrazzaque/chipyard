#!/usr/bin/env python3

import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures/exact-target-architecture.json"


class ExactTargetArchitectureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.annotations = cls.evidence["bridges"]

    def test_exact_five_bridge_widths_and_address_map(self) -> None:
        bridges = [
            annotation
            for annotation in self.annotations
            if annotation.get("widgetClass") == "midas.models.FASEDMemoryTimingModel"
        ]
        expected = [
            (0, 0x80000000, 0x7FFFFFFF, 32),
            (1, 0x100000000, 0x1FFFFFFF, 33),
            (2, 0x120000000, 0x1FFFFFFF, 33),
            (3, 0x140000000, 0x1FFFFFFF, 33),
            (4, 0x160000000, 0x1FFFFFFF, 33),
        ]
        self.assertEqual(len(bridges), len(expected))
        for bridge, (model_id, base, mask, addr_bits) in zip(bridges, expected):
            with self.subTest(model_id=model_id):
                self.assertEqual(bridge["target"], f"~FireSim|FASEDBridge_{model_id}")
                key = bridge["widgetConstructorKey"]
                self.assertEqual(
                    key["axi4Widths"],
                    {"dataBits": 64, "addrBits": addr_bits, "idBits": 4},
                )
                edge = key["axi4Edge"]
                self.assertEqual(edge["maxReadTransfer"], 4)
                self.assertEqual(edge["maxWriteTransfer"], 4)
                self.assertEqual(edge["address"], [{"base": base, "mask": mask}])

    def test_generated_clock_summary_is_one_ghz(self) -> None:
        self.assertEqual(self.evidence["input_reference_mhz"], 1000.0)
        self.assertEqual(
            self.evidence["output_clocks"],
            ["uart_clock", "clock_1000.0MHz", "harnessbinder_clock"],
        )

    def test_fixture_records_full_source_hashes(self) -> None:
        self.assertEqual(
            self.evidence["source_hashes"],
            {
                "target_annotations": (
                    "5d74fe915096616e84162a2616d5d688acbb9f454ffe1ea6a5eb5fd0cae99411"
                ),
                "frequency_summary": (
                    "1f67b3afd98ae8dbb2ce19b8970b1d01f180a29337e276a8a6b706235a7b977c"
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
