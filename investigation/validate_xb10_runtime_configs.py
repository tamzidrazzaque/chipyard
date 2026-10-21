#!/usr/bin/env python3
"""Validate the host-only XB10 controlled-pair deployment templates.

The default mode is deliberately non-deployable: it checks the checked-in
templates, nine workload ELFs, and canonical five-index FASED profiles while
requiring artifact/slot placeholders to remain present.  ``--ready`` instead
requires filled configs, local tarballs, deployed profiles, and an explicit
one-entry FPGA database.  Neither mode opens SSH nor accesses an FPGA.
"""

from __future__ import annotations

import argparse
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
PLATFORM_CONFIGS = {
    "hbm": "HBM2FRFCFS16GBDualPC_BaseCorigineXB10Config",
    "ddr": "FRFCFS8GBQuadRank_BaseCorigineXB10Config",
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
PLACEHOLDER_PREFIX = "__REPLACE_"


class ValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


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


@contextmanager
def cwd(path: Path) -> Iterator[None]:
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def validate_build_pair() -> None:
    recipes = read_yaml(HERE / "xb10-build-recipes.yaml")
    hbm = recipes[HBM_ENTRY]
    ddr = recipes[DDR_ENTRY]
    for model, recipe in (("hbm", hbm), ("ddr", ddr)):
        require(recipe["PLATFORM"] == "corigine_xb10", f"{model}: wrong platform")
        require(recipe["TARGET_PROJECT"] == "firesim", f"{model}: wrong project")
        require(recipe["DESIGN"] == "FireSim", f"{model}: wrong design")
        require(recipe["TARGET_CONFIG"] == TARGET_CONFIG, f"{model}: wrong target")
        require(
            recipe["PLATFORM_CONFIG"] == PLATFORM_CONFIGS[model],
            f"{model}: wrong platform config",
        )
        args = recipe["platform_config_args"]
        require(args == {"fpga_frequency": 20, "build_strategy": "TIMING"},
                f"{model}: build must be the initial 20 MHz TIMING recipe")

    hbm_normalized = copy.deepcopy(hbm)
    ddr_normalized = copy.deepcopy(ddr)
    hbm_normalized.pop("PLATFORM_CONFIG")
    ddr_normalized.pop("PLATFORM_CONFIG")
    require(
        hbm_normalized == ddr_normalized,
        "controlled build recipes differ in fields other than PLATFORM_CONFIG",
    )


def validate_fased_profile(path: Path, ids: list[int], settings_count: int) -> None:
    require(path.is_file(), f"missing FASED profile: {path}")
    indexed: dict[int, dict[str, str]] = {}
    setting_re = re.compile(r"^\+mm_(.+)_([0-9]+)=([^\s]+)$")
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = setting_re.fullmatch(line)
        require(match is not None, f"{path}:{lineno}: setting is not explicitly indexed")
        assert match is not None
        name, index_text, value = match.groups()
        index = int(index_text)
        model = indexed.setdefault(index, {})
        require(name not in model, f"{path}:{lineno}: duplicate {name}_{index}")
        model[name] = value

    require(sorted(indexed) == ids, f"{path}: expected model IDs {ids}, got {sorted(indexed)}")
    reference = indexed[ids[0]]
    require(len(reference) == settings_count,
            f"{path}: expected {settings_count} settings/model, got {len(reference)}")
    for index in ids[1:]:
        require(indexed[index] == reference,
                f"{path}: model {index} does not match model {ids[0]}")


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


def validate_workloads(campaign: dict[str, Any]) -> set[Path]:
    _, _, WorkloadConfig = import_manager_classes()
    cases = campaign["cases"]
    require([case["id"] for case in cases] == EXPECTED_CASE_IDS,
            "campaign does not contain the exact ordered nine-case set")
    require(len({case["id"] for case in cases}) == 9, "duplicate campaign case")

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
        params = result["mu_addr_hash_parameters"]
        require(result["mu_addr_hash"] == 1 and params["enabled"] is True,
                f"{case['id']}: ELF manifest is not hashed")
        require(params["required_load_path"] == "direct-memory-load",
                f"{case['id']}: wrong required load path")
        require(params["elf_base"] == "0x0", f"{case['id']}: wrong hash base")
        require(params["size"] == "0x80000000", f"{case['id']}: wrong hash size")
        require(params["unit_bytes"] == 32, f"{case['id']}: wrong hash unit")
        require(params["slices"] == 4, f"{case['id']}: wrong hash slice count")
        require(params["gpu_host_base"] == "0x100000000",
                f"{case['id']}: wrong GPU host base")
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
        require("workloads" not in workload_json,
                f"{case['id']}: one-slot campaign requires a uniform one-job JSON")
        require(workload_json.get("common_rootfs") is None,
                f"{case['id']}: unexpected root filesystem")
        reference = manager_workload_reference(workload_path)
        with cwd(DEPLOY):
            parsed = WorkloadConfig(reference, "validation-only", None)
            job = parsed.get_job(0)
            resolved_boot = (DEPLOY / job.bootbinary_path()).resolve()
        require(parsed.uniform_mode, f"{case['id']}: workload is not uniform-mode")
        require(resolved_boot == elf, f"{case['id']}: manager resolves the wrong boot ELF")
        require(job.rootfs_path() is None, f"{case['id']}: manager derived an unwanted rootfs")
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
    require(fpga_db != "/opt/firesim-db.json", f"{path}: shared eight-card DB is forbidden")
    if ready:
        require(not fpga_db.startswith(PLACEHOLDER_PREFIX), f"{path}: FPGA DB is unresolved")
        validate_one_entry_fpga_db(Path(fpga_db))
    else:
        require(fpga_db == "__REPLACE_WITH_COORDINATED_ONE_ENTRY_FPGA_DB_JSON__",
                f"{path}: template must retain the coordinated-slot placeholder")

    target = value["target_config"]
    require(target["topology"] == "no_net_config" and target["no_net_num_nodes"] == 1,
            f"{path}: target must be exactly one no-network node")
    require(target["default_hw_config"] == expected_entry, f"{path}: wrong HWDB entry")
    require("+loadmem" not in target["plusarg_passthrough"],
            f"{path}: never add +loadmem for an ELF supplied through +prog0")
    require(value["metasimulation"]["metasimulation_enabled"] is False,
            f"{path}: FPGA runtime template unexpectedly enables metasimulation")
    require(parsed.defaulthwconfig == expected_entry, f"{path}: manager parser disagrees")

    workload_ref = value["workload"]["workload_name"]
    resolved_workload = (DEPLOY / "workloads" / workload_ref).resolve()
    require(resolved_workload in known_workloads, f"{path}: workload is outside campaign set")
    return value, fpga_db


def validate_one_entry_fpga_db(path: Path) -> None:
    require(path.is_file(), f"coordinated FPGA DB does not exist: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, list) and len(value) == 1,
            f"{path}: expected exactly one coordinated physical FPGA entry")
    entry = value[0]
    require(isinstance(entry, dict), f"{path}: FPGA entry must be a mapping")
    require({"bdf", "uid", "device"}.issubset(entry), f"{path}: FPGA entry schema incomplete")
    require(re.fullmatch(r"[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]", str(entry["bdf"])) is not None,
            f"{path}: invalid BDF shape")
    require(bool(str(entry["uid"]).strip()), f"{path}: empty JTAG UID")
    require(bool(str(entry["device"]).strip()), f"{path}: empty device name")


def validate_hwdb(path: Path, campaign: dict[str, Any], ready: bool) -> dict[str, Any]:
    _, RuntimeHWDB, _ = import_manager_classes()
    value = read_yaml(path)
    require(set(value) == {HBM_ENTRY, HBM2000_ENTRY, DDR_ENTRY},
            f"{path}: HWDB must contain the two builds plus the HBM2000 runtime alias")
    with cwd(DEPLOY):
        parsed = RuntimeHWDB(str(path))

    artifact_commits: dict[str, str] = {}
    conditions = campaign["runtime_conditions"]
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
        if ready:
            require(not placeholders(entry), f"{entry_name}: unresolved HWDB placeholder")
            artifact_commits[condition] = validate_artifact_pair(
                physical_model, entry, conditions[condition]
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
        require(len(set(artifact_commits.values())) == 1,
                "runtime conditions were not built from the same FireSim commit")
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
    return {member.name.removeprefix("./"): member for member in archive.getmembers()}


def tar_member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    stream = archive.extractfile(member)
    require(stream is not None, f"cannot read tar member {member.name}")
    assert stream is not None
    return stream.read()


def parse_metadata(raw: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in raw.decode().strip().split(","):
        key, value = item.split(":", 1)
        result[key] = value
    return result


def validate_artifact_pair(
    model: str, entry: dict[str, Any], model_cfg: dict[str, Any]
) -> str:
    bitstream_tar = local_artifact(entry["bitstream_tar"])
    driver_tar = local_artifact(entry["driver_tar"])
    expected_quintuplet = (
        f"corigine_xb10-firesim-FireSim-{TARGET_CONFIG}-{PLATFORM_CONFIGS[model]}"
    )
    with tarfile.open(bitstream_tar, "r:*") as archive:
        names = normalized_tar_names(archive)
        bit_name = "corigine_xb10/firesim.bit"
        metadata_name = "corigine_xb10/metadata"
        require(bit_name in names and names[bit_name].size > 0,
                f"{bitstream_tar}: missing nonempty {bit_name}")
        require(metadata_name in names, f"{bitstream_tar}: missing {metadata_name}")
        metadata = parse_metadata(tar_member_bytes(archive, names[metadata_name]))
        require(metadata.get("firesim-buildquintuplet") == expected_quintuplet,
                f"{bitstream_tar}: build quintuplet mismatch")
        require(metadata.get("firesim-deployquintuplet") == expected_quintuplet,
                f"{bitstream_tar}: deploy quintuplet mismatch")
        firesim_commit = metadata.get("firesim-commit", "")
        require(re.fullmatch(r"[0-9a-f]{40}", firesim_commit) is not None,
                f"{bitstream_tar}: FireSim commit is absent, malformed, or dirty")

    profile_name = Path(model_cfg["fased_deployment_path"]).name
    with tarfile.open(driver_tar, "r:*") as archive:
        names = normalized_tar_names(archive)
        require("FireSim-corigine_xb10" in names,
                f"{driver_tar}: missing FireSim-corigine_xb10")
        require(names["FireSim-corigine_xb10"].size > 0,
                f"{driver_tar}: empty FireSim-corigine_xb10")
        require(profile_name in names, f"{driver_tar}: missing {profile_name}")
        profile_hash = hashlib.sha256(
            tar_member_bytes(archive, names[profile_name])
        ).hexdigest()
        require(profile_hash == model_cfg["fased_sha256"],
                f"{driver_tar}: bundled FASED profile hash mismatch")
        driver_bytes = tar_member_bytes(archive, names["FireSim-corigine_xb10"])
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
    require(campaign["schema_version"] == 1, "unexpected campaign schema")
    load = campaign["loading_contract"]
    require(load["manager_argument"] == "+prog0", "manager load argument changed")
    require(load["mechanism"] == "fesvr-elf-via-firesim-loadmem",
            "campaign load mechanism changed")
    require(load["address_hash_crossings"] == 0, "hashed ELF would be hashed again")
    require(load["binary_variant"] == "hashed-timed-fused-soc-elf",
            "campaign binary variant changed")
    require(load["forbid_unhashed_binary"] is True, "unhashed ELF guard disabled")
    require(load["forbid_extra_loadmem_plusarg"] is True, "+loadmem guard disabled")

    slot = campaign["slot_contract"]
    require(slot["host"] == "localhost" and slot["logical_slots"] == 1,
            "campaign is not a single localhost slot")
    require(slot["logical_slot_index"] == 0, "FireSim logical slot must be zero")
    require(slot["physical_selection"] == "coordinated-one-entry-fpga-db",
            "physical slot selection guard changed")

    rule = campaign["run_rule"]
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
    require(conditions["hbm2400"]["physical_bitstream"] == "hbm" and
            conditions["hbm2000"]["physical_bitstream"] == "hbm" and
            conditions["ddr2133"]["physical_bitstream"] == "ddr",
            "runtime-to-physical-bitstream mapping changed")
    for condition, cfg in conditions.items():
        ids = cfg["required_fased_model_ids"]
        require(ids == [0, 1, 2, 3, 4], f"{condition}: FASED IDs must be 0..4")
        source = (HERE / cfg["fased_source_path"]).resolve()
        require(sha256(source) == cfg["fased_sha256"],
                f"{condition}: FASED source hash mismatch")
        validate_fased_profile(source, ids, cfg["settings_per_model"])

        deployed = (HERE / cfg["fased_deployment_path"]).resolve()
        if deployed.is_file():
            require(sha256(deployed) == cfg["fased_sha256"],
                    f"{condition}: deployed FASED copy differs from canonical source")
            validate_fased_profile(deployed, ids, cfg["settings_per_model"])
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
        "--ready",
        action="store_true",
        help="require filled local tarballs, one-entry FPGA DB, and deployed profiles",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    campaign = read_yaml(args.campaign.resolve())
    validate_build_pair()
    blockers = validate_campaign(campaign, args.ready)
    validate_manager_load_path_source()
    known_workloads = validate_workloads(campaign)
    hwdb = validate_hwdb(args.hwdb.resolve(), campaign, args.ready)
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
        require(len(all_placeholders) == 9,
                f"template should contain nine fail-closed references, got {all_placeholders}")
        blockers.extend([
            "two produced firesim.tar.gz URIs",
            "two matching driver-bundle.tar.gz URIs",
            "one coordinated one-entry FPGA DB path (shared by all runtime files)",
        ])
        print("PASS: fail-closed host-only templates validated (not deployment-ready)")

    print("PASS: exact 20 MHz TIMING HBM/DDR controlled build pair")
    print("PASS: 9 hashed/timed two-SM ELFs and FireSim +prog0 -> LoadMem path")
    print("PASS: five indexed FASED model IDs (0..4) for all three runtime conditions")
    print("PASS: explicit one-slot localhost topology; shared eight-card DB forbidden")
    print("PASS: 2 physical bitstreams / 3 runtime conditions")
    print("PASS: campaign minimum 162 invocations / 135 captured results")
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
