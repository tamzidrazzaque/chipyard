#!/usr/bin/env python3

import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import expand_fased_runtime_config as expander


class ExpandedRuntimeProfilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        evidence = json.loads(
            (HERE / "fixtures/exact-target-architecture.json").read_text(
                encoding="utf-8"
            )
        )
        cls.model_ids = sorted(
            int(re.fullmatch(r"~FireSim\|FASEDBridge_([0-9]+)", bridge["target"])[1])
            for bridge in evidence["bridges"]
        )

    def test_outputs_are_exact_expansions_for_annotation_model_ids(self) -> None:
        profiles = [
            "hbm2-FRFCFS-2400-OP-REFab",
            "hbm2-FRFCFS-2000-OP-REFab",
            "ddr3-FRFCFS-8G-4R-2133-OP",
        ]
        self.assertEqual(self.model_ids, [0, 1, 2, 3, 4])
        for name in profiles:
            with self.subTest(profile=name):
                source = HERE / "runtime-configs" / f"{name}.source.conf"
                output = HERE / "runtime-configs" / f"{name}-5bridge.conf"
                settings = expander.parse_settings(
                    source.read_text(encoding="utf-8").splitlines()
                )
                self.assertEqual(
                    output.read_text(encoding="utf-8"),
                    expander.expand(settings, self.model_ids),
                )


if __name__ == "__main__":
    unittest.main()
