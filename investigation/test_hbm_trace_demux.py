"""Fail closed when command monitors from separate FASED bridges lack IDs."""

import importlib.util
from pathlib import Path
import unittest


PARSER = (
    Path(__file__).resolve().parents[1]
    / "sims/firesim/sim/scripts/hbm-validation/parse_fased_trace.py"
)
spec = importlib.util.spec_from_file_location("parse_fased_trace", PARSER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {PARSER}")
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


class TraceDemuxTest(unittest.TestCase):
    def test_single_model_allows_untagged_commands(self) -> None:
        parser.require_demultiplexed([
            "[FASED] Model 0 accepted 34 explicit runtime settings; hardware defaults disabled\n",
            "activate(0, 0, 0); // 3\n",
        ])

    def test_multiple_models_require_channel_tags(self) -> None:
        lines = [
            "[FASED] Model 0 accepted 34 explicit runtime settings; hardware defaults disabled\n",
            "[FASED] Model 1 accepted 34 explicit runtime settings; hardware defaults disabled\n",
            "activate(0, 0, 0); // 3\n",
        ]
        with self.assertRaisesRegex(ValueError, "cannot be demultiplexed"):
            parser.require_demultiplexed(lines)

    def test_multiple_models_accept_tagged_commands(self) -> None:
        parser.require_demultiplexed([
            "[FASED] Model 0 accepted 34 explicit runtime settings; hardware defaults disabled\n",
            "[FASED] Model 1 accepted 34 explicit runtime settings; hardware defaults disabled\n",
            "ch0: activate(0, 0, 0); // 3\n",
            "ch1: activate(0, 0, 0); // 3\n",
        ])


if __name__ == "__main__":
    unittest.main()
