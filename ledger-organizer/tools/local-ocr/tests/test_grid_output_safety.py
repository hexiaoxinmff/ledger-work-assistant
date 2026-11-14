"""Synthetic output-safety tests for the grid JSON and review workbook."""
import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]


def load_with_fake_vision_modules():
    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.IMREAD_COLOR = 1
    fake_cv2.imdecode = lambda encoded, mode: object()
    fake_numpy = types.ModuleType("numpy")
    fake_numpy.uint8 = object()
    fake_numpy.fromfile = lambda path, dtype=None: object()
    spec = importlib.util.spec_from_file_location("table_grid_under_test", HERE / "table_grid.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"cv2": fake_cv2, "numpy": fake_numpy}):
        spec.loader.exec_module(module)
    return module


GRID = load_with_fake_vision_modules()
SPEC = importlib.util.spec_from_file_location("export_review_under_test", HERE / "export_review.py")
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)
PDF_SPEC=importlib.util.spec_from_file_location("export_pdf_review_under_test",HERE/"export_pdf_review.py")
EXPORT_PDF=importlib.util.module_from_spec(PDF_SPEC)
PDF_SPEC.loader.exec_module(EXPORT_PDF)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class GridOutputSafety(unittest.TestCase):
    def fixtures(self, directory):
        image = directory / "synthetic.png"
        image.write_bytes(b"synthetic image bytes")
        ocr = directory / "synthetic-ocr.json"
        ocr_data = {
            "来源sha256": sha(image),
            "结果": [{
                "识别文本": "00042",
                "位置_像素": [[20, 20], [30, 20], [30, 30], [20, 30]],
                "模型分数": 0.99,
            }, {
                "识别文本": "跨界文字",
                "位置_像素": [[95, 20], [105, 20], [105, 30], [95, 30]],
                "模型分数": 0.61,
            }],
        }
        ocr.write_text(json.dumps(ocr_data, ensure_ascii=False), encoding="utf8")
        grid_json = directory / "grid.json"
        review_xlsx = directory / "review.xlsx"
        return image, ocr, grid_json, review_xlsx

    def map_fake(self, image, ocr, output):
        with mock.patch.object(GRID, "lines", return_value=([10, 100], [10, 100])):
            return GRID.map_table(image, ocr, output)

    def test_grid_json_is_staged_verified_and_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image, ocr, grid_json, _ = self.fixtures(directory)
            self.assertEqual(self.map_fake(image, ocr, grid_json), (1, 1))
            data = json.loads(grid_json.read_text(encoding="utf8"))
            self.assertEqual(data["来源sha256"], sha(image))
            self.assertEqual(data["OCR结果sha256"], sha(ocr))
            self.assertEqual(data["单元格"][0]["识别文本"], "00042")
            self.assertEqual(data["单元格"][0]["复核状态"], "待人工核对原图")
            self.assertEqual(data["OCR识别条数"], 2)
            self.assertEqual(data["单元格"][0]["片段"][0]["OCR结果序号"], 1)
            self.assertEqual(data["单元格"][0]["片段"][0]["模型分数"], 0.99)
            self.assertEqual(data["未归属片段"][0]["OCR结果序号"], 2)
            self.assertEqual(data["未归属片段"][0]["模型分数"], 0.61)
            self.assertEqual(list(directory.glob(".ledger-grid-*")), [])

    def test_invalid_ocr_scores_stop_grid_mapping(self):
        import math
        for score in (None, -0.1, 1.1, "0.9", math.nan, True):
            with self.subTest(score=score), tempfile.TemporaryDirectory() as temporary:
                directory=Path(temporary);image,ocr,output,_=self.fixtures(directory)
                raw=json.loads(ocr.read_text(encoding="utf8"))
                raw["结果"][0]["模型分数"]=score
                ocr.write_text(json.dumps(raw,ensure_ascii=False),encoding="utf8")
                with mock.patch.object(GRID,"lines",return_value=([10,100],[10,100])):
                    with self.assertRaisesRegex(ValueError,"OCR 模型分数无效"):
                        GRID.map_table(image,ocr,output)
                self.assertFalse(output.exists())
                self.assertEqual(list(directory.glob(".ledger-grid-*")),[])

    def test_review_export_rejects_missing_or_duplicate_fragment_indexes(self):
        for corruption in ("missing","duplicate"):
            with self.subTest(corruption=corruption),tempfile.TemporaryDirectory() as temporary:
                directory=Path(temporary);image,ocr,grid_json,output=self.fixtures(directory)
                self.map_fake(image,ocr,grid_json)
                data=json.loads(grid_json.read_text(encoding="utf8"))
                if corruption=="missing":
                    data["单元格"][0]["片段"].clear()
                    data["单元格"][0]["识别文本"]=""
                else:
                    data["未归属片段"][0]["OCR结果序号"]=1
                grid_json.write_text(json.dumps(data,ensure_ascii=False),encoding="utf8")
                with self.assertRaisesRegex(ValueError,"OCR 片段存在缺失、重复或序号不连续"):
                    EXPORT.run(image,grid_json,output)
                self.assertFalse(output.exists())
                self.assertEqual(list(directory.glob(".ledger-grid-review-*")),[])

    def test_multipage_pdf_review_retains_fragment_scores_and_unassigned_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);pages=directory/"pages";pages.mkdir()
            pdf=directory/"synthetic.pdf";pdf.write_bytes(b"synthetic PDF bytes")
            image=pages/"page_0001.png";image.write_bytes(b"synthetic page image")
            image_hash=sha(image)
            ocr=pages/"page_0001_ocr.json"
            ocr_data={"来源sha256":image_hash,"结果":[
                {"识别文本":"00042","位置_像素":[[20,20],[30,20],[30,30],[20,30]],"模型分数":0.99},
                {"识别文本":"跨界文字","位置_像素":[[95,20],[105,20],[105,30],[95,30]],"模型分数":0.61},
            ]}
            ocr.write_text(json.dumps(ocr_data,ensure_ascii=False),encoding="utf8")
            grid_json=pages/"page_0001_grid.json"
            with mock.patch.object(GRID,"lines",return_value=([10,100],[10,100])):
                GRID.map_table(image,ocr,grid_json)
            pdf_hash=sha(pdf)
            (pages/"pages.json").write_text(json.dumps({
                "source_sha256":pdf_hash,"page_count":1,
                "pages":[{"page":1,"image":"page_0001.png","sha256":image_hash}],
            }),encoding="utf8")
            output=directory/"review.xlsx"
            self.assertEqual(EXPORT_PDF.run(pdf,pages,output),(1,1,1))
            from openpyxl import load_workbook
            workbook=load_workbook(output,read_only=True,data_only=False)
            try:
                details=list(workbook["识别片段明细"].values)
                self.assertEqual(details[1][0:7],(1,1,1,1,"已归入网格单元格","00042",0.99))
                self.assertEqual(details[2][0:7],(1,2,None,None,"未归属","跨界文字",0.61))
                missing=list(workbook["未归属片段"].values)
                self.assertEqual(missing[1][0:4],(1,2,"跨界文字",0.61))
                self.assertIn("模型分数只作参考",workbook["来源"]["B5"].value)
            finally:
                workbook.close()
            self.assertEqual(list(directory.glob(".ledger-pdf-review-*")),[])

    def test_multipage_pdf_export_rejects_old_grid_without_fragment_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);pages=directory/"pages";pages.mkdir()
            pdf=directory/"synthetic.pdf";pdf.write_bytes(b"synthetic PDF bytes")
            image=pages/"page_0001.png";image.write_bytes(b"synthetic page image")
            image_hash=sha(image);ocr=pages/"page_0001_ocr.json"
            ocr.write_text(json.dumps({"来源sha256":image_hash,"结果":[]}),encoding="utf8")
            grid=pages/"page_0001_grid.json"
            grid.write_text(json.dumps({
                "来源sha256":image_hash,"OCR结果sha256":sha(ocr),"行数":1,"列数":1,
                "单元格":[{"行":1,"列":1,"识别文本":"","边界_像素":[10,10,100,100],"片段":[]}],
                "未归属片段":[],
            }),encoding="utf8")
            (pages/"pages.json").write_text(json.dumps({
                "source_sha256":sha(pdf),"page_count":1,
                "pages":[{"page":1,"image":"page_0001.png","sha256":image_hash}],
            }),encoding="utf8")
            output=directory/"review.xlsx"
            with self.assertRaisesRegex(ValueError,"缺少 OCR 识别条数"):
                EXPORT_PDF.run(pdf,pages,output)
            self.assertFalse(output.exists())
            self.assertEqual(list(directory.glob(".ledger-pdf-review-*")),[])

    def test_grid_json_failures_never_publish_or_overwrite(self):
        for failure in ("write", "readback", "source changed", "race"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                image, ocr, output, _ = self.fixtures(directory)
                kwargs = {"return_value": ([10, 100], [10, 100])}
                with mock.patch.object(GRID, "lines", **kwargs):
                    if failure == "write":
                        context = mock.patch.object(GRID.json, "dump", side_effect=OSError("synthetic write failure"))
                        expected, exception = "synthetic write failure", OSError
                    elif failure == "readback":
                        context = mock.patch.object(GRID.json, "load", side_effect=ValueError("synthetic readback failure"))
                        expected, exception = "synthetic readback failure", ValueError
                    elif failure == "source changed":
                        real_sha = GRID.sha
                        image_checks = []
                        def changed(path):
                            if Path(path).resolve() == image.resolve():
                                image_checks.append(True)
                                if len(image_checks) == 3:
                                    return "changed"
                            return real_sha(path)
                        context = mock.patch.object(GRID, "sha", side_effect=changed)
                        expected, exception = "输入文件在处理期间发生变化", ValueError
                    else:
                        real_link = GRID.os.link
                        def competing_writer(staged, destination):
                            Path(destination).write_bytes(b"other writer")
                            return real_link(staged, destination)
                        context = mock.patch.object(GRID.os, "link", side_effect=competing_writer)
                        expected, exception = "", FileExistsError
                    with context, self.assertRaisesRegex(exception, expected):
                        GRID.map_table(image, ocr, output)
                if failure == "race":
                    self.assertEqual(output.read_bytes(), b"other writer")
                else:
                    self.assertFalse(output.exists())
                self.assertEqual(list(directory.glob(".ledger-grid-*")), [])

    def test_review_workbook_failure_does_not_publish_or_overwrite(self):
        for failure in ("write", "readback", "source changed", "race"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                image, ocr, grid_json, output = self.fixtures(directory)
                self.map_fake(image, ocr, grid_json)
                if failure == "write":
                    context = mock.patch.object(EXPORT.Workbook, "save", side_effect=OSError("synthetic write failure"))
                    expected, exception = "synthetic write failure", OSError
                elif failure == "readback":
                    context = mock.patch.object(EXPORT, "load_workbook", side_effect=ValueError("synthetic readback failure"))
                    expected, exception = "synthetic readback failure", ValueError
                elif failure == "source changed":
                    real_sha = EXPORT.sha
                    image_checks = []
                    def changed(path):
                        if Path(path).resolve() == image.resolve():
                            image_checks.append(True)
                            if len(image_checks) == 3:
                                return "changed"
                        return real_sha(path)
                    context = mock.patch.object(EXPORT, "sha", side_effect=changed)
                    expected, exception = "源文件在处理期间变化", ValueError
                else:
                    real_link = EXPORT.os.link
                    def competing_writer(staged, destination):
                        Path(destination).write_bytes(b"other writer")
                        return real_link(staged, destination)
                    context = mock.patch.object(EXPORT.os, "link", side_effect=competing_writer)
                    expected, exception = "", FileExistsError
                with context, self.assertRaisesRegex(exception, expected):
                    EXPORT.run(image, grid_json, output)
                if failure == "race":
                    self.assertEqual(output.read_bytes(), b"other writer")
                else:
                    self.assertFalse(output.exists())
                self.assertEqual(list(directory.glob(".ledger-grid-review-*")), [])

    def test_review_workbook_success_and_existing_output(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image, ocr, grid_json, output = self.fixtures(directory)
            self.map_fake(image, ocr, grid_json)
            self.assertEqual(EXPORT.run(image, grid_json, output), (1, 1))
            workbook = load_workbook(output, read_only=True, data_only=False)
            try:
                self.assertEqual(workbook["待核对表格"]["A1"].value, "00042")
                self.assertEqual(workbook["待核对表格"]["A1"].data_type, "s")
                self.assertEqual(workbook["逐格复核"]["E2"].value, "待人工核对原图")
                details=list(workbook["识别片段明细"].values)
                self.assertEqual(details[1][0:6], (1,1,1,"已归入网格单元格","00042",0.99))
                self.assertEqual(details[2][0:6], (2,None,None,"未归属","跨界文字",0.61))
                self.assertEqual(workbook["未归属片段"]["A2"].value, 2)
                self.assertEqual(workbook["未归属片段"]["C2"].value, 0.61)
                self.assertIn("模型分数只作参考",workbook["说明"]["B6"].value)
            finally:
                workbook.close()
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                EXPORT.run(image, grid_json, output)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(list(directory.glob(".ledger-grid-review-*")), [])


if __name__ == "__main__":
    unittest.main()
