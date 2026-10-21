#!/usr/bin/env python3

import sys
import unittest
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRESIM = HERE.parent / "sims" / "firesim"
sys.path.insert(0, str(HERE))
import expand_fased_runtime_config as expander


class DDRRuntimeProfileTest(unittest.TestCase):
    expected = {
        "relaxFunctionalModel": "0",
        "openPagePolicy": "1",
        "backendLatency": "2",
        "schedulerWindowSize": "8",
        "transactionQueueDepth": "8",
        "dramTimings_tAL": "0",
        "dramTimings_tCAS": "14",
        "dramTimings_tCMD": "1",
        "dramTimings_tCWD": "10",
        "dramTimings_tCCD": "4",
        "dramTimings_tFAW": "25",
        "dramTimings_tRAS": "33",
        "dramTimings_tREFI": "7800",
        "dramTimings_tRC": "47",
        "dramTimings_tRCD": "14",
        "dramTimings_tRFC": "160",
        "dramTimings_tRRD": "5",
        "dramTimings_tRP": "14",
        "dramTimings_tRTP": "8",
        "dramTimings_tRTRS": "2",
        "dramTimings_tWR": "15",
        "dramTimings_tWTR": "8",
        "rankAddr_offset": "16",
        "rankAddr_mask": "3",
        "rowAddr_offset": "18",
        "rowAddr_mask": "32767",
        "bankAddr_offset": "13",
        "bankAddr_mask": "7",
    }

    def read_profile(self) -> list[tuple[str, str]]:
        path = HERE / "runtime-configs" / "ddr3-FRFCFS-8G-4R-2133-OP.source.conf"
        return expander.parse_settings(path.read_text(encoding="utf-8").splitlines())

    def test_profile_matches_2048_mbit_sg093_at_one_ghz(self) -> None:
        self.assertEqual(dict(self.read_profile()), self.expected)

    def test_timings_derive_from_checked_in_micron_table(self) -> None:
        source = (
            FIRESIM
            / "sim/midas/src/main/resources/midas/models/dram/2048Mb_ddr3.json"
        )
        micron = json.loads(source.read_text(encoding="utf-8"))["sg093"]["x8"]

        def ticks(name: str) -> int:
            field = micron[name]
            value = int(field["value"])
            return value if field["units"] == "tCK" else (value + 999) // 1000

        expected_timings = {
            "dramTimings_tAL": 0,
            "dramTimings_tCAS": ticks("CL_TIME"),
            "dramTimings_tCMD": 1,
            "dramTimings_tCWD": ticks("CL_TIME") - 4,
            "dramTimings_tCCD": ticks("TCCD"),
            "dramTimings_tFAW": ticks("TFAW"),
            "dramTimings_tRAS": ticks("TRAS_MIN"),
            "dramTimings_tREFI": ticks("TRFC_MAX") // 9,
            "dramTimings_tRC": ticks("TRC"),
            "dramTimings_tRCD": ticks("TRCD"),
            "dramTimings_tRFC": ticks("TRFC_MIN"),
            "dramTimings_tRRD": ticks("TRRD"),
            "dramTimings_tRP": ticks("TRP"),
            "dramTimings_tRTP": max(ticks("TRTP"), ticks("TRTP_TCK")),
            "dramTimings_tRTRS": 2,
            "dramTimings_tWR": ticks("TWR"),
            "dramTimings_tWTR": ticks("TWTR"),
        }
        profile = dict(self.read_profile())
        self.assertEqual(
            {name: int(profile[name]) for name in expected_timings},
            expected_timings,
        )
        self.assertEqual(
            int(profile["rowAddr_mask"]),
            (1 << int(micron["ROW_BITS"]["value"])) - 1,
        )

    def test_profile_expands_to_five_complete_models(self) -> None:
        settings = self.read_profile()
        expected = [
            f"+mm_{name}_{model_id}={value}"
            for model_id in range(5)
            for name, value in settings
        ]
        self.assertEqual(expander.expand(settings, range(5)).splitlines(), expected)


if __name__ == "__main__":
    unittest.main()
