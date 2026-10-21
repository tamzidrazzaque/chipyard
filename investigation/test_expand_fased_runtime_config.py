#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import expand_fased_runtime_config as subject


class ExpandFASEDRuntimeConfigTest(unittest.TestCase):
    def test_expands_every_setting_for_every_model(self) -> None:
        settings = subject.parse_settings(
            ["+mm_backendLatency=2", "+mm_hbmTimings_tCAS=17"]
        )
        self.assertEqual(
            subject.expand(settings, [0, 1, 2]),
            "+mm_backendLatency_0=2\n"
            "+mm_hbmTimings_tCAS_0=17\n"
            "+mm_backendLatency_1=2\n"
            "+mm_hbmTimings_tCAS_1=17\n"
            "+mm_backendLatency_2=2\n"
            "+mm_hbmTimings_tCAS_2=17\n",
        )

    def test_ignores_blank_lines_and_full_line_comments(self) -> None:
        self.assertEqual(
            subject.parse_settings(["", " # provenance", "+mm_openPagePolicy=1"]),
            [("openPagePolicy", "1")],
        )

    def test_rejects_malformed_duplicate_and_preindexed_settings(self) -> None:
        invalid_inputs = [
            ["+mm_openPagePolicy=1 # inline comment"],
            ["+mm_openPagePolicy=1", "+mm_openPagePolicy=0"],
            ["+mm_openPagePolicy_0=1"],
            ["+mm_openPagePolicy=-1"],
            [f"+mm_openPagePolicy={subject.CPP_UINT32_MAX + 1}"],
            ["+other=1"],
        ]
        for lines in invalid_inputs:
            with self.subTest(lines=lines), self.assertRaises(subject.ConfigError):
                subject.parse_settings(lines)

    def test_accepts_full_uint32_range(self) -> None:
        value = str(subject.CPP_UINT32_MAX)
        self.assertEqual(
            subject.parse_settings([f"+mm_backendLatency={value}"]),
            [("backendLatency", value)],
        )

    def test_derives_exact_contiguous_ids_from_bridge_annotations(self) -> None:
        annotations = [
            {
                "widgetClass": subject.FASED_WIDGET_CLASS,
                "target": f"~FireSim|FASEDBridge_{model_id}",
            }
            for model_id in [4, 1, 3, 0, 2]
        ]
        annotations.append(
            {"widgetClass": "midas.widgets.ClockBridgeModule", "target": "ignored"}
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "target.anno.json"
            path.write_text(json.dumps(annotations), encoding="utf-8")
            self.assertEqual(subject.model_ids_from_annotations(path), [0, 1, 2, 3, 4])

    def test_rejects_noncontiguous_annotation_ids(self) -> None:
        annotations = [
            {
                "widgetClass": subject.FASED_WIDGET_CLASS,
                "target": "~FireSim|FASEDBridge_1",
            }
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "target.anno.json"
            path.write_text(json.dumps(annotations), encoding="utf-8")
            with self.assertRaises(subject.ConfigError):
                subject.model_ids_from_annotations(path)


if __name__ == "__main__":
    unittest.main()
