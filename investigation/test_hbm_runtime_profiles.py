#!/usr/bin/env python3

import sys
import unittest
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRESIM = HERE.parent / "sims" / "firesim"
sys.path.insert(0, str(HERE))
import expand_fased_runtime_config as expander


class HBMRuntimeProfilesTest(unittest.TestCase):
    expected_common = {
        "relaxFunctionalModel": "0",
        "openPagePolicy": "1",
        "perBankRefresh": "0",
        "backendLatency": "2",
        "schedulerWindowSize": "8",
        "transactionQueueDepth": "8",
        "rowAddr_offset": "15",
        "rowAddr_mask": "524287",
        "pcAddr_offset": "14",
        "pcAddr_mask": "1",
        "bankAddr_offset": "10",
        "bankAddr_mask": "15",
    }

    expected_timings = {
        "2400": [17, 6, 2, 1, 2, 4, 5, 5, 19, 8, 10, 17, 14, 17, 40, 57, 6, 19, 4682, 421, 193, 10],
        "2000": [14, 5, 2, 1, 2, 4, 4, 4, 15, 6, 8, 14, 12, 14, 34, 48, 5, 16, 3900, 350, 160, 8],
    }
    timing_names = [
        "tCAS", "tCWD", "tBL", "tCMD", "tCCDS", "tCCDL", "tRRDS",
        "tRRDL", "tFAW", "tWTRS", "tWTRL", "tRCDRD", "tRCDWR", "tRP",
        "tRAS", "tRC", "tRTP", "tWR", "tREFI", "tRFC", "tRFCSB", "tRREFD",
    ]

    def read_profile(self, grade: str) -> dict[str, str]:
        path = HERE / "runtime-configs" / f"hbm2-FRFCFS-{grade}-OP-REFab.source.conf"
        return dict(expander.parse_settings(path.read_text(encoding="utf-8").splitlines()))

    def read_scala_table(self, grade: str) -> dict[str, str]:
        source = (
            FIRESIM / "sim/midas/src/main/scala/midas/models/dram/HBMModel.scala"
        ).read_text(encoding="utf-8")
        match = re.search(
            rf"val hbm2_{grade}: Map\[String, BigInt\] = Map\((.*?)\n  \)\.map",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, f"missing hbm2_{grade} table")
        return dict(re.findall(r'"(t[A-Z]+)"\s*->\s*([0-9]+)', match.group(1)))

    def test_profiles_have_exact_common_settings_and_timing_tables(self) -> None:
        for grade, values in self.expected_timings.items():
            with self.subTest(grade=grade):
                expected = dict(self.expected_common)
                expected.update(
                    {f"hbmTimings_{name}": str(value) for name, value in zip(self.timing_names, values)}
                )
                self.assertEqual(self.read_profile(grade), expected)

    def test_profile_timings_match_checked_in_scala_tables(self) -> None:
        for grade in self.expected_timings:
            profile = self.read_profile(grade)
            timings = {
                name.removeprefix("hbmTimings_"): value
                for name, value in profile.items()
                if name.startswith("hbmTimings_")
            }
            self.assertEqual(timings, self.read_scala_table(grade))

    def test_each_profile_expands_to_five_complete_models(self) -> None:
        for grade in self.expected_timings:
            settings = list(self.read_profile(grade).items())
            expected = [
                f"+mm_{name}_{model_id}={value}"
                for model_id in range(5)
                for name, value in settings
            ]
            self.assertEqual(expander.expand(settings, range(5)).splitlines(), expected)


if __name__ == "__main__":
    unittest.main()
