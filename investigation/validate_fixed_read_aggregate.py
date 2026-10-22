#!/usr/bin/env python3
"""Validate fixed-read FASED A/B results and print exact cycle comparisons."""

from __future__ import annotations

import csv
from pathlib import Path
import re


ROOT = Path("/scratch/trazzaque/firesim-host-builds/fixed-read-probe")
MODES = {
    "ddr_1port": (1, 32768),
    "hbm2_1port": (1, 32768),
    "ddr_4port": (4, 8192),
    "hbm2_4port": (4, 8192),
    "hbm2_1port_2400clk": (1, 32768),
    "hbm2_4port_2400clk": (4, 8192),
    "ddr_1port_refresh30k": (1, 32768),
    "hbm2_1port_refresh30k": (1, 32768),
    "hbm2_1port_refsb": (1, 32768),
    "hbm2_4port_refsb": (4, 8192),
    "hbm2_1port_postfix_refab": (1, 32768),
    "hbm2_1port_postfix_refsb": (1, 32768),
    "hbm2_4port_postfix_refab": (4, 8192),
    "hbm2_4port_postfix_refsb": (4, 8192),
    "hbm2_1port_interleaved_refab": (1, 32768),
    "hbm2_1port_interleaved_refsb": (1, 32768),
    "ddr_1port_interleaved": (1, 32768),
    "hbm2_4port_interleaved_refab": (4, 8192),
    "hbm2_4port_interleaved_refsb": (4, 8192),
    "ddr_4port_interleaved": (4, 8192),
}
PASS = re.compile(r"\*\*\* PASSED \*\*\* after ([0-9]+) cycles")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(mode: str, bridges: int, reads_per_bridge: int, repeat: str = "") -> int:
    run_dir = ROOT / f"aggregate-{mode}{'-' + repeat if repeat else ''}"
    log = (run_dir / "console.log").read_text(encoding="utf-8")
    passes = PASS.findall(log)
    require(len(passes) == 1, f"{mode}: expected exactly one PASS marker")
    require("*** FAILED ***" not in log, f"{mode}: FAILED marker present")
    require(
        log.count('COMMAND_EXIT_CODE="0"') == 1,
        f"{mode}: simulator exit was not exactly one success",
    )
    files = sorted(run_dir.glob("memory_stats*.csv"))
    require(
        {p.name for p in files} == {f"memory_stats{i}.csv" for i in range(bridges)},
        f"{mode}: expected exactly {bridges} bridge statistics files",
    )
    for path in files:
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        require(bool(rows), f"{mode}: missing statistics in {path.name}")
        row = rows[-1]
        for key, expected in {
            "totalReads": reads_per_bridge,
            "totalReadBeats": 4 * reads_per_bridge,
            "totalWrites": 0,
            "totalWriteBeats": 0,
            "brespError": 0,
            "rrespError": 0,
        }.items():
            require(int(row[key]) == expected, f"{mode}/{path.name}: {key}={row[key]}, expected {expected}")
    return int(passes[0])


def main() -> None:
    repeats = ("", "repeat1", "repeat2")
    measurements = {
        mode: [validate(mode, *args, repeat=repeat) for repeat in repeats]
        for mode, args in MODES.items()
    }
    for mode, values in measurements.items():
        require(len(set(values)) == 1, f"{mode}: three repeats disagree: {values}")
    cycles = {mode: values[0] for mode, values in measurements.items()}
    print("Fixed workload: 32,768 reads x 32 bytes = 1,048,576 bytes; all bridge counters and responses pass")
    print("Three independent runs per condition produced identical target cycles")
    for mode, value in cycles.items():
        print(f"{mode}: {value:,} target cycles")
    ddr1, hbm1 = cycles["ddr_1port"], cycles["hbm2_1port"]
    ddr4, hbm4 = cycles["ddr_4port"], cycles["hbm2_4port"]
    print(f"HBM2 vs DDR, one port: {(hbm1 / ddr1 - 1) * 100:+.3f}% cycles")
    print(f"HBM2 vs DDR, four ports: {(hbm4 / ddr4 - 1) * 100:+.3f}% cycles")
    print(f"Four-port HBM2 vs one-port DDR: {ddr1 / hbm4:.3f}x speedup, {(1 - hbm4 / ddr1) * 100:.3f}% fewer cycles")
    print(f"DDR four-port scaling: {ddr1 / ddr4:.3f}x")
    print(f"HBM2 four-port scaling: {hbm1 / hbm4:.3f}x")
    hbm2400_1, hbm2400_4 = (
        cycles["hbm2_1port_2400clk"],
        cycles["hbm2_4port_2400clk"],
    )
    print(f"HBM2-2400 @1GHz vs DDR, one port: {(hbm2400_1 / ddr1 - 1) * 100:+.3f}% cycles")
    print(f"HBM2-2400 @1GHz vs DDR, four ports: {(hbm2400_4 / ddr4 - 1) * 100:+.3f}% cycles")
    print(f"Four-port HBM2-2400 @1GHz vs one-port DDR: {ddr1 / hbm2400_4:.3f}x speedup, {(1 - hbm2400_4 / ddr1) * 100:.3f}% fewer cycles")
    ddr30k, hbm30k = cycles["ddr_1port_refresh30k"], cycles["hbm2_1port_refresh30k"]
    print(f"Nonphysical tREFI=30k DDR vs DDR baseline: {(ddr30k / ddr1 - 1) * 100:+.3f}% cycles")
    print(f"Nonphysical tREFI=30k HBM2 vs HBM2 baseline: {(hbm30k / hbm1 - 1) * 100:+.3f}% cycles")
    print(f"Nonphysical tREFI=30k HBM2 vs DDR, one port: {(hbm30k / ddr30k - 1) * 100:+.3f}% cycles")
    hbmrefsb1, hbmrefsb4 = cycles["hbm2_1port_refsb"], cycles["hbm2_4port_refsb"]
    print(f"HBM2-2000 REFSB vs REFab, one port: {(hbmrefsb1 / hbm1 - 1) * 100:+.3f}% cycles")
    print(f"HBM2-2000 REFSB vs DDR, one port: {(hbmrefsb1 / ddr1 - 1) * 100:+.3f}% cycles")
    print(f"HBM2-2000 REFSB vs DDR, four ports: {(hbmrefsb4 / ddr4 - 1) * 100:+.3f}% cycles")
    postrefab1, postrefsb1 = cycles["hbm2_1port_postfix_refab"], cycles["hbm2_1port_postfix_refsb"]
    postrefab4, postrefsb4 = cycles["hbm2_4port_postfix_refab"], cycles["hbm2_4port_postfix_refsb"]
    require(postrefab1 == hbm1 and postrefab4 == hbm4, "REFab control changed under REFSB-only source edit")
    print(f"Bank-local REFSB edit, one port: {hbmrefsb1 - postrefsb1:,} fewer cycles ({(1 - postrefsb1 / hbmrefsb1) * 100:.4f}%)")
    print(f"Bank-local REFSB edit, four ports: {hbmrefsb4 - postrefsb4:,} fewer cycles ({(1 - postrefsb4 / hbmrefsb4) * 100:.4f}%)")
    interab, intersb = cycles["hbm2_1port_interleaved_refab"], cycles["hbm2_1port_interleaved_refsb"]
    ddr_inter = cycles["ddr_1port_interleaved"]
    print(f"Bank-interleaved HBM2 REFSB vs REFab, one port: {(intersb / interab - 1) * 100:+.3f}% cycles")
    print(f"Bank-interleaved HBM2 REFSB vs DDR, one port: {(intersb / ddr_inter - 1) * 100:+.3f}% cycles")
    print(f"Bank-interleaved HBM2 REFab vs DDR, one port: {(interab / ddr_inter - 1) * 100:+.3f}% cycles")
    print(f"DDR bank-interleaved vs sequential: {(ddr_inter / ddr1 - 1) * 100:+.3f}% cycles")
    ddr4_inter = cycles["ddr_4port_interleaved"]
    hbm4_interab = cycles["hbm2_4port_interleaved_refab"]
    hbm4_intersb = cycles["hbm2_4port_interleaved_refsb"]
    print(f"Four-port bank-interleaved HBM2 REFSB vs DDR: {(hbm4_intersb / ddr4_inter - 1) * 100:+.3f}% cycles")
    print(f"Four-port bank-interleaved HBM2 REFab vs DDR: {(hbm4_interab / ddr4_inter - 1) * 100:+.3f}% cycles")
    print(f"Four-port bank-interleaved HBM2 REFSB vs REFab: {(hbm4_intersb / hbm4_interab - 1) * 100:+.3f}% cycles")
    print(f"DDR four-port bank-interleaved vs sequential: {(ddr4_inter / ddr4 - 1) * 100:+.3f}% cycles")


if __name__ == "__main__":
    main()
