"""Synthetic OCR grid coordinate validation tests."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("table_grid_coordinate_validation", HERE / "table_grid.py")
grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid)


def make_grid(path):
    image = np.full((200, 300, 3), 255, dtype=np.uint8)
    for x in (20, 150, 280):
        cv2.line(image, (x, 20), (x, 180), (0, 0, 0), 2)
    for y in (20, 100, 180):
        cv2.line(image, (20, y), (280, y), (0, 0, 0), 2)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise AssertionError("synthetic grid encoding failed")
    path.write_bytes(encoded.tobytes())


class OCRCoordinateValidation(unittest.TestCase):
    def test_rejects_malformed_or_out_of_image_boxes_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "grid.png"
            ocr = directory / "ocr.json"
            make_grid(image)
            source_hash = hashlib.sha256(image.read_bytes()).hexdigest()
            invalid_boxes = [
                [[30, 30], [90, 30], [90, 50]],  # not four corners
                [[True, 30], [90, 30], [90, 50], [30, 50]],  # bool is not a coordinate
                [[float("nan"), 30], [90, 30], [90, 50], [30, 50]],
                [[-1, 30], [90, 30], [90, 50], [30, 50]],  # outside image
                [[30, 30], [30, 30], [30, 30], [30, 30]],  # zero area
                [[30], [90, 30], [90, 50], [30, 50]],  # malformed point
                [[10 ** 1000, 30], [90, 30], [90, 50], [30, 50]],  # overflows float
            ]
            for index, box in enumerate(invalid_boxes):
                output = directory / f"bad-{index}.json"
                ocr.write_text(json.dumps({
                    "来源sha256": source_hash,
                    "结果": [{"识别文本": "100.00", "位置_像素": box, "模型分数": 0.99}],
                }, ensure_ascii=False), encoding="utf8")
                with self.subTest(index=index):
                    with self.assertRaises(ValueError):
                        grid.map_table(image, ocr, output)
                    self.assertFalse(output.exists())

            valid_box = [[30, 30], [90, 30], [90, 50], [30, 50]]
            for index, score in enumerate([True, float("inf"), 10 ** 1000]):
                output = directory / f"bad-score-{index}.json"
                ocr.write_text(json.dumps({
                    "来源sha256": source_hash,
                    "结果": [{"识别文本": "100.00", "位置_像素": valid_box, "模型分数": score}],
                }, ensure_ascii=False), encoding="utf8")
                with self.subTest(score_index=index):
                    with self.assertRaises(ValueError):
                        grid.map_table(image, ocr, output)
                    self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
