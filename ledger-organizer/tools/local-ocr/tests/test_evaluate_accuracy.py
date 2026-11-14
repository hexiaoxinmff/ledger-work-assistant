"""Synthetic unit tests for OCR numeric-field scoring and review-state invariants."""
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("evaluate_accuracy", HERE / "evaluate_accuracy.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PENDING = "待人工核对原图"


class EvaluateAccuracy(unittest.TestCase):
    def test_exact_fields_cer_and_extra_lines_are_reported(self):
        expected = {"cases": [
            {"id": "amount-comma", "field_type": "amount", "expected": "1,234.56", "result_index": 0},
            {"id": "amount-negative", "field_type": "amount", "expected": "(88.00)", "result_index": 1},
            {"id": "identifier-zero-prefix", "field_type": "identifier", "expected": "00042", "result_index": 2},
        ]}
        actual = {"来源sha256": "a" * 64, "结果": [
            {"识别文本": "1.23456", "复核状态": PENDING},
            {"识别文本": "(86.00)", "复核状态": PENDING},
            {"识别文本": "00042", "复核状态": PENDING},
            {"识别文本": "unmapped", "复核状态": PENDING},
        ]}

        report = MODULE.evaluate(expected, actual)
        self.assertEqual(report["exact_matches"], 1)
        self.assertEqual(report["case_count"], 3)
        self.assertAlmostEqual(report["exact_match_rate"], 1 / 3)
        self.assertEqual(report["edit_distance"], 3)
        self.assertAlmostEqual(report["character_error_rate"], 3 / 20)
        self.assertEqual(report["unmapped_ocr_result_count"], 1)
        self.assertEqual(report["by_field_type"]["amount"]["exact_matches"], 0)
        self.assertEqual(report["by_field_type"]["identifier"]["exact_matches"], 1)
        self.assertTrue(report["review_required"])
        self.assertTrue(all(row["review_status"] == PENDING for row in report["cases"]))

    def test_missing_ocr_line_counts_as_a_mismatch(self):
        report = MODULE.evaluate(
            {"cases": [{"id": "date-1", "field_type": "date", "expected": "2026-11-14", "result_index": 0}]},
            {"结果": []},
        )
        self.assertEqual(report["cases"][0]["recognized"], "")
        self.assertFalse(report["cases"][0]["exact_match"])
        self.assertEqual(report["edit_distance"], len("2026-11-14"))
        self.assertEqual(report["unmapped_ocr_result_count"], 0)
        self.assertTrue(report["review_required"])

    def test_does_not_normalize_punctuation_or_whitespace(self):
        report = MODULE.evaluate(
            {"cases": [{"id": "amount-1", "field_type": "amount", "expected": "1,234.56", "result_index": 0}]},
            {"结果": [{"识别文本": "1,234.56 ", "复核状态": PENDING}]},
        )
        self.assertFalse(report["cases"][0]["exact_match"])
        self.assertEqual(report["edit_distance"], 1)

    def test_rejects_non_pending_ocr_status(self):
        with self.assertRaisesRegex(ValueError, "必须保留待人工复核状态"):
            MODULE.evaluate(
                {"cases": [{"id": "text-1", "field_type": "text", "expected": "abc", "result_index": 0}]},
                {"结果": [{"识别文本": "abc", "复核状态": "已确认"}]},
            )

    def test_rejects_unmapped_rows_that_lost_review_status(self):
        with self.assertRaisesRegex(ValueError, "所有 OCR 结果"):
            MODULE.evaluate(
                {"cases": [{"id": "text-1", "field_type": "text", "expected": "abc", "result_index": 0}]},
                {"结果": [
                    {"识别文本": "abc", "复核状态": PENDING},
                    {"识别文本": "extra", "复核状态": "已确认"},
                ]},
            )

    def test_rejects_duplicate_case_ids_and_result_indexes(self):
        base = {"id": "x", "field_type": "text", "expected": "x", "result_index": 0}
        with self.assertRaisesRegex(ValueError, "唯一"):
            MODULE.evaluate({"cases": [base, dict(base)]}, {"结果": []})
        with self.assertRaisesRegex(ValueError, "唯一"):
            MODULE.evaluate(
                {"cases": [base, {"id": "y", "field_type": "text", "expected": "y", "result_index": 0}]},
                {"结果": []},
            )


if __name__ == "__main__":
    unittest.main()
