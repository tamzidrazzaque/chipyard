#!/usr/bin/env python3
"""Expand one unsuffixed FASED runtime config over every memory-model bridge.

FireSim's FASED driver expects ``+mm_<register>_<model-id>=<value>``.  The
checked-in custom runtime configs intentionally omit ``_<model-id>``.  This
tool validates that input form and emits an identical setting set for each
requested model ID.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence


SETTING_RE = re.compile(r"^\+mm_([A-Za-z][A-Za-z0-9_]*)=([0-9]+)$")
INDEXED_NAME_RE = re.compile(r"_[0-9]+$")
FASED_WIDGET_CLASS = "midas.models.FASEDMemoryTimingModel"
FASED_TARGET_RE = re.compile(r"\|FASEDBridge_([0-9]+)$")
CPP_UINT32_MAX = (1 << 32) - 1


class ConfigError(ValueError):
    """The source config or annotation file is unsafe to expand."""


def parse_settings(lines: Iterable[str]) -> list[tuple[str, str]]:
    settings: list[tuple[str, str]] = []
    seen: set[str] = set()

    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = SETTING_RE.fullmatch(line)
        if match is None:
            raise ConfigError(
                f"line {line_number}: expected +mm_<register>=<decimal integer>, got {line!r}"
            )
        name, value = match.groups()
        if INDEXED_NAME_RE.search(name):
            raise ConfigError(
                f"line {line_number}: setting {name!r} already looks model-indexed"
            )
        if name in seen:
            raise ConfigError(f"line {line_number}: duplicate setting {name!r}")
        if int(value) > CPP_UINT32_MAX:
            raise ConfigError(
                f"line {line_number}: value {value} exceeds the FASED driver's uint32 parser"
            )
        seen.add(name)
        settings.append((name, value))

    if not settings:
        raise ConfigError("source config contains no FASED settings")
    return settings


def model_ids_from_annotations(path: Path) -> list[int]:
    try:
        annotations = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"cannot read annotation JSON {path}: {error}") from error
    if not isinstance(annotations, list):
        raise ConfigError("annotation JSON top level is not an array")

    model_ids: list[int] = []
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        if annotation.get("widgetClass") != FASED_WIDGET_CLASS:
            continue
        target = annotation.get("target")
        match = FASED_TARGET_RE.search(target) if isinstance(target, str) else None
        if match is None:
            raise ConfigError(f"FASED bridge has unexpected target name {target!r}")
        model_ids.append(int(match.group(1)))

    if not model_ids:
        raise ConfigError("annotation JSON contains no FASED memory-model bridges")
    if len(set(model_ids)) != len(model_ids):
        raise ConfigError(f"duplicate FASED bridge IDs in annotations: {model_ids}")

    model_ids.sort()
    expected = list(range(len(model_ids)))
    if model_ids != expected:
        raise ConfigError(
            f"FASED bridge IDs must be contiguous from zero: got {model_ids}, expected {expected}"
        )
    return model_ids


def expand(settings: Sequence[tuple[str, str]], model_ids: Sequence[int]) -> str:
    return "".join(
        f"+mm_{name}_{model_id}={value}\n"
        for model_id in model_ids
        for name, value in settings
    )


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="unsuffixed +mm_ runtime config")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--annotations",
        type=Path,
        help="target annotation JSON; derive and validate FASED bridge IDs",
    )
    selector.add_argument(
        "--bridge-count",
        type=positive_int,
        help="number of contiguous model IDs, starting at zero",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = parse_settings(args.config.read_text(encoding="utf-8").splitlines())
        model_ids = (
            model_ids_from_annotations(args.annotations)
            if args.annotations is not None
            else list(range(args.bridge_count))
        )
    except (OSError, UnicodeError, ConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    sys.stdout.write(expand(settings, model_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
