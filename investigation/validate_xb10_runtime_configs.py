#!/usr/bin/env python3
"""Validate the host-only XB10 controlled-pair deployment templates.

The default mode is deliberately non-deployable: it checks the checked-in
templates, nine workload ELFs, and canonical five-index FASED profiles while
requiring artifact/provenance/slot placeholders to remain present. ``--ready``
instead requires filled configs, reviewed source/generated/archive hashes,
local tarballs, deployed profiles, and an explicit one-entry FPGA database.
Neither mode opens SSH nor accesses an FPGA.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlparse

try:
    import yaml
except ModuleNotFoundError as error:
    raise SystemExit(
        "FAIL: use the pinned Chipyard environment: "
        "source /scratch/trazzaque/tools/miniforge/etc/profile.d/conda.sh && "
        "conda activate /scratch/trazzaque/chipyard/.conda-env"
    ) from error


HERE = Path(__file__).resolve().parent
CHIPYARD = HERE.parent
FIRESIM = CHIPYARD / "sims" / "firesim"
DEPLOY = FIRESIM / "deploy"
SIM = FIRESIM / "sim"
RADIANCE = CHIPYARD.parent / "radiance-kernels"

DEFAULT_HWDB = HERE / "xb10-runtime-hwdb.template.yaml"
DEFAULT_HBM_RUNTIME = HERE / "xb10-runtime-hbm.template.yaml"
DEFAULT_HBM2000_RUNTIME = HERE / "xb10-runtime-hbm2000.template.yaml"
DEFAULT_DDR_RUNTIME = HERE / "xb10-runtime-ddr.template.yaml"
DEFAULT_CAMPAIGN = HERE / "xb10-runtime-campaign.yaml"

HBM_ENTRY = "xb10_two_sm_hbm2_frfcfs_20mhz_timing"
HBM2000_ENTRY = "xb10_two_sm_hbm2_frfcfs_20mhz_timing_hbm2000_sensitivity"
DDR_ENTRY = "xb10_two_sm_ddr3_frfcfs_20mhz_timing"
TARGET_CONFIG = "FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig"
RUNTIME_TEMPLATES = {
    HBM_ENTRY: DEFAULT_HBM_RUNTIME,
    HBM2000_ENTRY: DEFAULT_HBM2000_RUNTIME,
    DDR_ENTRY: DEFAULT_DDR_RUNTIME,
}
PLATFORM_CONFIGS = {
    "hbm": "HBM2FRFCFS16GBDualPC_BaseCorigineXB10Config",
    "ddr": "FRFCFS8GBQuadRank_BaseCorigineXB10Config",
}
BUILD_SELECTORS = {
    "xb10-build-hbm.yaml": HBM_ENTRY,
    "xb10-build-ddr.yaml": DDR_ENTRY,
}
RUNTIME_CONDITIONS = (
    ("hbm2400", HBM_ENTRY, "hbm"),
    ("hbm2000", HBM2000_ENTRY, "hbm"),
    ("ddr2133", DDR_ENTRY, "ddr"),
)
EXPECTED_CASE_IDS = [
    "stream-copy",
    "stream-scale",
    "stream-add",
    "stream-triad",
    "spatter-0-gather",
    "spatter-1-scatter",
    "spatter-2-gs",
    "spatter-3-multiscatter",
    "spatter-4-multigather",
]
EXPECTED_CASE_PATHS = {
    "stream-copy": (
        "workloads/xb10-two-sm-hashed-timed-stream-copy.json",
        "../../radiance-kernels/kernels/stream/runs/two-sm-native/hashed/timed/copy/kernel.soc.elf",
    ),
    "stream-scale": (
        "workloads/xb10-two-sm-hashed-timed-stream-scale.json",
        "../../radiance-kernels/kernels/stream/runs/two-sm-native/hashed/timed/scale/kernel.soc.elf",
    ),
    "stream-add": (
        "workloads/xb10-two-sm-hashed-timed-stream-add.json",
        "../../radiance-kernels/kernels/stream/runs/two-sm-native/hashed/timed/add/kernel.soc.elf",
    ),
    "stream-triad": (
        "workloads/xb10-two-sm-hashed-timed-stream-triad.json",
        "../../radiance-kernels/kernels/stream/runs/two-sm-native/hashed/timed/triad/kernel.soc.elf",
    ),
    "spatter-0-gather": (
        "workloads/xb10-two-sm-hashed-timed-spatter-0-gather.json",
        "../../radiance-kernels/kernels/spatter/runs/two-sm-native/hashed/timed/case-0-gather/kernel.soc.elf",
    ),
    "spatter-1-scatter": (
        "workloads/xb10-two-sm-hashed-timed-spatter-1-scatter.json",
        "../../radiance-kernels/kernels/spatter/runs/two-sm-native/hashed/timed/case-1-scatter/kernel.soc.elf",
    ),
    "spatter-2-gs": (
        "workloads/xb10-two-sm-hashed-timed-spatter-2-gs.json",
        "../../radiance-kernels/kernels/spatter/runs/two-sm-native/hashed/timed/case-2-gs/kernel.soc.elf",
    ),
    "spatter-3-multiscatter": (
        "workloads/xb10-two-sm-hashed-timed-spatter-3-multiscatter.json",
        "../../radiance-kernels/kernels/spatter/runs/two-sm-native/hashed/timed/case-3-multiscatter/kernel.soc.elf",
    ),
    "spatter-4-multigather": (
        "workloads/xb10-two-sm-hashed-timed-spatter-4-multigather.json",
        "../../radiance-kernels/kernels/spatter/runs/two-sm-native/hashed/timed/case-4-multigather/kernel.soc.elf",
    ),
}
EXPECTED_SIM_OUTPUTS = [
    "uartlog",
    "memory_stats0.csv",
    "memory_stats1.csv",
    "memory_stats2.csv",
    "memory_stats3.csv",
    "memory_stats4.csv",
    "fased-runtime-profile.applied.json",
]
EXPECTED_PROFILE_INTERVAL = 10_000_000
PLACEHOLDER_PREFIX = "__REPLACE_"
GIT_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SAFE_SUFFIX_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
FASED_SETTING_RE = re.compile(
    r"^\+mm_([A-Za-z][A-Za-z0-9_]*)_([0-9]+)=([0-9]+)$"
)
FASED_UART_DIAGNOSTIC_RE = re.compile(
    r"^\[FASED\] Model ([0-9]+) accepted ([0-9]+) explicit runtime settings; "
    r"hardware defaults (enabled|disabled)\r?$",
    re.MULTILINE,
)
SIMULATOR_PASS_RE = re.compile(
    r"^\*\*\* PASSED \*\*\* after ([0-9]+) cycles\r?$", re.MULTILINE
)
MEMORY_STATS_HEADER_CELL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
SOURCE_GITLINKS = {
    "firesim": "sims/firesim",
    "radiance": "generators/radiance",
    "fesvr_spike": "toolchains/riscv-tools/riscv-isa-sim",
}
GENERATED_OUTPUT_FILES = {
    "target_fir": f"firechip.chip.FireSim.{TARGET_CONFIG}.fir",
    "target_annotations": f"firechip.chip.FireSim.{TARGET_CONFIG}.anno.json",
    "generated_sv": "FireSim-generated.sv",
    "generated_defines_vh": "FireSim-generated.defines.vh",
    "generated_const_h": "FireSim-generated.const.h",
    "synthesis_xdc": "FireSim-generated.synthesis.xdc",
    "implementation_xdc": "FireSim-generated.implementation.xdc",
    "post_bridge_extraction": "post-bridge-extraction.json",
}
# These two source-sensitive outputs must change after the reviewed Gemmini
# width fix. Ancillary outputs (for example XDC and bridge annotations) can
# legitimately remain byte-identical, so they are not rejected by hash alone.
REJECTED_PRE_FIX_GENERATED_HASHES = {
    "hbm": {
        "target_fir": "aa29c4232aea52333252b8aca2b1d085fd333fcfe671d6405f0b1be4ffd7b284",
        "generated_sv": "56ac7565484c7f4a8c8f9591acbd78245c867e34a44c37d87540188a2b98e5d5",
    },
    "ddr": {
        "target_fir": "aa29c4232aea52333252b8aca2b1d085fd333fcfe671d6405f0b1be4ffd7b284",
        "generated_sv": "e594835720c60d91274bd4d5f2632f4e8c67b6e95e96030077f97a9c723d09c2",
    },
}
EXPECTED_PROVENANCE_PLACEHOLDER_PATHS = frozenset(
    {"source_commits.chipyard"}
    | {
        f"generated_output_sha256.{model}.{name}"
        for model in ("hbm", "ddr")
        for name in GENERATED_OUTPUT_FILES
    }
    | {
        f"artifact_sha256.{model}.{name}"
        for model in ("hbm", "ddr")
        for name in ("bitstream_tar", "driver_tar")
    }
)
EXPECTED_CONFIG_TEMPLATE_PLACEHOLDERS = Counter(
    {
        "__REPLACE_WITH_HBM_FIRESIM_TAR_GZ_URI__": 2,
        "__REPLACE_WITH_HBM_DRIVER_BUNDLE_TAR_GZ_URI__": 2,
        "__REPLACE_WITH_DDR_FIRESIM_TAR_GZ_URI__": 1,
        "__REPLACE_WITH_DDR_DRIVER_BUNDLE_TAR_GZ_URI__": 1,
        "__REPLACE_WITH_HBM_FIRESIM_TAR_GZ_SHA256__": 2,
        "__REPLACE_WITH_HBM_DRIVER_BUNDLE_TAR_GZ_SHA256__": 2,
        "__REPLACE_WITH_DDR_FIRESIM_TAR_GZ_SHA256__": 1,
        "__REPLACE_WITH_DDR_DRIVER_BUNDLE_TAR_GZ_SHA256__": 1,
        "__REPLACE_WITH_COORDINATED_ONE_ENTRY_FPGA_DB_JSON__": 3,
    }
)


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def is_canonical_bounded_decimal(value: str, maximum: int) -> bool:
    maximum_text = str(maximum)
    if value == "0":
        return True
    if re.fullmatch(r"[1-9][0-9]*", value) is None:
        return False
    return len(value) < len(maximum_text) or (
        len(value) == len(maximum_text) and value <= maximum_text
    )


def validate_result_suffix(value: Any, label: str) -> None:
    require(
        isinstance(value, str) and SAFE_SUFFIX_RE.fullmatch(value) is not None,
        f"{label}: result suffix must be a nonempty path-safe label",
    )


def parse_captured_result_spec(value: str) -> tuple[str, Path]:
    condition, separator, path_text = value.partition("=")
    require(
        separator == "=" and condition != "" and path_text != "",
        "captured result must use CONDITION=/absolute/path syntax",
    )
    path = Path(path_text)
    require(
        path.is_absolute(),
        f"captured result path must be absolute, got {path_text!r}",
    )
    return condition, path


def expected_fased_receipt(
    condition_config: dict[str, Any],
) -> dict[str, Any]:
    digest = condition_config["fased_sha256"]
    model_ids = condition_config["required_fased_model_ids"]
    settings_per_model = condition_config["settings_per_model"]
    return {
        "hwdb_entry": condition_config["hwdb_entry"],
        "model_ids": model_ids,
        "profile_snapshot": f".fased-runtime-profile-{digest}.conf",
        "profile_source": Path(
            condition_config["fased_deployment_path"]
        ).name,
        "settings_per_model": settings_per_model,
        "sha256": digest,
        "total_settings": len(model_ids) * settings_per_model,
    }


def expected_fased_hwdb_contract(
    condition_config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "sha256": condition_config["fased_sha256"],
        "model_ids": condition_config["required_fased_model_ids"],
        "settings_per_model": condition_config["settings_per_model"],
    }


def validate_captured_result_dir(
    path: Path,
    condition: str,
    campaign: dict[str, Any],
) -> None:
    conditions = campaign.get("runtime_conditions")
    require(isinstance(conditions, dict), "campaign runtime_conditions is missing")
    require(
        condition in conditions,
        f"unknown captured-result condition {condition!r}; expected one of "
        f"{list(conditions)}",
    )

    result_dir = path.resolve()
    require(result_dir.is_dir(), f"captured result directory is missing: {result_dir}")
    for name in EXPECTED_SIM_OUTPUTS:
        output = result_dir / name
        require(
            output.is_file() and not output.is_symlink(),
            f"{result_dir}: missing regular captured output {name}",
        )
        require(
            output.stat().st_size > 0,
            f"{result_dir}: captured output {name} is empty",
        )

    for model_id in range(5):
        stats_path = result_dir / f"memory_stats{model_id}.csv"
        try:
            stats_text = stats_path.read_bytes().decode("ascii")
        except UnicodeDecodeError as error:
            raise ValidationError(f"{stats_path}: memory statistics are not ASCII") from error
        require(
            "\r" not in stats_text and stats_text.endswith("\n"),
            f"{stats_path}: memory statistics must use LF-terminated records",
        )
        records = stats_text[:-1].split("\n")
        require(
            len(records) >= 2,
            f"{stats_path}: memory statistics contain only a header; "
            "the terminal profile row is missing",
        )
        header = records[0].split(",")
        require(
            len(header) >= 2 and header[-1] == "",
            f"{stats_path}: malformed memory-statistics header",
        )
        header_names = header[:-1]
        require(
            all(
                MEMORY_STATS_HEADER_CELL_RE.fullmatch(name)
                for name in header_names
            )
            and len(set(header_names)) == len(header_names),
            f"{stats_path}: invalid or duplicate memory-statistics header field",
        )
        for row_number, record in enumerate(records[1:], 2):
            cells = record.split(",")
            require(
                len(cells) == len(header) and cells[-1] == "",
                f"{stats_path}:{row_number}: data-row arity does not match header",
            )
            for value in cells[:-1]:
                require(
                    is_canonical_bounded_decimal(value, (1 << 32) - 1),
                    f"{stats_path}:{row_number}: noncanonical uint32 value {value!r}",
                )

    condition_config = conditions[condition]
    receipt_path = result_dir / "fased-runtime-profile.applied.json"

    def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            require(key not in value, f"{receipt_path}: duplicate JSON key {key!r}")
            value[key] = child
        return value

    try:
        receipt = json.loads(
            receipt_path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError(
            f"{receipt_path}: invalid UTF-8 JSON receipt: {error}"
        ) from error
    expected_receipt = expected_fased_receipt(condition_config)
    require(type(receipt) is dict, f"{receipt_path}: receipt must be a JSON object")
    exact_keys(receipt, set(expected_receipt), f"{receipt_path}: receipt")
    for key, expected_value in expected_receipt.items():
        require(
            type(receipt[key]) is type(expected_value),
            f"{receipt_path}: receipt field {key} has the wrong JSON type",
        )
    require(
        all(type(model_id) is int for model_id in receipt["model_ids"]),
        f"{receipt_path}: receipt model_ids must contain only integers",
    )
    require(
        receipt == expected_receipt,
        f"{receipt_path}: receipt does not exactly match {condition} campaign contract",
    )

    uart_path = result_dir / "uartlog"
    try:
        uart = uart_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(f"{uart_path}: UART log is not UTF-8") from error
    diagnostics = FASED_UART_DIAGNOSTIC_RE.findall(uart)
    acceptance_candidates = [
        line
        for line in uart.splitlines()
        if "[FASED] Model " in line
    ]
    require(
        len(acceptance_candidates) == len(diagnostics),
        f"{uart_path}: malformed FASED acceptance diagnostic",
    )
    model_ids = condition_config["required_fased_model_ids"]
    settings_per_model = condition_config["settings_per_model"]
    require(
        len(diagnostics) == len(model_ids),
        f"{uart_path}: expected exactly {len(model_ids)} FASED acceptance "
        f"diagnostics, got {len(diagnostics)}",
    )
    by_model: dict[int, tuple[int, str]] = {}
    for model_text, count_text, defaults_state in diagnostics:
        model_id = int(model_text)
        accepted_count = int(count_text)
        require(
            model_text == str(model_id) and count_text == str(accepted_count),
            f"{uart_path}: FASED acceptance diagnostic uses noncanonical decimal spelling",
        )
        require(
            model_id not in by_model,
            f"{uart_path}: duplicate FASED acceptance diagnostic for model {model_id}",
        )
        by_model[model_id] = (accepted_count, defaults_state)
    require(
        sorted(by_model) == model_ids,
        f"{uart_path}: FASED diagnostic model IDs must be {model_ids}, got "
        f"{sorted(by_model)}",
    )
    for model_id, (accepted_count, defaults_state) in by_model.items():
        require(
            accepted_count == settings_per_model,
            f"{uart_path}: model {model_id} accepted {accepted_count} settings; "
            f"expected {settings_per_model}",
        )
        require(
            defaults_state == "disabled",
            f"{uart_path}: model {model_id} enabled hardware-default runtime settings",
        )

    pass_matches = SIMULATOR_PASS_RE.findall(uart)
    status_candidates = [
        line
        for line in uart.splitlines()
        if "*** PASSED ***" in line or "*** FAILED ***" in line
    ]
    require(
        len(pass_matches) == 1 and len(status_candidates) == 1,
        f"{uart_path}: expected exactly one canonical successful simulator exit",
    )
    cycle_text = pass_matches[0]
    require(
        cycle_text != "0"
        and is_canonical_bounded_decimal(cycle_text, (1 << 64) - 1),
        f"{uart_path}: simulator pass cycle count is not a positive canonical decimal",
    )


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    require(isinstance(value, dict), f"{path}: top level must be a mapping")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest_sha256(root: Path) -> str:
    """Hash a stable sha256sum-style manifest of every regular file in root."""
    require(root.is_dir(), f"header tree does not exist: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    require(files, f"header tree is empty: {root}")
    manifest = "".join(
        f"{sha256(path)}  ./{path.relative_to(root).as_posix()}\n" for path in files
    ).encode()
    return hashlib.sha256(manifest).hexdigest()


def git_output(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
    )
    require(
        result.returncode == 0,
        f"git {' '.join(args)} failed in {repository}: {result.stderr.strip()}",
    )
    return result.stdout.strip()


def validate_checked_out_commit(
    repository: Path,
    expected_commit: str,
    label: str,
    *,
    allowed_untracked_prefixes: tuple[str, ...] = (),
) -> None:
    require(repository.is_dir(), f"{label}: repository is missing: {repository}")
    actual_commit = git_output(repository, "rev-parse", "HEAD")
    require(
        actual_commit == expected_commit,
        f"{label}: checkout {actual_commit} does not match intended {expected_commit}",
    )
    status = git_output(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    unexpected = []
    for line in status.splitlines():
        if line.startswith("?? ") and any(
            line[3:].startswith(prefix) for prefix in allowed_untracked_prefixes
        ):
            continue
        unexpected.append(line)
    require(
        not unexpected,
        f"{label}: intended source checkout is dirty:\n" + "\n".join(unexpected),
    )


def parent_gitlink(parent_commit: str, path: str) -> str:
    line = git_output(CHIPYARD, "ls-tree", parent_commit, "--", path)
    require(line, f"Chipyard {parent_commit}: missing gitlink {path}")
    metadata, separator, listed_path = line.partition("\t")
    require(separator == "\t" and listed_path == path,
            f"Chipyard {parent_commit}: malformed tree entry for {path}: {line}")
    fields = metadata.split()
    require(
        len(fields) == 3 and fields[0] == "160000" and fields[1] == "commit",
        f"Chipyard {parent_commit}: {path} is not a gitlink: {line}",
    )
    commit = fields[2]
    require(GIT_COMMIT_RE.fullmatch(commit) is not None,
            f"Chipyard {parent_commit}: malformed gitlink commit for {path}")
    return commit


def exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    require(
        set(value) == expected,
        f"{label}: expected keys {sorted(expected)}, got {sorted(value)}",
    )


def validate_filled_template(
    template: Any,
    candidate: Any,
    label: str,
    *,
    allowed_leaf_paths: frozenset[str] = frozenset(),
    _path: str = "",
) -> None:
    """Allow a ready copy to replace placeholder leaves, and nothing else."""
    if _path in allowed_leaf_paths:
        return
    if isinstance(template, str) and template.startswith(PLACEHOLDER_PREFIX):
        require(
            not (
                isinstance(candidate, str)
                and candidate.startswith(PLACEHOLDER_PREFIX)
            ),
            f"{label}: placeholder is still unresolved",
        )
        return
    if isinstance(template, dict):
        require(isinstance(candidate, dict), f"{label}: expected a mapping")
        exact_keys(candidate, set(template), label)
        for key, value in template.items():
            child_path = f"{_path}.{key}" if _path else key
            validate_filled_template(
                value,
                candidate[key],
                f"{label}.{key}",
                allowed_leaf_paths=allowed_leaf_paths,
                _path=child_path,
            )
        return
    if isinstance(template, list):
        require(isinstance(candidate, list), f"{label}: expected a list")
        require(len(candidate) == len(template), f"{label}: list length changed")
        for index, value in enumerate(template):
            child_path = f"{_path}[{index}]"
            validate_filled_template(
                value,
                candidate[index],
                f"{label}[{index}]",
                allowed_leaf_paths=allowed_leaf_paths,
                _path=child_path,
            )
        return
    require(
        type(candidate) is type(template) and candidate == template,
        f"{label}: ready campaign changed pinned value {template!r} to {candidate!r}",
    )


def placeholders(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str) and value.startswith(PLACEHOLDER_PREFIX):
        found.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            found.extend(placeholders(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(placeholders(child))
    return found


def placeholder_leaf_paths(value: Any, path: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, str) and value.startswith(PLACEHOLDER_PREFIX):
        found.add(path)
    elif isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            found.update(placeholder_leaf_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.update(placeholder_leaf_paths(child, f"{path}[{index}]"))
    return found


def validate_checked_in_campaign_placeholders(campaign: dict[str, Any]) -> None:
    actual = placeholder_leaf_paths(campaign["artifact_provenance"])
    require(
        actual == EXPECTED_PROVENANCE_PLACEHOLDER_PATHS,
        "checked-in campaign must retain exactly the 21 reviewed provenance "
        f"placeholders; expected {sorted(EXPECTED_PROVENANCE_PLACEHOLDER_PATHS)}, "
        f"got {sorted(actual)}",
    )


@contextmanager
def cwd(path: Path) -> Iterator[None]:
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def validate_build_pair() -> None:
    selector_common = {
        "build_farm": {
            "base_recipe": "build-farm-recipes/externally_provisioned.yaml",
            "recipe_arg_overrides": {
                "default_build_dir": "/scratch/trazzaque/firesim-buildfarm",
                "build_farm_hosts": ["localhost"],
            },
        },
        "agfis_to_share": [],
        "share_with_accounts": {},
    }
    for selector_name, expected_build in BUILD_SELECTORS.items():
        selector = read_yaml(HERE / selector_name)
        expected_selector = copy.deepcopy(selector_common)
        expected_selector["builds_to_run"] = [expected_build]
        require(
            selector == expected_selector,
            f"{selector_name}: selector changed from the exact localhost build contract",
        )

    recipes = read_yaml(HERE / "xb10-build-recipes.yaml")
    require(set(recipes) == {HBM_ENTRY, DDR_ENTRY},
            "build recipe file must contain exactly the controlled HBM/DDR pair")
    hbm = recipes[HBM_ENTRY]
    ddr = recipes[DDR_ENTRY]
    for model, recipe in (("hbm", hbm), ("ddr", ddr)):
        expected_recipe = {
            "PLATFORM": "corigine_xb10",
            "TARGET_PROJECT": "firesim",
            "TARGET_PROJECT_MAKEFRAG": (
                "/scratch/trazzaque/chipyard/generators/firechip/chip/src/main/"
                "makefrag/firesim"
            ),
            "DESIGN": "FireSim",
            "TARGET_CONFIG": TARGET_CONFIG,
            "PLATFORM_CONFIG": PLATFORM_CONFIGS[model],
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
        require(
            recipe == expected_recipe,
            f"{model}: build recipe changed from the exact 20 MHz TIMING contract",
        )

    hbm_normalized = copy.deepcopy(hbm)
    ddr_normalized = copy.deepcopy(ddr)
    hbm_normalized.pop("PLATFORM_CONFIG")
    ddr_normalized.pop("PLATFORM_CONFIG")
    require(
        hbm_normalized == ddr_normalized,
        "controlled build recipes differ in fields other than PLATFORM_CONFIG",
    )


def validate_fased_profile(path: Path, ids: list[int], settings_count: int) -> None:
    require(
        path.is_file() and not path.is_symlink(),
        f"missing regular non-symlink FASED profile: {path}",
    )
    profile_bytes = path.read_bytes()
    require(profile_bytes, f"FASED profile is empty: {path}")
    require(
        b"\r" not in profile_bytes,
        f"{path}: FASED profile must use canonical LF line endings",
    )
    try:
        profile_text = profile_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValidationError(f"{path}: FASED profile must be ASCII") from error

    # Split only on the LF byte flattened by the launch path. Python's
    # splitlines() also accepts control separators that remain embedded in one
    # driver argument.
    lines = profile_text.split("\n")
    if lines[-1] == "":
        lines.pop()

    indexed: dict[int, dict[str, int]] = {model_id: {} for model_id in ids}
    for lineno, line in enumerate(lines, 1):
        match = FASED_SETTING_RE.fullmatch(line)
        require(
            match is not None,
            f"{path}:{lineno}: expected strict "
            "+mm_<setting>_<model>=<nonnegative integer> syntax",
        )
        if match is None:  # Keep type narrowing independent of Python assertions.
            raise ValidationError(f"{path}:{lineno}: malformed FASED setting")
        name, index_text, value_text = match.groups()
        index = int(index_text)
        require(
            index_text == str(index),
            f"{path}:{lineno}: model ID must use canonical decimal spelling",
        )
        require(index in indexed, f"{path}:{lineno}: unexpected model ID {index}")
        model = indexed[index]
        require(name not in model, f"{path}:{lineno}: duplicate {name}_{index}")
        value = int(value_text)
        require(
            value <= 0xFFFFFFFF,
            f"{path}:{lineno}: value exceeds UINT32_MAX",
        )
        model[name] = value

    for index in ids:
        require(
            len(indexed[index]) == settings_count,
            f"{path}: model {index} has {len(indexed[index])} settings; "
            f"expected {settings_count}",
        )
    reference = indexed[ids[0]]
    for index in ids[1:]:
        require(
            indexed[index] == reference,
            f"{path}: model {index} does not match model {ids[0]}",
        )


def checksum_manifest() -> dict[str, str]:
    result: dict[str, str] = {}
    manifest = HERE / "workload-elfs-two-sm.sha256"
    for raw in manifest.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        digest, rel = line.split(None, 1)
        result[rel.strip()] = digest
    return result


def manager_workload_reference(path: Path) -> str:
    return os.path.relpath(path.resolve(), (DEPLOY / "workloads").resolve())


def import_manager_classes() -> tuple[type[Any], type[Any], type[Any]]:
    sys.path.insert(0, str(DEPLOY))
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", message="Blowfish has been deprecated")
    try:
        from runtools.runtime_config import InnerRuntimeConfiguration, RuntimeHWDB
        from runtools.workload import WorkloadConfig
    except ModuleNotFoundError as error:
        raise ValidationError(
            "FireSim manager dependency "
            f"{error.name!r} is unavailable. Activate the pinned environment: "
            "source /scratch/trazzaque/tools/miniforge/etc/profile.d/conda.sh && "
            "conda activate /scratch/trazzaque/chipyard/.conda-env"
        ) from error
    return InnerRuntimeConfiguration, RuntimeHWDB, WorkloadConfig


def validate_workload_json_contract(
    workload: dict[str, Any], case_id: str, expected_bootbinary: str
) -> None:
    label = f"{case_id}: workload JSON"
    exact_keys(
        workload,
        {
            "benchmark_name",
            "common_bootbinary",
            "common_rootfs",
            "common_outputs",
            "common_simulation_outputs",
            "common_simulation_inputs",
        },
        label,
    )
    require(
        workload["benchmark_name"] == f"xb10-two-sm-hashed-timed-{case_id}",
        f"{label}: benchmark_name does not match the reviewed safe name",
    )
    require(
        workload["common_bootbinary"] == expected_bootbinary,
        f"{label}: common_bootbinary does not match the reviewed ELF path",
    )
    require(workload["common_rootfs"] is None, f"{label}: common_rootfs must be null")
    require(workload["common_outputs"] == [], f"{label}: common_outputs must be empty")
    require(
        workload["common_simulation_outputs"] == EXPECTED_SIM_OUTPUTS,
        f"{label}: simulation outputs must be the exact seven reviewed files",
    )
    require(
        workload["common_simulation_inputs"] == [],
        f"{label}: simulation inputs must be empty",
    )


def validate_case_contracts(cases: Any) -> None:
    require(isinstance(cases, list), "campaign cases must be a list")
    require(len(cases) == len(EXPECTED_CASE_IDS),
            "campaign must contain exactly nine cases")
    for index, (case_id, expected_paths) in enumerate(EXPECTED_CASE_PATHS.items()):
        case = cases[index]
        require(isinstance(case, dict), "campaign case must be a mapping")
        exact_keys(case, {"id", "workload_file", "elf", "sha256"},
                   f"campaign case {index}")
        require(case["id"] == case_id,
                f"campaign case {index}: expected identity {case_id}")
        expected_workload, expected_elf = expected_paths
        require(case["workload_file"] == expected_workload,
                f"{case_id}: workload_file does not match its reviewed identity")
        require(case["elf"] == expected_elf,
                f"{case_id}: ELF path does not match its reviewed identity")
        require(isinstance(case["sha256"], str)
                and SHA256_RE.fullmatch(case["sha256"]) is not None,
                f"{case_id}: ELF hash must be a full lowercase SHA-256")


def validate_workloads(campaign: dict[str, Any]) -> set[Path]:
    _, _, WorkloadConfig = import_manager_classes()
    cases = campaign["cases"]
    workload_build = campaign["artifact_provenance"]["workload_build"]
    hash_parameters = campaign["loading_contract"]["hash_parameters"]
    validate_case_contracts(cases)

    known_hashes = checksum_manifest()
    workload_paths: set[Path] = set()
    for case in cases:
        workload_path = (HERE / case["workload_file"]).resolve()
        elf = (HERE / case["elf"]).resolve()
        require(workload_path.is_file(), f"{case['id']}: missing workload JSON")
        require(elf.is_file(), f"{case['id']}: missing ELF")
        require(RADIANCE.resolve() in elf.parents, f"{case['id']}: ELF outside radiance-kernels")
        parts = elf.parts
        require("hashed" in parts and "unhashed" not in parts and "timed" in parts,
                f"{case['id']}: must use the hashed/timed ELF")

        actual_hash = sha256(elf)
        require(actual_hash == case["sha256"], f"{case['id']}: campaign ELF hash mismatch")
        rel_to_radiance = elf.relative_to(RADIANCE).as_posix()
        require(known_hashes.get(rel_to_radiance) == actual_hash,
                f"{case['id']}: checksum manifest mismatch")

        result_path = elf.parent / "result.json"
        result = json.loads(result_path.read_text())
        for result_key in (
            "kernel_revision",
            "llvm_source_revision",
            "mxgemmini_revision",
        ):
            require(
                result.get(result_key) == workload_build[result_key],
                f"{case['id']}: result.json {result_key} does not match "
                "reviewed workload-build provenance",
            )
        params = result["mu_addr_hash_parameters"]
        require(isinstance(params, dict),
                f"{case['id']}: result.json hash parameters must be a mapping")
        exact_keys(
            params,
            {
                "enabled",
                "elf_base",
                "size",
                "unit_bytes",
                "slices",
                "gpu_host_base",
                "required_load_path",
            },
            f"{case['id']}: result.json hash parameters",
        )
        require(result["mu_addr_hash"] == 1 and params["enabled"] is True,
                f"{case['id']}: ELF manifest is not hashed")
        require(params["required_load_path"] == "direct-memory-load",
                f"{case['id']}: wrong required load path")
        for parameter, expected in hash_parameters.items():
            require(
                params.get(parameter) == expected,
                f"{case['id']}: result.json hash parameter {parameter} does not "
                "match the campaign contract",
            )
        require(result["muon_clusters"] == 2, f"{case['id']}: not a two-cluster ELF")
        require(result["muon_cores_per_cluster"] == 2,
                f"{case['id']}: wrong core count per cluster")
        require(result["muon_total_cores"] == 4, f"{case['id']}: wrong total core count")
        require(result["host_timing_requested"] is True,
                f"{case['id']}: not a host-timed build")
        require(result["artifacts"]["kernel.soc.elf"]["sha256"] == actual_hash,
                f"{case['id']}: result.json ELF hash mismatch")

        readelf = subprocess.run(
            ["readelf", "-SW", str(elf)], text=True, capture_output=True, check=True
        ).stdout
        require(".radiance_addr_hash" in readelf,
                f"{case['id']}: missing .radiance_addr_hash section")
        program_headers = subprocess.run(
            ["readelf", "-lW", str(elf)], text=True, capture_output=True, check=True
        ).stdout
        require(re.search(r"LOAD\s+\S+\s+0x0*1[0-9a-fA-F]{8}", program_headers) is not None,
                f"{case['id']}: no GPU-address PT_LOAD segment")

        workload_json = json.loads(workload_path.read_text())
        require(isinstance(workload_json, dict),
                f"{case['id']}: workload JSON must be a mapping")
        expected_benchmark = f"xb10-two-sm-hashed-timed-{case['id']}"
        expected_bootbinary = os.path.relpath(
            elf, (DEPLOY / "workloads" / expected_benchmark).resolve()
        )
        validate_workload_json_contract(
            workload_json, case["id"], expected_bootbinary
        )
        reference = manager_workload_reference(workload_path)
        with cwd(DEPLOY):
            parsed = WorkloadConfig(reference, "validation-only", None)
            job = parsed.get_job(0)
            resolved_boot = (DEPLOY / job.bootbinary_path()).resolve()
        require(parsed.uniform_mode, f"{case['id']}: workload is not uniform-mode")
        require(resolved_boot == elf, f"{case['id']}: manager resolves the wrong boot ELF")
        require(job.rootfs_path() is None, f"{case['id']}: manager derived an unwanted rootfs")
        require(job.simoutputs == EXPECTED_SIM_OUTPUTS,
                f"{case['id']}: must collect UART, all five FASED stats files, "
                "and the applied-profile receipt")
        workload_paths.add(workload_path)

    return workload_paths


def normalized_runtime_pair(value: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(value)
    normalized["target_config"].pop("default_hw_config", None)
    normalized["workload"].pop("suffix_tag", None)
    return normalized


def validate_runtime_yaml(
    path: Path,
    expected_entry: str,
    known_workloads: set[Path],
    ready: bool,
) -> tuple[dict[str, Any], str]:
    InnerRuntimeConfiguration, _, _ = import_manager_classes()
    value = read_yaml(path)
    if ready:
        validate_filled_template(
            read_yaml(RUNTIME_TEMPLATES[expected_entry]),
            value,
            f"ready runtime {path}",
            allowed_leaf_paths=frozenset(
                {"workload.workload_name", "workload.suffix_tag"}
            ),
        )
    with cwd(DEPLOY):
        parsed = InnerRuntimeConfiguration(str(path), "")

    overrides = value["run_farm"]["recipe_arg_overrides"]
    require(value["run_farm"]["base_recipe"] == "run-farm-recipes/externally_provisioned.yaml",
            f"{path}: wrong run-farm recipe")
    require(overrides["default_platform"] == "CorigineXB10InstanceDeployManager",
            f"{path}: wrong deploy manager")
    require(overrides["run_farm_hosts_to_use"] == [
        {"localhost": "xb10_controlled_single_slot"}
    ], f"{path}: run farm must contain only localhost/single-slot")
    require(overrides["run_farm_host_specs"] == [{
        "xb10_controlled_single_slot": {
            "num_fpgas": 1,
            "num_metasims": 0,
            "use_for_switch_only": False,
        }
    }], f"{path}: single-slot host spec changed")

    fpga_db = overrides["default_fpga_db"]
    require(isinstance(fpga_db, str), f"{path}: FPGA DB path must be a string")
    require(fpga_db != "/opt/firesim-db.json", f"{path}: shared eight-card DB is forbidden")
    if ready:
        require(not fpga_db.startswith(PLACEHOLDER_PREFIX), f"{path}: FPGA DB is unresolved")
        fpga_db_path = Path(fpga_db)
        require(fpga_db_path.is_absolute(), f"{path}: FPGA DB path must be absolute")
        validate_one_entry_fpga_db(fpga_db_path)
    else:
        require(fpga_db == "__REPLACE_WITH_COORDINATED_ONE_ENTRY_FPGA_DB_JSON__",
                f"{path}: template must retain the coordinated-slot placeholder")

    target = value["target_config"]
    require(target["topology"] == "no_net_config" and target["no_net_num_nodes"] == 1,
            f"{path}: target must be exactly one no-network node")
    require(target["profile_interval"] == EXPECTED_PROFILE_INTERVAL,
            f"{path}: FASED profile interval must be {EXPECTED_PROFILE_INTERVAL}")
    require(parsed.profileinterval == EXPECTED_PROFILE_INTERVAL,
            f"{path}: manager parser disagrees on FASED profile interval")
    require(target["default_hw_config"] == expected_entry, f"{path}: wrong HWDB entry")
    require(
        target["plusarg_passthrough"] == "",
        f"{path}: plusarg_passthrough must be empty for the controlled campaign",
    )
    require(value["metasimulation"]["metasimulation_enabled"] is False,
            f"{path}: FPGA runtime template unexpectedly enables metasimulation")
    require(parsed.defaulthwconfig == expected_entry, f"{path}: manager parser disagrees")

    workload_ref = value["workload"]["workload_name"]
    require(isinstance(workload_ref, str), f"{path}: workload reference must be a string")
    suffix_tag = value["workload"]["suffix_tag"]
    validate_result_suffix(suffix_tag, str(path))
    resolved_workload = (DEPLOY / "workloads" / workload_ref).resolve()
    require(resolved_workload in known_workloads, f"{path}: workload is outside campaign set")
    return value, fpga_db


def validate_one_entry_fpga_db(path: Path) -> None:
    require(
        path.is_file() and not path.is_symlink(),
        f"coordinated FPGA DB must be a regular non-symlink file: {path}",
    )
    value = json.loads(path.read_text())
    require(isinstance(value, list) and len(value) == 1,
            f"{path}: expected exactly one coordinated physical FPGA entry")
    entry = value[0]
    require(isinstance(entry, dict), f"{path}: FPGA entry must be a mapping")
    require({"bdf", "uid", "device"}.issubset(entry), f"{path}: FPGA entry schema incomplete")
    require(re.fullmatch(r"[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]", str(entry["bdf"])) is not None,
            f"{path}: invalid BDF shape")
    require(
        re.fullmatch(r"[A-Za-z0-9_.:-]+/[A-Za-z0-9_.:-]+", str(entry["uid"]))
        is not None,
        f"{path}: invalid JTAG UID",
    )
    require(
        re.fullmatch(r"[A-Za-z0-9_.:-]+", str(entry["device"])) is not None,
        f"{path}: invalid device name",
    )


def validate_artifact_provenance(
    campaign: dict[str, Any], ready: bool
) -> tuple[dict[str, Any], list[str]]:
    provenance = campaign.get("artifact_provenance")
    require(isinstance(provenance, dict), "campaign artifact_provenance is missing")
    exact_keys(
        provenance,
        {
            "schema_version",
            "source_commits",
            "workload_build",
            "host_dependencies",
            "generated_output_sha256",
            "artifact_sha256",
        },
        "artifact_provenance",
    )
    require(provenance["schema_version"] == 1,
            "unexpected artifact provenance schema")

    blockers: list[str] = []
    commits = provenance["source_commits"]
    require(isinstance(commits, dict), "source_commits must be a mapping")
    exact_keys(commits, {"chipyard", "firesim", "radiance", "fesvr_spike"},
               "source_commits")

    for name in ("firesim", "radiance", "fesvr_spike"):
        commit = commits[name]
        require(isinstance(commit, str) and GIT_COMMIT_RE.fullmatch(commit) is not None,
                f"{name}: intended source commit must be a full lowercase SHA")

    validate_checked_out_commit(FIRESIM, commits["firesim"], "FireSim")
    validate_checked_out_commit(CHIPYARD / "generators" / "radiance",
                                commits["radiance"], "Radiance")
    validate_checked_out_commit(
        CHIPYARD / SOURCE_GITLINKS["fesvr_spike"],
        commits["fesvr_spike"],
        "Spike/FESVR source",
    )

    workload_build = provenance["workload_build"]
    require(isinstance(workload_build, dict), "workload_build must be a mapping")
    exact_keys(
        workload_build,
        {
            "radiance_kernels_checkout",
            "kernel_revision",
            "llvm_source_revision",
            "mxgemmini_revision",
        },
        "workload_build",
    )
    for name, commit in workload_build.items():
        require(
            isinstance(commit, str) and GIT_COMMIT_RE.fullmatch(commit) is not None,
            f"workload_build/{name}: must be a full lowercase commit SHA",
        )
    validate_checked_out_commit(
        RADIANCE,
        workload_build["radiance_kernels_checkout"],
        "radiance-kernels checkout",
    )
    git_output(
        RADIANCE,
        "cat-file",
        "-e",
        f"{workload_build['kernel_revision']}^{{commit}}",
    )
    git_output(
        RADIANCE,
        "merge-base",
        "--is-ancestor",
        workload_build["kernel_revision"],
        workload_build["radiance_kernels_checkout"],
    )
    validate_checked_out_commit(
        RADIANCE / "llvm" / "llvm-src",
        workload_build["llvm_source_revision"],
        "workload LLVM source",
    )
    validate_checked_out_commit(
        RADIANCE / "lib" / "mxgemmini",
        workload_build["mxgemmini_revision"],
        "workload mxgemmini source",
    )
    for path, key in (
        ("llvm/llvm-src", "llvm_source_revision"),
        ("lib/mxgemmini", "mxgemmini_revision"),
    ):
        line = git_output(
            RADIANCE, "ls-tree", workload_build["kernel_revision"], "--", path
        )
        fields = line.partition("\t")[0].split()
        require(
            len(fields) == 3
            and fields[0] == "160000"
            and fields[1] == "commit"
            and fields[2] == workload_build[key],
            f"workload kernel revision does not pin {path} to {workload_build[key]}",
        )

    parent_commit = commits["chipyard"]
    if isinstance(parent_commit, str) and parent_commit.startswith(PLACEHOLDER_PREFIX):
        require(not ready,
                "artifact provenance still lacks the final clean Chipyard build commit")
        blockers.append("final clean Chipyard build commit and source gitlinks")
    else:
        require(
            isinstance(parent_commit, str)
            and GIT_COMMIT_RE.fullmatch(parent_commit) is not None,
            "chipyard: build commit must be a full lowercase SHA",
        )
        git_output(CHIPYARD, "cat-file", "-e", f"{parent_commit}^{{commit}}")
        validate_checked_out_commit(
            CHIPYARD,
            parent_commit,
            "Chipyard parent build tree",
            allowed_untracked_prefixes=("investigation/",),
        )
        for source_name, gitlink_path in SOURCE_GITLINKS.items():
            require(
                parent_gitlink(parent_commit, gitlink_path) == commits[source_name],
                f"Chipyard {parent_commit}: {gitlink_path} does not pin "
                f"the intended {source_name} commit {commits[source_name]}",
            )

    dependencies = provenance["host_dependencies"]
    require(isinstance(dependencies, dict), "host_dependencies must be a mapping")
    exact_keys(
        dependencies,
        {
            "fesvr_prefix",
            "libfesvr_a_sha256",
            "libriscv_so_sha256",
            "include_tree_sha256",
        },
        "host_dependencies",
    )
    require(isinstance(dependencies["fesvr_prefix"], str),
            "FESVR prefix must be a string")
    fesvr_prefix = Path(dependencies["fesvr_prefix"])
    require(fesvr_prefix.is_absolute(), "FESVR prefix must be an absolute path")
    expected_fesvr_hash = dependencies["libfesvr_a_sha256"]
    require(
        isinstance(expected_fesvr_hash, str)
        and SHA256_RE.fullmatch(expected_fesvr_hash) is not None,
        "libfesvr.a provenance hash must be a full lowercase SHA-256",
    )
    expected_include_hash = dependencies["include_tree_sha256"]
    require(
        isinstance(expected_include_hash, str)
        and SHA256_RE.fullmatch(expected_include_hash) is not None,
        "FESVR include-tree provenance hash must be a full lowercase SHA-256",
    )
    fesvr_archive = fesvr_prefix / "lib" / "libfesvr.a"
    riscv_library = fesvr_prefix / "lib" / "libriscv.so"
    fesvr_include = fesvr_prefix / "include"
    if fesvr_archive.is_file():
        require(
            sha256(fesvr_archive) == expected_fesvr_hash,
            f"{fesvr_archive}: does not match the reviewed FESVR archive hash",
        )
    elif ready:
        raise ValidationError(f"reviewed FESVR archive is missing: {fesvr_archive}")
    else:
        blockers.append(f"reviewed FESVR archive: {fesvr_archive}")
    expected_riscv_hash = dependencies["libriscv_so_sha256"]
    require(
        isinstance(expected_riscv_hash, str)
        and SHA256_RE.fullmatch(expected_riscv_hash) is not None,
        "libriscv.so provenance hash must be a full lowercase SHA-256",
    )
    if riscv_library.is_file():
        require(
            sha256(riscv_library) == expected_riscv_hash,
            f"{riscv_library}: does not match the reviewed Spike library hash",
        )
    elif ready:
        raise ValidationError(f"reviewed Spike library is missing: {riscv_library}")
    else:
        blockers.append(f"reviewed Spike library: {riscv_library}")
    if fesvr_include.is_dir():
        require(
            tree_manifest_sha256(fesvr_include) == expected_include_hash,
            f"{fesvr_include}: does not match the reviewed FESVR header-tree hash",
        )
    elif ready:
        raise ValidationError(f"reviewed FESVR header tree is missing: {fesvr_include}")
    else:
        blockers.append(f"reviewed FESVR header tree: {fesvr_include}")

    generated = provenance["generated_output_sha256"]
    require(isinstance(generated, dict), "generated_output_sha256 must be a mapping")
    exact_keys(generated, {"hbm", "ddr"}, "generated_output_sha256")
    for model in ("hbm", "ddr"):
        hashes = generated[model]
        require(isinstance(hashes, dict), f"{model}: generated hashes must be a mapping")
        exact_keys(hashes, set(GENERATED_OUTPUT_FILES), f"{model}: generated hashes")
        unresolved = [
            name
            for name, digest in hashes.items()
            if isinstance(digest, str) and digest.startswith(PLACEHOLDER_PREFIX)
        ]
        if unresolved:
            require(
                not ready,
                f"{model}: post-fix generated hashes are unresolved: {unresolved}",
            )
            blockers.append(
                f"post-fix {model.upper()} generated-output hashes "
                f"({len(unresolved)} unresolved)"
            )

        expected_dir = (
            SIM
            / "generated-src"
            / "corigine_xb10"
            / (
                f"corigine_xb10-firesim-FireSim-{TARGET_CONFIG}-"
                f"{PLATFORM_CONFIGS[model]}"
            )
        )
        for name, filename in GENERATED_OUTPUT_FILES.items():
            digest = hashes[name]
            if isinstance(digest, str) and digest.startswith(PLACEHOLDER_PREFIX):
                continue
            require(
                isinstance(digest, str) and SHA256_RE.fullmatch(digest) is not None,
                f"{model}/{name}: generated hash must be a full lowercase SHA-256",
            )
            rejected_hash = REJECTED_PRE_FIX_GENERATED_HASHES[model].get(name)
            require(
                digest != rejected_hash,
                f"{model}/{name}: known pre-fix output is forbidden; regenerate "
                "Golden Gate after the reviewed source fix",
            )
            output = expected_dir / filename
            if output.is_file():
                require(sha256(output) == digest,
                        f"{output}: generated output hash mismatch")
            elif ready:
                raise ValidationError(f"missing reviewed generated output: {output}")
            else:
                blockers.append(f"reviewed generated output: {output}")

    artifacts = provenance["artifact_sha256"]
    require(isinstance(artifacts, dict), "artifact_sha256 must be a mapping")
    exact_keys(artifacts, {"hbm", "ddr"}, "artifact_sha256")
    for model in ("hbm", "ddr"):
        hashes = artifacts[model]
        require(isinstance(hashes, dict), f"{model}: artifact hashes must be a mapping")
        exact_keys(hashes, {"bitstream_tar", "driver_tar"},
                   f"{model}: artifact hashes")
        unresolved = []
        for artifact_name, digest in hashes.items():
            if isinstance(digest, str) and digest.startswith(PLACEHOLDER_PREFIX):
                unresolved.append(artifact_name)
            else:
                require(
                    isinstance(digest, str) and SHA256_RE.fullmatch(digest) is not None,
                    f"{model}/{artifact_name}: artifact hash must be a full lowercase SHA-256",
                )
        if unresolved:
            require(not ready, f"{model}: artifact hashes are unresolved: {unresolved}")
            blockers.append(
                f"final {model.upper()} bitstream/driver archive hashes "
                f"({len(unresolved)} unresolved)"
            )

    for artifact_name in ("bitstream_tar", "driver_tar"):
        hbm_hash = artifacts["hbm"][artifact_name]
        ddr_hash = artifacts["ddr"][artifact_name]
        if not (
            str(hbm_hash).startswith(PLACEHOLDER_PREFIX)
            or str(ddr_hash).startswith(PLACEHOLDER_PREFIX)
        ):
            require(hbm_hash != ddr_hash,
                    f"HBM and DDR {artifact_name} hashes must differ")

    return provenance, blockers


def validate_hwdb(
    path: Path,
    campaign: dict[str, Any],
    provenance: dict[str, Any],
    ready: bool,
) -> dict[str, Any]:
    _, RuntimeHWDB, _ = import_manager_classes()
    value = read_yaml(path)
    if ready:
        validate_filled_template(
            read_yaml(DEFAULT_HWDB), value, f"ready HWDB {path}"
        )
    require(set(value) == {HBM_ENTRY, HBM2000_ENTRY, DDR_ENTRY},
            f"{path}: HWDB must contain the two builds plus the HBM2000 runtime alias")

    conditions = campaign["runtime_conditions"]
    for condition, entry_name, physical_model in RUNTIME_CONDITIONS:
        entry = value[entry_name]
        require(isinstance(entry, dict), f"{entry_name}: HWDB entry must be a mapping")
        exact_keys(
            entry,
            {
                "bitstream_tar",
                "driver_tar",
                "deploy_quintuplet_override",
                "deploy_makefrag_override",
                "custom_runtime_config",
                "fased_runtime_profile",
                "artifact_sha256",
            },
            f"{entry_name}: HWDB entry",
        )
        expected_contract = expected_fased_hwdb_contract(conditions[condition])
        require(
            entry["fased_runtime_profile"] == expected_contract,
            f"{entry_name}: fased_runtime_profile does not exactly match the "
            f"{condition} campaign contract",
        )
        expected_artifact_hashes = provenance["artifact_sha256"][physical_model]
        require(
            entry["artifact_sha256"] == expected_artifact_hashes,
            f"{entry_name}: artifact_sha256 does not exactly match the reviewed "
            f"{physical_model} archive hashes",
        )

    with cwd(DEPLOY):
        parsed = RuntimeHWDB(str(path))

    artifact_commits: dict[str, str] = {}
    for condition, entry_name, physical_model in RUNTIME_CONDITIONS:
        entry = value[entry_name]
        require("agfi" not in entry, f"{entry_name}: XB10 must use bitstream_tar, not AGFI")
        require(entry["deploy_quintuplet_override"] is None,
                f"{entry_name}: do not override bitstream metadata")
        require(entry["deploy_makefrag_override"] is None,
                f"{entry_name}: do not override deploy makefrag")
        expected_profile = Path(conditions[condition]["fased_deployment_path"]).name
        require(entry["custom_runtime_config"] == expected_profile,
                f"{entry_name}: wrong custom runtime config")
        parsed_entry = parsed.get_runtimehwconfig_from_name(entry_name)
        require(parsed_entry.get_local_runtime_conf_path() == f"../sim/custom-runtime-configs/{expected_profile}",
                f"{entry_name}: manager resolves unexpected runtime-config path")
        parsed_profile = parsed_entry.fased_runtime_profile
        require(
            parsed_profile is not None,
            f"{entry_name}: manager dropped the FASED runtime-profile contract",
        )
        expected_contract = expected_fased_hwdb_contract(conditions[condition])
        require(
            parsed_profile.filename == expected_profile
            and parsed_profile.sha256 == expected_contract["sha256"]
            and list(parsed_profile.model_ids) == expected_contract["model_ids"]
            and parsed_profile.settings_per_model
            == expected_contract["settings_per_model"],
            f"{entry_name}: manager parsed an unexpected FASED runtime-profile contract",
        )
        expected_artifact_hashes = provenance["artifact_sha256"][physical_model]
        parsed_artifacts = parsed_entry.artifact_sha256
        require(
            parsed_artifacts is not None
            and parsed_artifacts.bitstream_tar
            == expected_artifact_hashes["bitstream_tar"]
            and parsed_artifacts.driver_tar
            == expected_artifact_hashes["driver_tar"],
            f"{entry_name}: manager parsed an unexpected artifact SHA-256 contract",
        )
        if ready:
            require(not placeholders(entry), f"{entry_name}: unresolved HWDB placeholder")
            artifact_commits[condition] = validate_artifact_pair(
                physical_model, entry, conditions[condition], provenance
            )
        else:
            require(str(entry["bitstream_tar"]).startswith(PLACEHOLDER_PREFIX),
                    f"{entry_name}: template bitstream placeholder missing")
            require(str(entry["driver_tar"]).startswith(PLACEHOLDER_PREFIX),
                    f"{entry_name}: template driver placeholder missing")

    require(value[HBM_ENTRY]["bitstream_tar"] == value[HBM2000_ENTRY]["bitstream_tar"],
            "HBM2000 sensitivity must reuse the HBM2400 bitstream URI")
    require(value[HBM_ENTRY]["driver_tar"] == value[HBM2000_ENTRY]["driver_tar"],
            "HBM2000 sensitivity must reuse the HBM2400 driver URI")
    if ready:
        require(value[HBM_ENTRY]["bitstream_tar"] != value[DDR_ENTRY]["bitstream_tar"],
                "HBM and DDR bitstream URIs must differ")
        require(value[HBM_ENTRY]["driver_tar"] != value[DDR_ENTRY]["driver_tar"],
                "HBM and DDR driver URIs must differ")
        expected_commit = provenance["source_commits"]["firesim"]
        require(set(artifact_commits.values()) == {expected_commit},
                "runtime artifacts do not match the intended FireSim commit")
    return value


def local_artifact(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        require(parsed.netloc in ("", "localhost"), f"unsupported file URI host: {uri}")
        path = Path(unquote(parsed.path))
    elif parsed.scheme == "":
        path = Path(uri)
        if not path.is_absolute():
            path = DEPLOY / path
    else:
        raise ValidationError(
            f"ready audit requires a local path/file:// URI, not {parsed.scheme}://"
        )
    path = path.resolve()
    require(path.is_file(), f"artifact does not exist: {path}")
    return path


def normalized_tar_names(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    result: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        raw_name = member.name
        require(raw_name != "", f"{archive.name}: empty tar member name")
        require(not raw_name.startswith("/"),
                f"{archive.name}: absolute tar member path {raw_name!r}")
        require("\\" not in raw_name,
                f"{archive.name}: non-POSIX tar member path {raw_name!r}")
        raw_parts = raw_name.split("/")
        require(".." not in raw_parts,
                f"{archive.name}: parent traversal in tar member {raw_name!r}")
        name = "/".join(part for part in raw_parts if part not in ("", "."))
        if name == "":
            require(member.isdir(),
                    f"{archive.name}: root tar member must be a directory")
            continue
        require(member.isfile() or member.isdir(),
                f"{archive.name}: unsupported tar member type for {raw_name!r}")
        require(name not in result,
                f"{archive.name}: duplicate canonical tar member {name}")
        result[name] = member
    return result


def tar_member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    require(member.isfile(), f"{archive.name}: {member.name} is not a regular file")
    stream = archive.extractfile(member)
    require(stream is not None, f"cannot read tar member {member.name}")
    if stream is None:  # Keep type narrowing independent of Python assertions.
        raise ValidationError(f"cannot read tar member {member.name}")
    return stream.read()


def parse_metadata(raw: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in raw.decode().strip().split(","):
        require(":" in item, f"malformed bitstream metadata item: {item!r}")
        key, value = item.split(":", 1)
        require(bool(key) and bool(value), f"empty bitstream metadata item: {item!r}")
        require(key not in result, f"duplicate bitstream metadata key: {key}")
        result[key] = value
    return result


def validate_x86_64_elf(raw: bytes, label: str) -> None:
    elf_header_size = 64
    program_header_size = 56
    require(len(raw) >= elf_header_size,
            f"{label}: executable is too short for a complete ELF64 header")
    require(raw[:4] == b"\x7fELF", f"{label}: executable lacks ELF magic")
    require(raw[4] == 2, f"{label}: executable is not ELF64")
    require(raw[5] == 1, f"{label}: executable is not little-endian")
    require(raw[6] == 1, f"{label}: ELF identification version is not current")
    require(
        int.from_bytes(raw[16:18], "little") in (2, 3),
        f"{label}: ELF is neither ET_EXEC nor ET_DYN",
    )
    require(
        int.from_bytes(raw[18:20], "little") == 62,
        f"{label}: executable is not x86-64",
    )
    require(
        int.from_bytes(raw[20:24], "little") == 1,
        f"{label}: ELF header version is not current",
    )
    program_offset = int.from_bytes(raw[32:40], "little")
    header_size = int.from_bytes(raw[52:54], "little")
    entry_size = int.from_bytes(raw[54:56], "little")
    entry_count = int.from_bytes(raw[56:58], "little")
    require(header_size == elf_header_size,
            f"{label}: unexpected ELF64 header size {header_size}")
    require(entry_size == program_header_size,
            f"{label}: unexpected ELF64 program-header size {entry_size}")
    require(0 < entry_count < 0xFFFF,
            f"{label}: ELF has no directly encoded program headers")
    require(program_offset >= header_size,
            f"{label}: ELF program-header table overlaps its header")
    table_size = entry_size * entry_count
    require(
        program_offset <= len(raw) and table_size <= len(raw) - program_offset,
        f"{label}: ELF program-header table is out of bounds",
    )

    executable_load = False
    for index in range(entry_count):
        offset = program_offset + index * entry_size
        program_type = int.from_bytes(raw[offset:offset + 4], "little")
        flags = int.from_bytes(raw[offset + 4:offset + 8], "little")
        if program_type != 1:  # PT_LOAD
            continue
        file_offset = int.from_bytes(raw[offset + 8:offset + 16], "little")
        file_size = int.from_bytes(raw[offset + 32:offset + 40], "little")
        memory_size = int.from_bytes(raw[offset + 40:offset + 48], "little")
        require(memory_size >= file_size,
                f"{label}: PT_LOAD {index} has p_memsz smaller than p_filesz")
        require(
            file_offset <= len(raw) and file_size <= len(raw) - file_offset,
            f"{label}: PT_LOAD {index} extends beyond the bundled executable",
        )
        if flags & 0x1 and file_size > 0:  # PF_X
            executable_load = True
    require(executable_load,
            f"{label}: ELF has no in-bounds executable PT_LOAD segment")


def validate_artifact_pair(
    model: str,
    entry: dict[str, Any],
    model_cfg: dict[str, Any],
    provenance: dict[str, Any],
) -> str:
    bitstream_tar = local_artifact(entry["bitstream_tar"])
    driver_tar = local_artifact(entry["driver_tar"])
    expected_artifacts = provenance["artifact_sha256"][model]
    require(
        sha256(bitstream_tar) == expected_artifacts["bitstream_tar"],
        f"{bitstream_tar}: does not match the reviewed {model} bitstream archive hash",
    )
    require(
        sha256(driver_tar) == expected_artifacts["driver_tar"],
        f"{driver_tar}: does not match the reviewed {model} driver archive hash",
    )
    expected_quintuplet = (
        f"corigine_xb10-firesim-FireSim-{TARGET_CONFIG}-{PLATFORM_CONFIGS[model]}"
    )
    with tarfile.open(bitstream_tar, "r:*") as archive:
        names = normalized_tar_names(archive)
        bit_name = "corigine_xb10/firesim.bit"
        metadata_name = "corigine_xb10/metadata"
        require(bit_name in names and names[bit_name].isfile() and names[bit_name].size > 0,
                f"{bitstream_tar}: missing nonempty {bit_name}")
        require(metadata_name in names, f"{bitstream_tar}: missing {metadata_name}")
        metadata = parse_metadata(tar_member_bytes(archive, names[metadata_name]))
        require(metadata.get("firesim-buildquintuplet") == expected_quintuplet,
                f"{bitstream_tar}: build quintuplet mismatch")
        require(metadata.get("firesim-deployquintuplet") == expected_quintuplet,
                f"{bitstream_tar}: deploy quintuplet mismatch")
        firesim_commit = metadata.get("firesim-commit", "")
        expected_commit = provenance["source_commits"]["firesim"]
        require(
            firesim_commit == expected_commit,
            f"{bitstream_tar}: FireSim commit {firesim_commit!r} does not match "
            f"the intended clean commit {expected_commit}",
        )

    profile_name = Path(model_cfg["fased_deployment_path"]).name
    with tarfile.open(driver_tar, "r:*") as archive:
        names = normalized_tar_names(archive)
        require("FireSim-corigine_xb10" in names
                and names["FireSim-corigine_xb10"].isfile(),
                f"{driver_tar}: missing FireSim-corigine_xb10")
        driver_member = names["FireSim-corigine_xb10"]
        require(driver_member.size > 0, f"{driver_tar}: empty FireSim-corigine_xb10")
        require(
            driver_member.mode & 0o111 != 0,
            f"{driver_tar}: FireSim-corigine_xb10 is not executable",
        )
        require(profile_name in names, f"{driver_tar}: missing {profile_name}")
        profile_hash = hashlib.sha256(
            tar_member_bytes(archive, names[profile_name])
        ).hexdigest()
        require(profile_hash == model_cfg["fased_sha256"],
                f"{driver_tar}: bundled FASED profile hash mismatch")
        driver_bytes = tar_member_bytes(archive, driver_member)
        validate_x86_64_elf(driver_bytes, f"{driver_tar}: FireSim-corigine_xb10")
        profile_text = tar_member_bytes(archive, names[profile_name]).decode()
        register_names = set()
        for line in profile_text.splitlines():
            match = re.fullmatch(r"\+mm_(.+)_[0-4]=[^\s]+", line.strip())
            if match:
                register_names.add(match.group(1))
        require(register_names, f"{driver_tar}: bundled profile has no indexed registers")
        missing_registers = sorted(
            name for name in register_names if name.encode() not in driver_bytes
        )
        require(not missing_registers,
                f"{driver_tar}: driver lacks profile registers {missing_registers}")
        for model_id in range(5):
            require(f"memory_stats{model_id}.csv".encode() in driver_bytes,
                    f"{driver_tar}: driver lacks FASED constructor/model {model_id}")
    return firesim_commit


def validate_campaign(campaign: dict[str, Any], ready: bool) -> list[str]:
    exact_keys(
        campaign,
        {
            "schema_version",
            "artifact_provenance",
            "loading_contract",
            "slot_contract",
            "runtime_conditions",
            "run_rule",
            "cases",
        },
        "campaign",
    )
    require(campaign["schema_version"] == 1, "unexpected campaign schema")
    validate_case_contracts(campaign["cases"])
    load = campaign["loading_contract"]
    exact_keys(
        load,
        {
            "manager_argument",
            "mechanism",
            "address_hash_crossings",
            "binary_variant",
            "forbid_unhashed_binary",
            "forbid_extra_loadmem_plusarg",
            "hash_parameters",
        },
        "campaign loading_contract",
    )
    require(load["manager_argument"] == "+prog0", "manager load argument changed")
    require(load["mechanism"] == "fesvr-elf-via-firesim-loadmem",
            "campaign load mechanism changed")
    require(load["address_hash_crossings"] == 0, "hashed ELF would be hashed again")
    require(load["binary_variant"] == "hashed-timed-fused-soc-elf",
            "campaign binary variant changed")
    require(load["forbid_unhashed_binary"] is True, "unhashed ELF guard disabled")
    require(load["forbid_extra_loadmem_plusarg"] is True, "+loadmem guard disabled")
    expected_hash_parameters = {
        "elf_base": "0x0",
        "size": "0x80000000",
        "unit_bytes": 32,
        "slices": 4,
        "gpu_host_base": "0x100000000",
    }
    require(load["hash_parameters"] == expected_hash_parameters,
            "campaign address-hash parameters changed")

    slot = campaign["slot_contract"]
    exact_keys(
        slot,
        {
            "host",
            "logical_slots",
            "logical_slot_index",
            "physical_selection",
            "forbidden_database",
        },
        "campaign slot_contract",
    )
    require(slot["host"] == "localhost" and slot["logical_slots"] == 1,
            "campaign is not a single localhost slot")
    require(slot["logical_slot_index"] == 0, "FireSim logical slot must be zero")
    require(slot["physical_selection"] == "coordinated-one-entry-fpga-db",
            "physical slot selection guard changed")
    require(slot["forbidden_database"] == "/opt/firesim-db.json",
            "shared eight-card database guard changed")

    rule = campaign["run_rule"]
    exact_keys(
        rule,
        {
            "one_case_per_manager_invocation",
            "excluded_first_runs_per_case_condition",
            "captured_runs_per_case_condition_minimum",
            "alternate_runtime_condition_order_across_run_blocks_when_practical",
            "retain_every_correctness_result",
            "silent_retry_or_discard",
            "post_run_completeness_gate",
            "require_all_seven_simoutputs_before_counting",
            "require_terminal_memory_stats_rows_before_counting",
            "require_successful_simulator_exit_before_counting",
            "case_count",
            "physical_bitstream_count",
            "runtime_condition_count",
            "minimum_total_invocations",
            "minimum_captured_results",
        },
        "campaign run_rule",
    )
    require(rule["one_case_per_manager_invocation"] is True,
            "single-slot campaign must run one case per invocation")
    require(rule["excluded_first_runs_per_case_condition"] == 1,
            "campaign must exclude exactly the labelled first run")
    require(rule["captured_runs_per_case_condition_minimum"] >= 5,
            "campaign needs at least five captured runs per case/condition")
    require(rule["alternate_runtime_condition_order_across_run_blocks_when_practical"] is True,
            "runtime-condition order alternation rule missing")
    require(rule["retain_every_correctness_result"] is True,
            "correctness retention rule missing")
    require(rule["silent_retry_or_discard"] == "forbidden",
            "silent retry/discard must be forbidden")
    require(
        rule["post_run_completeness_gate"]
        == (
            "validate_xb10_runtime_configs.py --captured-result-dir "
            "CONDITION=/absolute/path"
        ),
        "mandatory post-run result-completeness gate changed",
    )
    require(rule["require_all_seven_simoutputs_before_counting"] is True,
            "captured results must contain all seven requested outputs")
    require(rule["require_terminal_memory_stats_rows_before_counting"] is True,
            "captured results must contain terminal memory-statistics rows")
    require(rule["require_successful_simulator_exit_before_counting"] is True,
            "captured results must contain a successful simulator exit")
    require(rule["case_count"] == 9 and rule["physical_bitstream_count"] == 2,
            "physical controlled-pair dimensions changed")
    require(rule["runtime_condition_count"] == 3,
            "campaign must contain DDR2133, HBM2400, and HBM2000")
    minimum_runs = 9 * 3 * (1 + rule["captured_runs_per_case_condition_minimum"])
    minimum_captured = 9 * 3 * rule["captured_runs_per_case_condition_minimum"]
    require(rule["minimum_total_invocations"] == minimum_runs,
            "minimum invocation count is inconsistent")
    require(rule["minimum_captured_results"] == minimum_captured,
            "minimum captured-result count is inconsistent")

    blockers: list[str] = []
    conditions = campaign["runtime_conditions"]
    require(list(conditions) == ["hbm2400", "hbm2000", "ddr2133"],
            "runtime conditions or their stable order changed")
    expected_condition_bindings = {
        "hbm2400": {
            "physical_bitstream": "hbm",
            "runtime_template": "xb10-runtime-hbm.template.yaml",
            "hwdb_entry": HBM_ENTRY,
        },
        "hbm2000": {
            "physical_bitstream": "hbm",
            "runtime_template": "xb10-runtime-hbm2000.template.yaml",
            "hwdb_entry": HBM2000_ENTRY,
        },
        "ddr2133": {
            "physical_bitstream": "ddr",
            "runtime_template": "xb10-runtime-ddr.template.yaml",
            "hwdb_entry": DDR_ENTRY,
        },
    }
    for condition, cfg in conditions.items():
        exact_keys(
            cfg,
            {
                "physical_bitstream",
                "runtime_template",
                "hwdb_entry",
                "fased_source_path",
                "fased_deployment_path",
                "fased_sha256",
                "required_fased_model_ids",
                "settings_per_model",
            },
            f"campaign runtime_conditions.{condition}",
        )
        for field, expected in expected_condition_bindings[condition].items():
            require(
                cfg[field] == expected,
                f"{condition}: {field} does not match the reviewed binding",
            )
        ids = cfg["required_fased_model_ids"]
        require(ids == [0, 1, 2, 3, 4], f"{condition}: FASED IDs must be 0..4")
        source = HERE / cfg["fased_source_path"]
        validate_fased_profile(source, ids, cfg["settings_per_model"])
        require(sha256(source) == cfg["fased_sha256"],
                f"{condition}: FASED source hash mismatch")

        deployed = HERE / cfg["fased_deployment_path"]
        if deployed.is_file():
            validate_fased_profile(deployed, ids, cfg["settings_per_model"])
            require(sha256(deployed) == cfg["fased_sha256"],
                    f"{condition}: deployed FASED copy differs from canonical source")
        elif ready:
            raise ValidationError(
                f"{condition}: manager-visible FASED profile is missing: {deployed}"
            )
        else:
            blockers.append(f"manager-visible {condition.upper()} profile copy: {deployed}")
    return blockers


def validate_manager_load_path_source() -> None:
    runtime_source = (DEPLOY / "runtools" / "runtime_config.py").read_text()
    tsi_source = (
        CHIPYARD / "generators" / "firechip" / "bridgestubs" / "src" / "main" /
        "cc" / "fesvr" / "firesim_tsi.cc"
    ).read_text()
    bridge_source = (
        CHIPYARD / "generators" / "firechip" / "bridgestubs" / "src" / "main" /
        "cc" / "bridges" / "tsibridge.cc"
    ).read_text()
    require('array_to_plusargs(all_bootbinaries, "+prog")' in runtime_source,
            "manager no longer passes workload binaries through +progN")
    require("has_loadmem = can_have_loadmem" in tsi_source,
            "FireSim FESVR no longer automatically selects LoadMem")
    require("loadmem_widget.write_mem_chunk(" in bridge_source,
            "TSI bridge no longer bypasses target fabric via LoadMem writes")
    require("loadmem.addr + mem_host_offset" in bridge_source,
            "TSI bridge LoadMem address path changed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hwdb", type=Path, default=DEFAULT_HWDB)
    parser.add_argument("--hbm-runtime", type=Path, default=DEFAULT_HBM_RUNTIME)
    parser.add_argument(
        "--hbm2000-runtime", type=Path, default=DEFAULT_HBM2000_RUNTIME
    )
    parser.add_argument("--ddr-runtime", type=Path, default=DEFAULT_DDR_RUNTIME)
    parser.add_argument("--campaign", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument(
        "--captured-result-dir",
        action="append",
        default=[],
        metavar="CONDITION=/absolute/path",
        help=(
            "repeat for each completed FireSim job directory; CONDITION must be "
            "hbm2400, hbm2000, or ddr2133 and every path must contain the exact "
            "profile receipt, five UART acceptance diagnostics, one successful "
            "simulator exit, and terminal rows in all five memory-statistics files"
        ),
    )
    parser.add_argument(
        "--ready",
        action="store_true",
        help="require filled local tarballs, one-entry FPGA DB, and deployed profiles",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    campaign_path = args.campaign.resolve()
    campaign = read_yaml(campaign_path)
    if campaign_path == DEFAULT_CAMPAIGN.resolve():
        validate_checked_in_campaign_placeholders(campaign)
    if args.ready:
        validate_filled_template(
            read_yaml(DEFAULT_CAMPAIGN), campaign, "ready campaign"
        )
    validate_build_pair()
    blockers = validate_campaign(campaign, args.ready)
    captured_results = [
        parse_captured_result_spec(spec) for spec in args.captured_result_dir
    ]
    for condition, result_dir in captured_results:
        validate_captured_result_dir(result_dir, condition, campaign)
    provenance, provenance_blockers = validate_artifact_provenance(campaign, args.ready)
    blockers.extend(provenance_blockers)
    validate_manager_load_path_source()
    known_workloads = validate_workloads(campaign)
    hwdb = validate_hwdb(args.hwdb.resolve(), campaign, provenance, args.ready)
    hbm_runtime, hbm_db = validate_runtime_yaml(
        args.hbm_runtime.resolve(), HBM_ENTRY, known_workloads, args.ready
    )
    hbm2000_runtime, hbm2000_db = validate_runtime_yaml(
        args.hbm2000_runtime.resolve(), HBM2000_ENTRY, known_workloads, args.ready
    )
    ddr_runtime, ddr_db = validate_runtime_yaml(
        args.ddr_runtime.resolve(), DDR_ENTRY, known_workloads, args.ready
    )
    normalized_runtimes = [
        normalized_runtime_pair(runtime)
        for runtime in (hbm_runtime, hbm2000_runtime, ddr_runtime)
    ]
    require(all(runtime == normalized_runtimes[0]
                for runtime in normalized_runtimes[1:]),
            "runtime templates differ beyond condition selection/result suffix")
    require(hbm_db == hbm2000_db == ddr_db,
            "all conditions must use the same coordinated one-entry DB")

    all_placeholders = (
        placeholders(hwdb)
        + placeholders(hbm_runtime)
        + placeholders(hbm2000_runtime)
        + placeholders(ddr_runtime)
    )
    if args.ready:
        require(not all_placeholders, f"ready configs still contain: {all_placeholders}")
        print("PASS: deployment-ready host artifacts and one-entry slot database validated")
    else:
        actual_placeholders = Counter(all_placeholders)
        require(
            actual_placeholders == EXPECTED_CONFIG_TEMPLATE_PLACEHOLDERS,
            "template fail-closed references changed: expected "
            f"{EXPECTED_CONFIG_TEMPLATE_PLACEHOLDERS}, got {actual_placeholders}",
        )
        blockers.extend([
            "two produced firesim.tar.gz URIs",
            "two matching driver-bundle.tar.gz URIs",
            "four matching bitstream/driver archive SHA-256 values",
            "one coordinated one-entry FPGA DB path (shared by all runtime files)",
        ])
        print("PASS: fail-closed host-only templates validated (not deployment-ready)")

    print("PASS: exact 20 MHz TIMING HBM/DDR controlled build pair")
    print("PASS: 9 hashed/timed two-SM ELFs and FireSim +prog0 -> LoadMem path")
    print("PASS: five indexed FASED model IDs (0..4) for all three runtime conditions")
    print("PASS: explicit one-slot localhost topology; shared eight-card DB forbidden")
    print("PASS: 2 physical bitstreams / 3 runtime conditions")
    print("PASS: reviewed source/FESVR/generated/profile/artifact provenance contract")
    print("PASS: campaign minimum 162 invocations / 135 captured results")
    if args.captured_result_dir:
        print(
            "PASS: "
            f"{len(args.captured_result_dir)} captured result director"
            f"{'y' if len(args.captured_result_dir) == 1 else 'ies'} "
            "contain all mandatory outputs"
        )
    if blockers:
        print("BLOCKED (expected for template mode):")
        for blocker in blockers:
            print(f"  - {blocker}")
    print("No SSH, FPGA, Vivado, driver, or programming operation was performed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValidationError, KeyError, OSError, ValueError, tarfile.TarError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
