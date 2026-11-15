"""Synthetic output-safety tests for the grid JSON and review workbook."""
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def load_with_fake_vision_modules():
    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.IMREAD_COLOR = 1
    fake_cv2.imdecode = lambda encoded, mode: types.SimpleNamespace(shape=(200, 300, 3))
    fake_numpy = types.ModuleType("numpy")
    fake_numpy.uint8 = object()
    fake_numpy.fromfile = lambda path, dtype=None: object()
    fake_numpy.frombuffer = lambda buffer, dtype=None: object()
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
    def png_header(self, width=300, height=200):
        kind = b"IHDR"
        payload = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    def fixtures(self, directory):
        image = directory / "synthetic.png"
        image.write_bytes(self.png_header())
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

    def test_split_negative_fragments_remain_separate_in_pending_review(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image, ocr, grid_json, review_xlsx = self.fixtures(directory)
            ocr.write_text(json.dumps({
                "来源sha256": sha(image),
                "识别条数": 2,
                "识别状态": "已检出文字候选",
                "结果": [
                    {
                        "识别文本": "1,234.56",
                        "位置_像素": [[40, 30], [80, 30], [80, 40], [40, 40]],
                        "模型分数": 0.9,
                        "复核状态": "待人工核对原图",
                    },
                    {
                        "识别文本": "-1",
                        "位置_像素": [[20, 30], [35, 30], [35, 40], [20, 40]],
                        "模型分数": 0.8,
                        "复核状态": "待人工核对原图",
                    },
                ],
            }, ensure_ascii=False), encoding="utf8")

            self.assertEqual(self.map_fake(image, ocr, grid_json), (1, 0))
            mapped = json.loads(grid_json.read_text(encoding="utf8"))
            cell = mapped["单元格"][0]
            self.assertEqual(cell["识别文本"], "-1 1,234.56")
            self.assertEqual([fragment["OCR结果序号"] for fragment in cell["片段"]], [2, 1])
            self.assertEqual(
                [fragment["识别文本"] for fragment in cell["片段"]],
                ["-1", "1,234.56"],
            )
            self.assertTrue(all(
                fragment["复核状态"] == "待人工核对原图" for fragment in cell["片段"]
            ))

            self.assertEqual(EXPORT.run(image, grid_json, review_xlsx), (1, 0))
            workbook = load_workbook(review_xlsx, read_only=True, data_only=False)
            try:
                self.assertEqual(workbook["待核对表格"]["A1"].value, "-1 1,234.56")
                self.assertEqual(workbook["逐格复核"]["C2"].value, "-1 1,234.56")
                self.assertEqual(workbook["逐格复核"]["E2"].value, "待人工核对原图")
                details = list(workbook["识别片段明细"].values)[1:]
                self.assertEqual([row[0] for row in details], [1, 2])
                self.assertEqual([row[4] for row in details], ["1,234.56", "-1"])
                self.assertTrue(all(row[7] == "待人工核对原图" for row in details))
            finally:
                workbook.close()

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

    def test_grid_image_and_json_limits_run_before_decode(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "oversized.png"
            image.write_bytes(self.png_header(5001, 5000))
            ocr = directory / "ocr.json"
            ocr.write_text(json.dumps({
                "来源sha256": sha(image), "结果": [],
            }, ensure_ascii=False), encoding="utf8")
            output = directory / "grid.json"
            with mock.patch.object(GRID.cv2, "imdecode") as decode:
                with self.assertRaisesRegex(ValueError, "2500 万像素"):
                    GRID.map_table(image, ocr, output)
                decode.assert_not_called()
            self.assertFalse(output.exists())

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image, ocr, output, _ = self.fixtures(directory)
            with mock.patch.object(GRID, "MAX_OCR_JSON_BYTES", 1), mock.patch.object(GRID.cv2, "imdecode") as decode:
                with self.assertRaisesRegex(ValueError, "OCR JSON"):
                    GRID.map_table(image, ocr, output)
                decode.assert_not_called()
            self.assertFalse(output.exists())

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image, ocr, output, _ = self.fixtures(directory)
            with mock.patch.object(GRID, "MAX_OCR_RESULTS", 1), mock.patch.object(GRID.cv2, "imdecode") as decode:
                with self.assertRaisesRegex(ValueError, "10 万条"):
                    GRID.map_table(image, ocr, output)
                decode.assert_not_called()
            self.assertFalse(output.exists())

    def test_bounded_json_read_handles_size_change_after_stat(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image, ocr, output, _ = self.fixtures(directory)
            original_stat = Path.stat

            def report_stale_small_size(path, *args, **kwargs):
                if Path(path) == ocr:
                    return types.SimpleNamespace(st_size=1)
                return original_stat(path, *args, **kwargs)

            with mock.patch.object(GRID, "MAX_OCR_JSON_BYTES", 8):
                with mock.patch.object(GRID.Path, "stat", new=report_stale_small_size):
                    with mock.patch.object(GRID.cv2, "imdecode") as decode:
                        with self.assertRaisesRegex(ValueError, "OCR JSON"):
                            GRID.map_table(image, ocr, output)
                        decode.assert_not_called()
            self.assertFalse(output.exists())

    def test_decoded_image_dimensions_must_match_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image, ocr, output, _ = self.fixtures(directory)
            fake_image = types.SimpleNamespace(shape=(201, 300, 3))
            with mock.patch.object(GRID.cv2, "imdecode", return_value=fake_image):
                with mock.patch.object(GRID, "lines") as find_lines:
                    with self.assertRaisesRegex(ValueError, "头尺寸与解码尺寸不一致"):
                        GRID.map_table(image, ocr, output)
                    find_lines.assert_not_called()
            self.assertFalse(output.exists())

    def test_no_detection_status_survives_grid_and_single_image_review(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);image=directory/"blank-table.png";image.write_bytes(self.png_header())
            ocr=directory/"no-detections.json"
            status="未检出文字候选；不能据此判断原图空白，需人工查看"
            ocr.write_text(json.dumps({
                "来源sha256":sha(image),"识别状态":status,"识别条数":0,"结果":[],
            },ensure_ascii=False),encoding="utf8")
            grid_json=directory/"grid.json";review=directory/"review.xlsx"
            self.map_fake(image,ocr,grid_json)
            grid_data=json.loads(grid_json.read_text(encoding="utf8"))
            self.assertEqual(grid_data["OCR识别条数"],0)
            self.assertEqual(grid_data["OCR识别状态"],status)
            EXPORT.run(image,grid_json,review)
            workbook=load_workbook(review,read_only=True,data_only=False)
            try:
                self.assertEqual(workbook["说明"]["B7"].value,status)
                self.assertIsNone(workbook["待核对表格"]["A1"].value)
                self.assertEqual(workbook["逐格复核"]["E2"].value,"待人工核对原图")
            finally:
                workbook.close()

    def test_invalid_ocr_scores_stop_grid_mapping(self):
        import math
        for score in (None, -0.1, 1.1, "0.9", math.nan, True, 10 ** 1000):
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

    def test_invalid_ocr_coordinate_boxes_stop_before_grid_publication(self):
        import math
        invalid_boxes = [
            [[20, 20], [30, 20], [30, 30]],  # not four corners
            [[True, 20], [30, 20], [30, 30], [20, 30]],  # bool is not numeric evidence
            [[math.nan, 20], [30, 20], [30, 30], [20, 30]],
            [[-1, 20], [30, 20], [30, 30], [20, 30]],  # outside the image
            [[20, 20], [20, 20], [20, 20], [20, 20]],  # zero area
            [[20], [30, 20], [30, 30], [20, 30]],  # malformed point
            [[10 ** 1000, 20], [30, 20], [30, 30], [20, 30]],  # float overflow
        ]
        for index, box in enumerate(invalid_boxes):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                image, ocr, output, _ = self.fixtures(directory)
                raw = json.loads(ocr.read_text(encoding="utf8"))
                raw["结果"][0]["位置_像素"] = box
                ocr.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf8")
                with mock.patch.object(GRID, "lines", return_value=([10, 100], [10, 100])):
                    with self.assertRaises(ValueError):
                        GRID.map_table(image, ocr, output)
                self.assertFalse(output.exists())
                self.assertEqual(list(directory.glob(".ledger-grid-*")), [])

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
            image=pages/"page_0001.png";image.write_bytes(self.png_header())
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
                self.assertIn("不能据此判断原图空白",workbook["来源"]["B9"].value)
            finally:
                workbook.close()
            self.assertEqual(list(directory.glob(".ledger-pdf-review-*")),[])

    def test_multipage_pdf_export_rejects_old_grid_without_fragment_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);pages=directory/"pages";pages.mkdir()
            pdf=directory/"synthetic.pdf";pdf.write_bytes(b"synthetic PDF bytes")
            image=pages/"page_0001.png";image.write_bytes(self.png_header())
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
                        def changed(path, *limits):
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


class CollectorProvenanceRegression(unittest.TestCase):
    def test_collect_review_provenance_suite(self):
        import test_collect_review
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(
            test_collect_review.CollectReviewProvenance
        )
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        self.assertTrue(result.wasSuccessful(), "collector provenance regressions failed")


if __name__ == "__main__":
    unittest.main()
