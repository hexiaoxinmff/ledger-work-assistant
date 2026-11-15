"""Regression tests for synthetic real-model numeric measurement reporting."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
OCR_ROOT = HERE.parent
sys.path.insert(0, str(OCR_ROOT))
SPEC = importlib.util.spec_from_file_location(
    "real_model_numeric_eval", OCR_ROOT / "real_model_numeric_eval.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PENDING = MODULE.PENDING


def fake_run(source, result_path, invalid_review=False):
    index = int(Path(result_path).stem.rsplit("-", 1)[1])
    case = MODULE.CASES[index]
    lines = ["1,234.56", "-1"] if case["id"] == "amount-negative" else [case["expected"]]
    if invalid_review and index == 0:
        status = "已确认"
    else:
        status = PENDING
    payload = {"结果": [
        {
            "识别文本": line,
            "复核状态": status,
            "模型分数": 0.99,
            "位置_像素": ([[20, 30], [35, 30], [35, 40], [20, 40]]
                          if line == "-1"
                          else [[40, 30], [80, 30], [80, 40], [40, 40]]),
        } for line in lines
    ]}
    Path(result_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class NumericMeasurement(unittest.TestCase):
    def test_fragmented_negative_is_not_exact_and_all_characters_count_in_cer(self):
        with patch.object(MODULE, "run", side_effect=fake_run):
            report = MODULE.evaluate()
        negative = next(row for row in report["cases"] if row["id"] == "amount-negative")
        joined = "1,234.56-1"
        self.assertEqual(report["exact_matches"], len(MODULE.CASES) - 1)
        self.assertFalse(negative["exact_match"])
        self.assertEqual(negative["recognized_joined_for_cer"], joined)
        self.assertEqual(
            negative["edit_distance"],
            MODULE.edit_distance(negative["expected"], joined),
        )
        self.assertTrue(report["review_required"])
        self.assertFalse(report["accuracy_gate"])
        self.assertEqual(
            negative["recognized_fragments"][0]["bbox_pixels"],
            [[40, 30], [80, 30], [80, 40], [40, 40]],
        )
        self.assertEqual(
            [fragment["ocr_result_index"] for fragment in negative["recognized_fragments"]],
            [1, 2],
        )
        self.assertTrue(all(
            fragment["review_status"] == PENDING
            for fragment in negative["recognized_fragments"]
        ))

    def test_rejects_result_that_lost_pending_review_status(self):
        with patch.object(MODULE, "run", side_effect=lambda s, o: fake_run(s, o, True)):
            with self.assertRaisesRegex(ValueError, "人工复核状态"):
                MODULE.evaluate()

    def test_report_publish_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "report.json"
            destination.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                MODULE._publish_new_file(destination, b"replace")
            self.assertEqual(destination.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
