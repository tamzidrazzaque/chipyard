#!/usr/bin/env python3
"""Focused fail-closed tests for the XB10 build/runtime validators."""

from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import validate_xb10_runtime_configs as runtime_validator  # noqa: E402


def add_tar_bytes(
    archive: tarfile.TarFile, name: str, data: bytes, mode: int = 0o644
) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mode = mode
    archive.addfile(member, io.BytesIO(data))


class ValidatorHardeningTest(unittest.TestCase):
    def campaign(self) -> dict:
        return yaml.safe_load((HERE / "xb10-runtime-campaign.yaml").read_text())

    def write_valid_captured_result(
        self, result_dir: Path, condition: str = "hbm2400"
    ) -> dict:
        campaign = self.campaign()
        config = campaign["runtime_conditions"][condition]
        for model_id in range(5):
            (result_dir / f"memory_stats{model_id}.csv").write_text(
                "totalReads,totalWrites,\n0,0,\n"
            )
        diagnostics = "".join(
            f"[FASED] Model {model_id} accepted {config['settings_per_model']} "
            "explicit runtime settings; hardware defaults disabled\n"
            for model_id in config["required_fased_model_ids"]
        )
        (result_dir / "uartlog").write_text(
            diagnostics + "*** PASSED *** after 12345 cycles\n"
        )
        receipt = runtime_validator.expected_fased_receipt(config)
        (result_dir / "fased-runtime-profile.applied.json").write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
        )
        return campaign

    def test_production_validators_have_no_assert_statements(self) -> None:
        for name in (
            "validate_xb10_build_configs.py",
            "validate_xb10_runtime_configs.py",
        ):
            tree = ast.parse((HERE / name).read_text(), filename=name)
            asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
            self.assertEqual(asserts, [], f"{name} still depends on Python assert")

    def test_require_survives_optimized_python(self) -> None:
        program = f"""
import sys
sys.path.insert(0, {str(HERE)!r})
import validate_xb10_runtime_configs as validator
try:
    validator.require(False, 'optimized rejection')
except validator.ValidationError:
    raise SystemExit(0)
raise SystemExit(7)
"""
        result = subprocess.run([sys.executable, "-O", "-c", program])
        self.assertEqual(result.returncode, 0)

    def test_checked_in_generated_hashes_remain_post_fix_placeholders(self) -> None:
        campaign = yaml.safe_load((HERE / "xb10-runtime-campaign.yaml").read_text())
        placeholder_paths = runtime_validator.placeholder_leaf_paths(
            campaign["artifact_provenance"]
        )
        self.assertEqual(
            placeholder_paths,
            runtime_validator.EXPECTED_PROVENANCE_PLACEHOLDER_PATHS,
        )
        self.assertEqual(len(placeholder_paths), 21)
        runtime_validator.validate_checked_in_campaign_placeholders(campaign)

        resolved_parent = copy.deepcopy(campaign)
        resolved_parent["artifact_provenance"]["source_commits"]["chipyard"] = (
            "0" * 40
        )
        with self.assertRaises(runtime_validator.ValidationError):
            runtime_validator.validate_checked_in_campaign_placeholders(
                resolved_parent
            )

        generated = campaign["artifact_provenance"]["generated_output_sha256"]
        self.assertTrue(
            {
                "generated_sv",
                "generated_defines_vh",
                "synthesis_xdc",
                "implementation_xdc",
            }.issubset(runtime_validator.GENERATED_OUTPUT_FILES)
        )
        for model, hashes in generated.items():
            with self.subTest(model=model):
                self.assertEqual(set(hashes), set(runtime_validator.GENERATED_OUTPUT_FILES))
                self.assertTrue(
                    all(
                        value.startswith(runtime_validator.PLACEHOLDER_PREFIX)
                        for value in hashes.values()
                    )
                )

    def test_config_template_placeholder_multiset_is_exact(self) -> None:
        hwdb = yaml.safe_load(
            (HERE / "xb10-runtime-hwdb.template.yaml").read_text()
        )
        runtimes = [
            yaml.safe_load((HERE / name).read_text())
            for name in (
                "xb10-runtime-hbm.template.yaml",
                "xb10-runtime-hbm2000.template.yaml",
                "xb10-runtime-ddr.template.yaml",
            )
        ]
        actual = runtime_validator.Counter(
            runtime_validator.placeholders(hwdb)
            + [
                placeholder
                for runtime in runtimes
                for placeholder in runtime_validator.placeholders(runtime)
            ]
        )
        self.assertEqual(
            actual, runtime_validator.EXPECTED_CONFIG_TEMPLATE_PLACEHOLDERS
        )

    def test_template_provenance_blocks_ready_mode(self) -> None:
        campaign = yaml.safe_load((HERE / "xb10-runtime-campaign.yaml").read_text())
        with mock.patch.object(runtime_validator, "validate_checked_out_commit"):
            _, blockers = runtime_validator.validate_artifact_provenance(
                campaign, False
            )
        self.assertIn("final clean Chipyard build commit and source gitlinks", blockers)
        with mock.patch.object(
            runtime_validator, "validate_checked_out_commit"
        ), self.assertRaises(runtime_validator.ValidationError):
            runtime_validator.validate_artifact_provenance(campaign, True)

    def test_campaign_semantic_bindings_are_enforced(self) -> None:
        template = yaml.safe_load((HERE / "xb10-runtime-campaign.yaml").read_text())
        mutations = (
            (("loading_contract", "hash_parameters", "unit_bytes"), 64),
            (("slot_contract", "forbidden_database"), "/tmp/different.json"),
            (
                ("runtime_conditions", "hbm2400", "runtime_template"),
                "different.yaml",
            ),
            (
                ("runtime_conditions", "ddr2133", "hwdb_entry"),
                runtime_validator.HBM_ENTRY,
            ),
            (
                ("cases", 0, "elf"),
                runtime_validator.EXPECTED_CASE_PATHS["stream-scale"][1],
            ),
            (
                ("cases", 0, "workload_file"),
                runtime_validator.EXPECTED_CASE_PATHS["stream-scale"][0],
            ),
        )
        for path, replacement in mutations:
            with self.subTest(path=path):
                candidate = copy.deepcopy(template)
                leaf = candidate
                for key in path[:-1]:
                    leaf = leaf[key]
                leaf[path[-1]] = replacement
                with self.assertRaises(runtime_validator.ValidationError):
                    runtime_validator.validate_campaign(candidate, False)

    def test_ready_campaign_can_only_fill_placeholder_leaves(self) -> None:
        template = yaml.safe_load((HERE / "xb10-runtime-campaign.yaml").read_text())

        def fill_placeholders(value: object) -> object:
            if isinstance(value, str) and value.startswith(
                runtime_validator.PLACEHOLDER_PREFIX
            ):
                return "0" * 64
            if isinstance(value, dict):
                return {key: fill_placeholders(child) for key, child in value.items()}
            if isinstance(value, list):
                return [fill_placeholders(child) for child in value]
            return value

        candidate = fill_placeholders(template)
        self.assertIsInstance(candidate, dict)
        candidate["artifact_provenance"]["source_commits"]["firesim"] = "2" * 40
        with self.assertRaisesRegex(runtime_validator.ValidationError, "pinned value"):
            runtime_validator.validate_filled_template(
                template, candidate, "ready campaign"
            )

    def test_known_pre_fix_generated_outputs_are_rejected(self) -> None:
        campaign = yaml.safe_load((HERE / "xb10-runtime-campaign.yaml").read_text())
        campaign["artifact_provenance"]["generated_output_sha256"]["hbm"][
            "target_fir"
        ] = runtime_validator.REJECTED_PRE_FIX_GENERATED_HASHES["hbm"]["target_fir"]
        with mock.patch.object(
            runtime_validator, "validate_checked_out_commit"
        ), self.assertRaisesRegex(runtime_validator.ValidationError, "known pre-fix"):
            runtime_validator.validate_artifact_provenance(campaign, False)

    def test_host_libraries_and_header_tree_match_reviewed_hashes(self) -> None:
        campaign = self.campaign()
        dependency = campaign["artifact_provenance"]["host_dependencies"]
        prefix = Path(dependency["fesvr_prefix"])
        self.assertEqual(
            runtime_validator.sha256(prefix / "lib" / "libfesvr.a"),
            dependency["libfesvr_a_sha256"],
        )
        self.assertEqual(
            runtime_validator.sha256(prefix / "lib" / "libriscv.so"),
            dependency["libriscv_so_sha256"],
        )
        actual = runtime_validator.tree_manifest_sha256(
            prefix / "include"
        )
        self.assertEqual(actual, dependency["include_tree_sha256"])

    def test_fpga_db_uses_manager_uid_and_device_grammar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "fpga.json"
            database.write_text('[{"bdf":"1a:00.0","uid":"no-slash","device":"xcvu19p"}]')
            with self.assertRaisesRegex(runtime_validator.ValidationError, "JTAG UID"):
                runtime_validator.validate_one_entry_fpga_db(database)

            target = Path(temporary) / "valid-fpga.json"
            target.write_text(
                '[{"bdf":"1a:00.0","uid":"adapter/device","device":"xcvu19p"}]'
            )
            link = Path(temporary) / "fpga-link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(
                runtime_validator.ValidationError, "non-symlink"
            ):
                runtime_validator.validate_one_entry_fpga_db(link)

    def test_result_suffix_rejects_path_and_shell_syntax(self) -> None:
        runtime_validator.validate_result_suffix("hbm-run_01.ok", "test")
        for unsafe in ("../escape", ".hidden", "run/child", "run;touch", "$(id)"):
            with self.subTest(unsafe=unsafe), self.assertRaises(
                runtime_validator.ValidationError
            ):
                runtime_validator.validate_result_suffix(unsafe, "test")

    def test_fased_profile_grammar_matches_fail_closed_runtime_contract(self) -> None:
        valid = "".join(
            f"+mm_testSetting_{model_id}=4294967295\n" for model_id in range(5)
        )
        mutations = {
            "blank-line": valid.replace("\n", "\n\n", 1),
            "comment": "# comment\n" + valid,
            "negative": valid.replace("=4294967295", "=-1", 1),
            "trailing-junk": valid.replace("=4294967295", "=1junk", 1),
            "overflow": valid.replace("=4294967295", "=4294967296", 1),
            "carriage-return": valid.replace("\n", "\r\n"),
            "vertical-tab-separator": valid.replace("\n", "\x0b", 1),
            "noncanonical-model": valid.replace("_0=", "_00=", 1),
            "unexpected-model": valid.replace("_4=", "_5=", 1),
            "duplicate": valid + "+mm_testSetting_0=1\n",
        }
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profile.conf"
            profile.write_text(valid)
            runtime_validator.validate_fased_profile(profile, [0, 1, 2, 3, 4], 1)
            for name, contents in mutations.items():
                with self.subTest(name=name):
                    profile.write_bytes(contents.encode("ascii"))
                    with self.assertRaises(runtime_validator.ValidationError):
                        runtime_validator.validate_fased_profile(
                            profile, [0, 1, 2, 3, 4], 1
                        )

            target = Path(temporary) / "target.conf"
            target.write_text(valid)
            profile.unlink()
            profile.symlink_to(target)
            with self.assertRaisesRegex(runtime_validator.ValidationError, "non-symlink"):
                runtime_validator.validate_fased_profile(
                    profile, [0, 1, 2, 3, 4], 1
                )

    def test_campaign_preserves_profile_symlink_identity_for_rejection(self) -> None:
        campaign = self.campaign()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.conf"
            source = (
                HERE
                / campaign["runtime_conditions"]["hbm2400"]["fased_source_path"]
            )
            target.write_bytes(source.read_bytes())
            link = root / "profile-link.conf"
            link.symlink_to(target)
            campaign["runtime_conditions"]["hbm2400"][
                "fased_source_path"
            ] = link.name

            with mock.patch.object(
                runtime_validator, "HERE", root
            ), self.assertRaisesRegex(runtime_validator.ValidationError, "non-symlink"):
                runtime_validator.validate_campaign(campaign, False)

    def test_hwdb_fased_contract_fields_are_exact(self) -> None:
        campaign = self.campaign()
        template = yaml.safe_load(
            (HERE / "xb10-runtime-hwdb.template.yaml").read_text()
        )
        runtime_validator.validate_hwdb(
            HERE / "xb10-runtime-hwdb.template.yaml",
            campaign,
            campaign["artifact_provenance"],
            False,
        )
        mutations = {
            "sha256": "0" * 64,
            "model_ids": [0, 1, 2, 3],
            "settings_per_model": 28,
            "unexpected": True,
        }
        for field, replacement in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                candidate = copy.deepcopy(template)
                contract = candidate[runtime_validator.HBM_ENTRY][
                    "fased_runtime_profile"
                ]
                contract[field] = replacement
                path = Path(temporary) / "config_hwdb.yaml"
                path.write_text(yaml.safe_dump(candidate, sort_keys=False))
                with self.assertRaisesRegex(
                    runtime_validator.ValidationError, "fased_runtime_profile"
                ):
                    runtime_validator.validate_hwdb(
                        path,
                        campaign,
                        campaign["artifact_provenance"],
                        False,
                    )

        artifact_mutations = (
            {"bitstream_tar": "0" * 64, "driver_tar": "1" * 64},
            {"bitstream_tar": "0" * 64},
            {
                "bitstream_tar": "0" * 64,
                "driver_tar": "1" * 64,
                "unexpected": "2" * 64,
            },
        )
        for replacement in artifact_mutations:
            with self.subTest(
                artifact=replacement
            ), tempfile.TemporaryDirectory() as temporary:
                candidate = copy.deepcopy(template)
                candidate[runtime_validator.HBM_ENTRY][
                    "artifact_sha256"
                ] = replacement
                path = Path(temporary) / "config_hwdb.yaml"
                path.write_text(yaml.safe_dump(candidate, sort_keys=False))
                with self.assertRaisesRegex(
                    runtime_validator.ValidationError, "artifact_sha256"
                ):
                    runtime_validator.validate_hwdb(
                        path,
                        campaign,
                        campaign["artifact_provenance"],
                        False,
                    )

    def test_runtime_plusarg_passthrough_must_be_exactly_empty(self) -> None:
        template = yaml.safe_load(
            (HERE / "xb10-runtime-hbm.template.yaml").read_text()
        )
        workload_ref = template["workload"]["workload_name"]
        known_workload = (
            runtime_validator.DEPLOY / "workloads" / workload_ref
        ).resolve()
        with tempfile.TemporaryDirectory() as temporary:
            candidate = copy.deepcopy(template)
            candidate["target_config"]["plusarg_passthrough"] = "+foo=1"
            path = Path(temporary) / "runtime.yaml"
            path.write_text(yaml.safe_dump(candidate, sort_keys=False))
            with self.assertRaisesRegex(
                runtime_validator.ValidationError, "must be empty"
            ):
                runtime_validator.validate_runtime_yaml(
                    path,
                    runtime_validator.HBM_ENTRY,
                    {known_workload},
                    False,
                )

    def test_workload_json_contract_rejects_hooks_and_unsafe_fields(self) -> None:
        expected_boot = "../../radiance-kernels/kernel.soc.elf"
        valid = {
            "benchmark_name": "xb10-two-sm-hashed-timed-stream-copy",
            "common_bootbinary": expected_boot,
            "common_rootfs": None,
            "common_outputs": [],
            "common_simulation_outputs": runtime_validator.EXPECTED_SIM_OUTPUTS,
            "common_simulation_inputs": [],
        }
        runtime_validator.validate_workload_json_contract(
            valid, "stream-copy", expected_boot
        )
        mutations = (
            {"benchmark_name": "x; touch /tmp/unsafe"},
            {"post_run_hook": "touch /tmp/unsafe"},
            {"common_bootbinary": "different.elf"},
            {"common_outputs": ["unexpected"]},
            {"common_simulation_inputs": ["unexpected"]},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                candidate = copy.deepcopy(valid)
                candidate.update(mutation)
                with self.assertRaises(runtime_validator.ValidationError):
                    runtime_validator.validate_workload_json_contract(
                        candidate, "stream-copy", expected_boot
                    )

    def test_captured_result_requires_all_seven_nonempty_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            campaign = self.write_valid_captured_result(result_dir)
            runtime_validator.validate_captured_result_dir(
                result_dir, "hbm2400", campaign
            )

            (result_dir / "memory_stats4.csv").unlink()
            with self.assertRaisesRegex(runtime_validator.ValidationError, "missing"):
                runtime_validator.validate_captured_result_dir(
                    result_dir, "hbm2400", campaign
                )

        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            campaign = self.write_valid_captured_result(result_dir, "ddr2133")
            runtime_validator.validate_captured_result_dir(
                result_dir, "ddr2133", campaign
            )
            (result_dir / "memory_stats4.csv").write_bytes(b"")
            with self.assertRaisesRegex(runtime_validator.ValidationError, "empty"):
                runtime_validator.validate_captured_result_dir(
                    result_dir, "ddr2133", campaign
                )

    def test_captured_result_requires_well_formed_terminal_stats_rows(self) -> None:
        invalid_stats = {
            "header-only": "totalReads,totalWrites,\n",
            "wrong-arity": "totalReads,totalWrites,\n0,\n",
            "nonnumeric": "totalReads,totalWrites,\n0,nope,\n",
            "noncanonical": "totalReads,totalWrites,\n00,0,\n",
            "overflow": "totalReads,totalWrites,\n4294967296,0,\n",
            "huge": "totalReads,totalWrites,\n" + "9" * 5000 + ",0,\n",
            "missing-trailing-comma": "totalReads,totalWrites,\n0,0\n",
        }
        for name, contents in invalid_stats.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                result_dir = Path(temporary)
                campaign = self.write_valid_captured_result(result_dir)
                (result_dir / "memory_stats2.csv").write_text(contents)
                with self.assertRaises(runtime_validator.ValidationError):
                    runtime_validator.validate_captured_result_dir(
                        result_dir, "hbm2400", campaign
                    )

    def test_captured_result_receipt_fields_are_exact(self) -> None:
        mutations = {
            "hwdb_entry": "wrong-entry",
            "model_ids": [0, 1, 2, 3],
            "profile_snapshot": ".wrong-snapshot.conf",
            "profile_source": "wrong-source.conf",
            "settings_per_model": 33,
            "sha256": "0" * 64,
            "total_settings": 169,
        }
        for field, replacement in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                result_dir = Path(temporary)
                campaign = self.write_valid_captured_result(result_dir)
                receipt_path = result_dir / "fased-runtime-profile.applied.json"
                receipt = json.loads(receipt_path.read_text())
                receipt[field] = replacement
                receipt_path.write_text(json.dumps(receipt) + "\n")
                with self.assertRaisesRegex(
                    runtime_validator.ValidationError, "does not exactly match"
                ):
                    runtime_validator.validate_captured_result_dir(
                        result_dir, "hbm2400", campaign
                    )

        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            campaign = self.write_valid_captured_result(result_dir)
            receipt_path = result_dir / "fased-runtime-profile.applied.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["unexpected"] = True
            receipt_path.write_text(json.dumps(receipt) + "\n")
            with self.assertRaises(runtime_validator.ValidationError):
                runtime_validator.validate_captured_result_dir(
                    result_dir, "hbm2400", campaign
                )

            receipt.pop("unexpected")
            receipt.pop("sha256")
            receipt_path.write_text(json.dumps(receipt) + "\n")
            with self.assertRaises(runtime_validator.ValidationError):
                runtime_validator.validate_captured_result_dir(
                    result_dir, "hbm2400", campaign
                )

            expected = runtime_validator.expected_fased_receipt(
                campaign["runtime_conditions"]["hbm2400"]
            )
            canonical = json.dumps(expected, separators=(",", ":"))
            receipt_path.write_text(
                canonical[:-1] + ',"sha256":"' + expected["sha256"] + '"}\n'
            )
            with self.assertRaisesRegex(
                runtime_validator.ValidationError, "duplicate JSON key"
            ):
                runtime_validator.validate_captured_result_dir(
                    result_dir, "hbm2400", campaign
                )

    def test_captured_result_uart_diagnostics_are_exact(self) -> None:
        valid_line = (
            "[FASED] Model 0 accepted 34 explicit runtime settings; "
            "hardware defaults disabled\n"
        )
        mutations = {
            "missing": "".join(
                f"[FASED] Model {model_id} accepted 34 explicit runtime settings; "
                "hardware defaults disabled\n"
                for model_id in range(4)
            ),
            "wrong-count": "".join(
                f"[FASED] Model {model_id} accepted "
                f"{33 if model_id == 2 else 34} explicit runtime settings; "
                "hardware defaults disabled\n"
                for model_id in range(5)
            ),
            "defaults-enabled": "".join(
                f"[FASED] Model {model_id} accepted 34 explicit runtime settings; "
                f"hardware defaults {'enabled' if model_id == 3 else 'disabled'}\n"
                for model_id in range(5)
            ),
            "duplicate": valid_line + valid_line + "".join(
                f"[FASED] Model {model_id} accepted 34 explicit runtime settings; "
                "hardware defaults disabled\n"
                for model_id in range(1, 4)
            ),
            "malformed-extra": "".join(
                f"[FASED] Model {model_id} accepted 34 explicit runtime settings; "
                "hardware defaults disabled\n"
                for model_id in range(5)
            )
            + (
                "[FASED] Model 0 accepted 34 explicit runtime settings; "
                "hardware defaults unknown\n"
            ),
            "zero-padded-model": "".join(
                f"[FASED] Model {'00' if model_id == 0 else model_id} accepted 34 "
                "explicit runtime settings; hardware defaults disabled\n"
                for model_id in range(5)
            ),
            "zero-padded-count": "".join(
                f"[FASED] Model {model_id} accepted "
                f"{'034' if model_id == 0 else 34} explicit runtime settings; "
                "hardware defaults disabled\n"
                for model_id in range(5)
            ),
            "leading-space-extra": "".join(
                f"[FASED] Model {model_id} accepted 34 explicit runtime settings; "
                "hardware defaults disabled\n"
                for model_id in range(5)
            )
            + (
                " [FASED] Model 0 accepted 34 explicit runtime settings; "
                "hardware defaults disabled\n"
            ),
            "ansi-prefix-extra": "".join(
                f"[FASED] Model {model_id} accepted 34 explicit runtime settings; "
                "hardware defaults disabled\n"
                for model_id in range(5)
            )
            + (
                "\x1b[31m[FASED] Model 0 accepted 34 explicit runtime settings; "
                "hardware defaults disabled\x1b[0m\n"
            ),
        }
        for name, uart in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                result_dir = Path(temporary)
                campaign = self.write_valid_captured_result(result_dir)
                (result_dir / "uartlog").write_text(
                    uart + "*** PASSED *** after 12345 cycles\n"
                )
                with self.assertRaises(runtime_validator.ValidationError):
                    runtime_validator.validate_captured_result_dir(
                        result_dir, "hbm2400", campaign
                    )

    def test_captured_result_requires_one_canonical_successful_exit(self) -> None:
        invalid_statuses = {
            "missing": "",
            "failed": "*** FAILED *** (code = 1) after 12345 cycles\n",
            "timeout": "*** FAILED *** simulation timed out after 12345 cycles\n",
            "duplicate": (
                "*** PASSED *** after 12345 cycles\n"
                "*** PASSED *** after 12345 cycles\n"
            ),
            "zero": "*** PASSED *** after 0 cycles\n",
            "zero-padded": "*** PASSED *** after 012345 cycles\n",
            "overflow": "*** PASSED *** after 18446744073709551616 cycles\n",
            "huge": "*** PASSED *** after " + "9" * 5000 + " cycles\n",
            "prefixed": " [*** PASSED *** after 12345 cycles\n",
        }
        for name, status in invalid_statuses.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                result_dir = Path(temporary)
                campaign = self.write_valid_captured_result(result_dir)
                uart_path = result_dir / "uartlog"
                diagnostics = "\n".join(
                    line
                    for line in uart_path.read_text().splitlines()
                    if line.startswith("[FASED]")
                )
                uart_path.write_text(diagnostics + "\n" + status)
                with self.assertRaises(runtime_validator.ValidationError):
                    runtime_validator.validate_captured_result_dir(
                        result_dir, "hbm2400", campaign
                    )

    def test_captured_result_condition_path_syntax_is_fail_closed(self) -> None:
        condition, path = runtime_validator.parse_captured_result_spec(
            "hbm2400=/absolute/result"
        )
        self.assertEqual((condition, path), ("hbm2400", Path("/absolute/result")))
        for invalid in (
            "/absolute/result",
            "= /absolute/result",
            "hbm2400=relative/result",
            "hbm2400=",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(
                runtime_validator.ValidationError
            ):
                runtime_validator.parse_captured_result_spec(invalid)

        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            campaign = self.write_valid_captured_result(result_dir)
            with self.assertRaisesRegex(runtime_validator.ValidationError, "unknown"):
                runtime_validator.validate_captured_result_dir(
                    result_dir, "unknown", campaign
                )

    def make_artifacts(
        self, directory: Path, firesim_commit: str, driver_mode: int = 0o755
    ) -> tuple[Path, Path, dict[str, str], dict[str, str]]:
        quintuplet = (
            "corigine_xb10-firesim-FireSim-"
            f"{runtime_validator.TARGET_CONFIG}-"
            f"{runtime_validator.PLATFORM_CONFIGS['hbm']}"
        )
        metadata = (
            f"firesim-buildquintuplet:{quintuplet},"
            f"firesim-deployquintuplet:{quintuplet},"
            f"firesim-commit:{firesim_commit}"
        ).encode()
        bitstream = directory / "firesim.tar.gz"
        with tarfile.open(bitstream, "w:gz") as archive:
            add_tar_bytes(archive, "corigine_xb10/firesim.bit", b"synthetic bit")
            add_tar_bytes(archive, "corigine_xb10/metadata", metadata)

        profile = "".join(f"+mm_testRegister_{model_id}=1\n" for model_id in range(5))
        profile_name = "hbm-test-profile.conf"
        payload = b"testRegister " + b" ".join(
            f"memory_stats{model_id}.csv".encode() for model_id in range(5)
        )
        elf_header = bytearray(64)
        elf_header[:4] = b"\x7fELF"
        elf_header[4] = 2  # ELF64
        elf_header[5] = 1  # little-endian
        elf_header[6] = 1  # current ELF version
        elf_header[16:18] = (2).to_bytes(2, "little")  # ET_EXEC
        elf_header[18:20] = (62).to_bytes(2, "little")  # EM_X86_64
        elf_header[20:24] = (1).to_bytes(4, "little")  # EV_CURRENT
        elf_header[32:40] = (64).to_bytes(8, "little")  # e_phoff
        elf_header[52:54] = (64).to_bytes(2, "little")  # e_ehsize
        elf_header[54:56] = (56).to_bytes(2, "little")  # e_phentsize
        elf_header[56:58] = (1).to_bytes(2, "little")  # e_phnum
        program_header = bytearray(56)
        program_header[0:4] = (1).to_bytes(4, "little")  # PT_LOAD
        program_header[4:8] = (5).to_bytes(4, "little")  # PF_R | PF_X
        program_header[8:16] = (120).to_bytes(8, "little")  # p_offset
        program_header[32:40] = len(payload).to_bytes(8, "little")  # p_filesz
        program_header[40:48] = len(payload).to_bytes(8, "little")  # p_memsz
        driver_data = bytes(elf_header + program_header) + payload
        driver = directory / "driver-bundle.tar.gz"
        with tarfile.open(driver, "w:gz") as archive:
            add_tar_bytes(archive, "FireSim-corigine_xb10", driver_data, driver_mode)
            add_tar_bytes(archive, profile_name, profile.encode())

        entry = {"bitstream_tar": str(bitstream), "driver_tar": str(driver)}
        model_cfg = {
            "fased_deployment_path": profile_name,
            "fased_sha256": hashlib.sha256(profile.encode()).hexdigest(),
        }
        return bitstream, driver, entry, model_cfg

    def test_artifacts_are_bound_to_intended_commit_and_archive_hashes(self) -> None:
        intended_commit = "1" * 40
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, driver, entry, model_cfg = self.make_artifacts(
                Path(temporary), intended_commit
            )
            provenance = {
                "source_commits": {"firesim": intended_commit},
                "artifact_sha256": {
                    "hbm": {
                        "bitstream_tar": runtime_validator.sha256(bitstream),
                        "driver_tar": runtime_validator.sha256(driver),
                    }
                },
            }
            self.assertEqual(
                runtime_validator.validate_artifact_pair(
                    "hbm", entry, model_cfg, provenance
                ),
                intended_commit,
            )

            wrong_commit = copy.deepcopy(provenance)
            wrong_commit["source_commits"]["firesim"] = "2" * 40
            with self.assertRaisesRegex(
                runtime_validator.ValidationError, "intended clean commit"
            ):
                runtime_validator.validate_artifact_pair(
                    "hbm", entry, model_cfg, wrong_commit
                )

            wrong_driver = copy.deepcopy(provenance)
            wrong_driver["artifact_sha256"]["hbm"]["driver_tar"] = "0" * 64
            with self.assertRaisesRegex(
                runtime_validator.ValidationError, "driver archive hash"
            ):
                runtime_validator.validate_artifact_pair(
                    "hbm", entry, model_cfg, wrong_driver
                )

    def test_duplicate_metadata_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(runtime_validator.ValidationError, "duplicate"):
            runtime_validator.parse_metadata(b"firesim-commit:a,firesim-commit:b")

    def test_tar_alias_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "alias.tar"
            with tarfile.open(bundle, "w") as archive:
                add_tar_bytes(archive, "FireSim-corigine_xb10", b"first")
                add_tar_bytes(archive, "././FireSim-corigine_xb10", b"second")
            with tarfile.open(bundle) as archive, self.assertRaisesRegex(
                runtime_validator.ValidationError, "duplicate canonical"
            ):
                runtime_validator.normalized_tar_names(archive)

    def test_plain_or_nonexecutable_driver_is_rejected(self) -> None:
        with self.assertRaisesRegex(runtime_validator.ValidationError, "ELF"):
            runtime_validator.validate_x86_64_elf(b"plain text", "synthetic driver")
        truncated = bytearray(20)
        truncated[:4] = b"\x7fELF"
        truncated[4:7] = bytes((2, 1, 1))
        truncated[16:20] = bytes((2, 0, 62, 0))
        with self.assertRaisesRegex(runtime_validator.ValidationError, "complete ELF64"):
            runtime_validator.validate_x86_64_elf(
                bytes(truncated), "synthetic driver"
            )

        intended_commit = "1" * 40
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, driver, entry, model_cfg = self.make_artifacts(
                Path(temporary), intended_commit, driver_mode=0o644
            )
            provenance = {
                "source_commits": {"firesim": intended_commit},
                "artifact_sha256": {
                    "hbm": {
                        "bitstream_tar": runtime_validator.sha256(bitstream),
                        "driver_tar": runtime_validator.sha256(driver),
                    }
                },
            }
            with self.assertRaisesRegex(
                runtime_validator.ValidationError, "not executable"
            ):
                runtime_validator.validate_artifact_pair(
                    "hbm", entry, model_cfg, provenance
                )


if __name__ == "__main__":
    unittest.main()
