"""Synthetic end-to-end tests for collecting OCR review with fragment provenance."""
import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parents[1]


def load_grid():
    cv2 = types.ModuleType("cv2")
    cv2.IMREAD_COLOR = 1
    cv2.imdecode = lambda *_: object()
    numpy = types.ModuleType("numpy")
    numpy.uint8 = object()
    numpy.fromfile = lambda *_args, **_kwargs: object()
    spec = importlib.util.spec_from_file_location("collect_test_grid", HERE / "table_grid.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"cv2": cv2, "numpy": numpy}):
        spec.loader.exec_module(module)
    return module


GRID = load_grid()


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PDF_REVIEW = load_module("collect_test_pdf_review", "export_pdf_review.py")
COLLECT = load_module("collect_test_collector", "collect_review.py")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CollectReviewProvenance(unittest.TestCase):
    def prepare(self, directory):
        pages = directory / "pages"
        pages.mkdir()
        pdf = directory / "source.pdf"
        pdf.write_bytes(b"synthetic PDF")
        image = pages / "page_0001.png"
        image.write_bytes(b"synthetic page image")
        image_hash = sha(image)
        ocr = pages / "page_0001_ocr.json"
        ocr.write_text(json.dumps({
            "来源sha256": image_hash,
            "结果": [{
                "识别文本": "00042",
                "位置_像素": [[20, 20], [30, 20], [30, 30], [20, 30]],
                "模型分数": 0.99,
            }],
        }, ensure_ascii=False), encoding="utf8")
        grid = pages / "page_0001_grid.json"
        with mock.patch.object(GRID, "lines", return_value=([10, 100], [10, 100])):
            GRID.map_table(image, ocr, grid)
        (pages / "pages.json").write_text(json.dumps({
            "source_sha256": sha(pdf),
            "page_count": 1,
            "pages": [{"page": 1, "image": image.name, "sha256": image_hash}],
        }), encoding="utf8")
        review = directory / "review.xlsx"
        self.assertEqual(PDF_REVIEW.run(pdf, pages, review), (1, 1, 0))
        workbook = load_workbook(review)
        workbook["逐格复核"]["G2"] = "原文一致"
        workbook.save(review)
        workbook.close()
        return pdf, pages, review

    def test_review_collection_preserves_fragment_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            pdf, pages, review = self.prepare(directory)
            output = directory / "collected.xlsx"
            self.assertEqual(COLLECT.run(pdf, pages, review, output), (1, 0))
            workbook = load_workbook(output, read_only=True, data_only=False)
            try:
                rows = list(workbook["OCR片段来源"].values)
                self.assertEqual(rows[1], (
                    1, 1, 1, 1, "已归入网格单元格", "00042", 0.99,
                    "[[20, 20], [30, 20], [30, 30], [20, 30]]", "待人工核对原PDF",
                ))
                self.assertEqual(workbook["说明"]["B6"].value, 1)
                self.assertEqual(workbook["复核记录"]["D2"].value, "00042")
                self.assertEqual(workbook["复核记录"]["F2"].value, "00042")
            finally:
                workbook.close()

    def test_collector_rejects_changed_fragment_details_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            pdf, pages, review = self.prepare(directory)
            workbook = load_workbook(review)
            workbook["识别片段明细"]["F2"] = "tampered"
            workbook.save(review)
            workbook.close()
            output = directory / "collected.xlsx"
            with self.assertRaisesRegex(ValueError, "OCR 片段或来源发生改变"):
                COLLECT.run(pdf, pages, review, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(directory.glob(".ledger-review-*")), [])

    def test_collector_requires_unassigned_fragments_to_be_resolved_upstream(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            pdf, pages, review = self.prepare(directory)
            grid = pages / "page_0001_grid.json"
            data = json.loads(grid.read_text(encoding="utf8"))
            data["未归属片段"] = [{
                "OCR结果序号": 2,
                "识别文本": "unknown",
                "位置_像素": [[110, 20], [120, 20], [120, 30], [110, 30]],
                "模型分数": 0.5,
                "复核状态": "待人工核对原图",
            }]
            data["OCR识别条数"] = 2
            grid.write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")
            output = directory / "collected.xlsx"
            with self.assertRaisesRegex(ValueError, "未归属片段"):
                COLLECT.run(pdf, pages, review, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
