"""Synthetic tests for conservative ledger amount parsing."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalizer import parse_amount


class AmountParsing(unittest.TestCase):
    def test_valid_grouping_currency_and_fullwidth_digits(self):
        cases = [
            ("1234.56", Decimal("1234.56")),
            ("1,234.56", Decimal("1234.56")),
            ("￥1,234.56", Decimal("1234.56")),
            ("1,234.56¥", Decimal("1234.56")),
            ("１，２３４．５６", Decimal("1234.56")),
            (".5", Decimal("0.50")),
            ("-1,234.00", Decimal("-1234.00")),
            ("0", Decimal("0.00")),
            ("1.230", Decimal("1.23")),\n            ("1e3", Decimal("1000.00")),\n            ("-4.5e-2", Decimal("-0.05")),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse_amount(raw, 2), (expected, None))

    def test_malformed_grouping_and_symbols_are_rejected(self):
        for raw in ("1,23", "12,34.56", "1234,567", "12$34", "$￥10", "1e", "1e+", "1,234e3", "1_000", "(1,000.00)"):
            with self.subTest(raw=raw):
                self.assertEqual(parse_amount(raw, 2), (None, "非法金额"))

    def test_nonzero_precision_beyond_config_is_pending(self):
        for raw in ("1.234", "1.235", "-0.001"):
            with self.subTest(raw=raw):
                self.assertEqual(parse_amount(raw, 2), (None, "金额精度超出配置"))
        self.assertEqual(parse_amount("1.234", 3), (Decimal("1.234"), None))


if __name__ == "__main__":
    unittest.main()
