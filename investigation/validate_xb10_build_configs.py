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
SELECTORS = {
    "xb10-build-hbm.yaml": "xb10_two_sm_hbm2_frfcfs_20mhz_timing",
    "xb10-build-ddr.yaml": "xb10_two_sm_ddr3_frfcfs_20mhz_timing",
}

sys.path.insert(0, str(DEPLOY_DIR))
os.chdir(DEPLOY_DIR)

from buildtools.buildconfigfile import BuildConfigFile  # noqa: E402


class ValidationError(RuntimeError):
    """A fail-closed configuration validation error."""


def require(condition: bool, message: str) -> None:
    """Reject an invalid configuration even when Python assertions are disabled."""
    if not condition:
        raise ValidationError(message)


def parse_selector(selector: str, expected_build_name: str):
    selector_path = INVESTIGATION_DIR / selector
    with selector_path.open(encoding="utf-8") as stream:
        selector_value = yaml.safe_load(stream)
    expected_selector = {
        "build_farm": {
            "base_recipe": "build-farm-recipes/externally_provisioned.yaml",
            "recipe_arg_overrides": {
                "default_build_dir": "/scratch/trazzaque/firesim-buildfarm",
                "build_farm_hosts": ["localhost"],
            },
        },
        "builds_to_run": [expected_build_name],
        "agfis_to_share": [],
        "share_with_accounts": {},
    }
    require(
        selector_value == expected_selector,
        f"{selector}: selector changed from the exact localhost build contract",
    )
    args = Namespace(
        launchtime="parse-audit",
        forceterminate=True,
        buildconfigfile=str(selector_path),
        buildrecipesconfigfile=str(RECIPES_PATH),
        hwdbconfigfile=str(HWDB_PATH),
    )
    config = BuildConfigFile(args)
    require(config.num_builds == 1, f"{selector}: expected exactly one build")
    build = config.builds_list[0]
    require(
        build.name == expected_build_name,
        f"{selector}: selected {build.name}, expected {expected_build_name}",
    )
    config.request_build_hosts()
    host = config.build_farm.get_build_host(build)

    require(
        type(build.bitbuilder).__name__ == "CorigineXB10BitBuilder",
        f"{selector}: wrong bit builder {type(build.bitbuilder).__name__}",
    )
    require(
        build.bitbuilder.BOARD_NAME == "xb10",
        f"{selector}: wrong board {build.bitbuilder.BOARD_NAME}",
    )
    expected_vivado = "/ecad/tools/xilinx/2025.1/Vivado/settings64.sh"
    require(
        build.bitbuilder.vivado_settings == expected_vivado,
        f"{selector}: wrong Vivado settings {build.bitbuilder.vivado_settings}",
    )
    require(
        build.bitbuilder.get_build_script_extra_args()
        == f" --vivado-settings {expected_vivado}",
        f"{selector}: Vivado settings were not forwarded to the build script",
    )
    require(build.get_frequency() == 20, f"{selector}: frequency must be 20 MHz")
    require(
        build.get_strategy().name == "TIMING",
        f"{selector}: build strategy must be TIMING",
    )
    require(host.ip_address == "localhost", f"{selector}: build host must be localhost")
    require(
        host.dest_build_dir == "/scratch/trazzaque/firesim-buildfarm",
        f"{selector}: unexpected build directory {host.dest_build_dir}",
    )
    return build


def main() -> None:
    builds = [
        parse_selector(selector, expected_build_name)
        for selector, expected_build_name in SELECTORS.items()
    ]

    with RECIPES_PATH.open(encoding="utf-8") as stream:
        recipes = yaml.safe_load(stream)
    require(
        set(recipes) == set(SELECTORS.values()),
        "build recipe file must contain exactly the controlled HBM/DDR pair",
    )
    hbm = recipes["xb10_two_sm_hbm2_frfcfs_20mhz_timing"]
    ddr = recipes["xb10_two_sm_ddr3_frfcfs_20mhz_timing"]
    common_recipe = {
        "PLATFORM": "corigine_xb10",
        "TARGET_PROJECT": "firesim",
        "TARGET_PROJECT_MAKEFRAG": (
            "/scratch/trazzaque/chipyard/generators/firechip/chip/src/main/"
            "makefrag/firesim"
        ),
        "DESIGN": "FireSim",
        "TARGET_CONFIG": "FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig",
        "deploy_quintuplet": None,
        "platform_config_args": {
            "fpga_frequency": 20,
            "build_strategy": "TIMING",
        },
        "post_build_hook": None,
        "metasim_customruntimeconfig": None,
        "bit_builder_recipe": "bit-builder-recipes/corigine_xb10.yaml",
        "bit_builder_arg_overrides": {
            "vivado_settings": "/ecad/tools/xilinx/2025.1/Vivado/settings64.sh"
        },
    }
    expected_hbm = dict(common_recipe)
    expected_hbm["PLATFORM_CONFIG"] = "HBM2FRFCFS16GBDualPC_BaseCorigineXB10Config"
    expected_ddr = dict(common_recipe)
    expected_ddr["PLATFORM_CONFIG"] = "FRFCFS8GBQuadRank_BaseCorigineXB10Config"
    require(hbm == expected_hbm, "HBM recipe changed from the exact build contract")
    require(ddr == expected_ddr, "DDR recipe changed from the exact build contract")
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
    require(
        differences == expected_difference,
        f"controlled recipes have unexpected differences: {differences}",
    )

    for build in builds:
        print(build.name)
        print(f"  {build.get_chisel_quintuplet()}")
    print(f"only recipe difference: {differences}")


if __name__ == "__main__":
    try:
        main()
    except (ValidationError, KeyError, OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
