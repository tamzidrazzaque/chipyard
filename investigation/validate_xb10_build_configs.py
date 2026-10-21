#!/usr/bin/env python3
"""Parse and cross-check the controlled XB10 build pair without building."""

from argparse import Namespace
import os
from pathlib import Path
import sys

import yaml


INVESTIGATION_DIR = Path(__file__).resolve().parent
CHIPYARD_DIR = INVESTIGATION_DIR.parent
FIRESIM_DIR = CHIPYARD_DIR / "sims" / "firesim"
DEPLOY_DIR = FIRESIM_DIR / "deploy"
RECIPES_PATH = INVESTIGATION_DIR / "xb10-build-recipes.yaml"
HWDB_PATH = INVESTIGATION_DIR / "xb10-empty-hwdb.yaml"
SELECTORS = ("xb10-build-hbm.yaml", "xb10-build-ddr.yaml")

sys.path.insert(0, str(DEPLOY_DIR))
os.chdir(DEPLOY_DIR)

from buildtools.buildconfigfile import BuildConfigFile  # noqa: E402


def parse_selector(selector: str):
    args = Namespace(
        launchtime="parse-audit",
        forceterminate=True,
        buildconfigfile=str(INVESTIGATION_DIR / selector),
        buildrecipesconfigfile=str(RECIPES_PATH),
        hwdbconfigfile=str(HWDB_PATH),
    )
    config = BuildConfigFile(args)
    assert config.num_builds == 1, f"{selector}: expected exactly one build"
    build = config.builds_list[0]
    config.request_build_hosts()
    host = config.build_farm.get_build_host(build)

    assert type(build.bitbuilder).__name__ == "CorigineXB10BitBuilder"
    assert build.bitbuilder.BOARD_NAME == "xb10"
    assert build.bitbuilder.vivado_settings == (
        "/ecad/tools/xilinx/2025.1/Vivado/settings64.sh"
    )
    assert build.bitbuilder.get_build_script_extra_args() == (
        " --vivado-settings /ecad/tools/xilinx/2025.1/Vivado/settings64.sh"
    )
    assert build.get_frequency() == 20
    assert build.get_strategy().name == "TIMING"
    assert host.ip_address == "localhost"
    assert host.dest_build_dir == "/scratch/trazzaque/firesim-buildfarm"
    return build


def main() -> None:
    builds = [parse_selector(selector) for selector in SELECTORS]

    with RECIPES_PATH.open(encoding="utf-8") as stream:
        recipes = yaml.safe_load(stream)
    hbm = recipes["xb10_two_sm_hbm2_frfcfs_20mhz_timing"]
    ddr = recipes["xb10_two_sm_ddr3_frfcfs_20mhz_timing"]
    differences = {
        key: (hbm.get(key), ddr.get(key))
        for key in hbm.keys() | ddr.keys()
        if hbm.get(key) != ddr.get(key)
    }
    expected_difference = {
        "PLATFORM_CONFIG": (
            "HBM2FRFCFS16GBDualPC_BaseCorigineXB10Config",
            "FRFCFS8GBQuadRank_BaseCorigineXB10Config",
        )
    }
    assert differences == expected_difference, differences

    for build in builds:
        print(build.name)
        print(f"  {build.get_chisel_quintuplet()}")
    print(f"only recipe difference: {differences}")


if __name__ == "__main__":
    main()
