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


def fake_run(source, result_path, invalid_review=False, fragmented_exact=False):
    index = int(Path(result_path).stem.rsplit("-", 1)[1])
    case = MODULE.CASES[index]
    if case["id"] == "amount-negative" and fragmented_exact:
        lines = ["-", "1,234.56"]
    elif case["id"] == "amount-negative":
        lines = ["1,234.56", "-1"]
    else:
        lines = [case["expected"]]
    if invalid_review and index == 0:
        status = "已确认"
    else:
        status = PENDING
    payload = {"结果": [
        {
            "识别文本": line,
            "复核状态": status,
            "模型分数": 0.99,
            "位置_像素": ([[20, 30], [55, 30], [55, 40], [20, 40]]
                          if line in ("-1", "-")
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

    def test_multiple_overlapping_boxes_never_count_as_single_box_exact(self):
        with patch.object(
            MODULE, "run",
            side_effect=lambda source, result_path: fake_run(
                source, result_path, fragmented_exact=True
            ),
        ):
            report = MODULE.evaluate()
        negative = next(row for row in report["cases"] if row["id"] == "amount-negative")
        self.assertEqual(negative["recognized_joined_for_cer"], negative["expected"])
        self.assertEqual(negative["fragment_count"], 2)
        self.assertFalse(negative["exact_match"])
        self.assertEqual(report["multi_box_case_count"], 1)
        self.assertEqual(len(negative["axis_aligned_bbox_overlaps"]), 1)
        overlap = negative["axis_aligned_bbox_overlaps"][0]
        self.assertEqual(overlap["intersection_envelope_pixels"], [40, 30, 55, 40])
        self.assertTrue(all(fragment["review_status"] == PENDING for fragment in negative["recognized_fragments"]))

    def test_rejects_result_that_lost_pending_review_status(self):
        with patch.object(MODULE, "run", side_effect=lambda s, o: fake_run(s, o, True)):
            with self.assertRaisesRegex(ValueError, "人工复核状态"):
                MODULE.evaluate()

    def test_image_variation_generators_apply_declared_transforms(self):
        from PIL import Image
        jpeg_case = next(case for case in MODULE.CASES if case["id"] == "negative-jpeg-q40")
        small_case = next(case for case in MODULE.CASES if case["id"] == "negative-downsample-half")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            jpeg = directory / "synthetic.jpg"
            small = directory / "synthetic.png"
            MODULE._draw_case(jpeg_case, jpeg)
            MODULE._draw_case(small_case, small)
            with Image.open(jpeg) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.width, 1600)
            with Image.open(small) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (800, 210))

    def test_case_ids_are_unique_and_baseline_variations_are_separate(self):
        ids = [case["id"] for case in MODULE.CASES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sum(case["suite"] == "baseline" for case in MODULE.CASES), 8)
        self.assertGreaterEqual(sum(case["suite"] == "image-variation" for case in MODULE.CASES), 5)
        self.assertEqual(sum(case["suite"] == "preprocess" for case in MODULE.CASES), 6)

    def test_preprocessing_variants_use_distinct_images_and_preserve_synthetic_source(self):
        with patch.object(MODULE, "run", side_effect=fake_run):
            report = MODULE.evaluate()
        rows = [row for row in report["cases"] if row["suite"] == "preprocess"]
        self.assertEqual(len(rows), 6)
        for base in ("negative-low-contrast", "negative-jpeg-q40"):
            group = [row for row in rows if row["preprocess_base_case"] == base]
            self.assertEqual(
                {row["preprocessing_variant"] for row in group},
                {"original", "autocontrast", "threshold-198"},
            )
            self.assertEqual(len({row["original_source_sha256"] for row in group}), 1)
            self.assertTrue(all(row["source_unchanged"] for row in group))
            original = next(row for row in group if row["preprocessing_variant"] == "original")
            self.assertEqual(original["ocr_input_sha256"], original["original_source_sha256"])
            for row in group:
                self.assertTrue(row["review_required"])
                self.assertTrue(all(
                    fragment["review_status"] == PENDING
                    for fragment in row["recognized_fragments"]
                ))
    def test_report_publish_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "report.json"
            destination.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                MODULE._publish_new_file(destination, b"replace")
            self.assertEqual(destination.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
