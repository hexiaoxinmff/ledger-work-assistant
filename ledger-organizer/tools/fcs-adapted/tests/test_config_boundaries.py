"""Synthetic regressions for reconciliation configuration boundaries."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from config import ConfigError, load_config


class ConfigBoundaries(unittest.TestCase):
    def load_with(self, match_options, left_header="0", right_header="0"):
        directory = Path(self.temporary.name)
        config_path = directory / "config.yaml"
        options = "\n".join(f"  {key}: {value}" for key, value in match_options.items())
        config_path.write_text(
            "left:\n  file: left.csv\n  header_row: " + left_header + "\n  fields:\n    no: id\n    amount: amount\n"
            "right:\n  file: right.csv\n  header_row: " + right_header + "\n  fields:\n    no: id\n    amount: amount\n"
            "match:\n  direction_rule: none\n" + options + "\n"
            "output:\n  path: result.xlsx\n",
            encoding="utf-8",
        )
        return load_config(str(config_path))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temporary.cleanup()

    def test_integer_settings_accept_boundaries(self):
        for options, expected_scale, expected_days in [
            ({"amount_scale": "0", "date_tolerance_days": "0"}, 0, 0),
            ({"amount_scale": "12", "date_tolerance_days": "36500"}, 12, 36500),
            ({"amount_scale": "2", "date_tolerance_days": "30"}, 2, 30),
        ]:
            with self.subTest(options=options):
                cfg = self.load_with(options)
                self.assertEqual(cfg.match.amount_scale, expected_scale)
                self.assertEqual(cfg.match.date_tolerance_days, expected_days)

    def test_header_row_requires_nonnegative_integer(self):
        for value in ("0", "37"):
            with self.subTest(valid=value):
                cfg = self.load_with({}, left_header=value)
                self.assertEqual(cfg.left.header_row, int(value))
        for value in ("1.5", "true", "-1"):
            with self.subTest(invalid=value):
                with self.assertRaisesRegex(ConfigError, "header_row"):
                    self.load_with({}, left_header=value)

    def test_fractional_boolean_negative_and_out_of_range_values_rejected(self):
        invalid = [
            ({"amount_scale": "2.7"}, "amount_scale"),
            ({"amount_scale": "true"}, "amount_scale"),
            ({"amount_scale": "-1"}, "amount_scale"),
            ({"amount_scale": "13"}, "amount_scale"),
            ({"date_tolerance_days": "0.9"}, "date_tolerance_days"),
            ({"date_tolerance_days": "true"}, "date_tolerance_days"),
            ({"date_tolerance_days": "-1"}, "date_tolerance_days"),
            ({"date_tolerance_days": "36501"}, "date_tolerance_days"),
        ]
        for options, name in invalid:
            with self.subTest(options=options):
                with self.assertRaisesRegex(ConfigError, name):
                    self.load_with(options)


if __name__ == "__main__":
    unittest.main()
