"""Synthetic searchable-PDF extraction tests; no OCR or business data."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import load_workbook

SCRIPT = Path(__file__).resolve().parents[2] / "document-to-excel" / "pdf_text_to_excel.py"
spec = importlib.util.spec_from_file_location("pdf_text_to_excel", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_pdf(path, page_streams):
    """Create a tiny ASCII PDF with one Helvetica text page and optional blank pages."""
    count = len(page_streams)
    bodies = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: ("<< /Type /Pages /Kids [" + " ".join(f"{index} 0 R" for index in range(3, 3 + count)) + f"] /Count {count} >>").encode(),
    }
    font_id = 3 + count
    next_content_id = font_id + 1
    for index, stream in enumerate(page_streams):
        page_id = 3 + index
        if stream is None:
            bodies[page_id] = f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> >>".encode()
        else:
            content_id = next_content_id
            next_content_id += 1
            bodies[page_id] = f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode()
            bodies[content_id] = f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
    bodies[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects = [bodies[index] for index in range(1, max(bodies) + 1)]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{object_number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_offset = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode())
    path.write_bytes(data)


class PdfTextToExcel(unittest.TestCase):
    def test_pdf_line_endings_are_normalized_before_excel_export(self):
        self.assertEqual(
            module._normalize_line_endings("first\r\nsecond\rthird\nfourth"),
            "first\nsecond\nthird\nfourth",
        )

    def test_number_candidates_require_complete_token_boundaries(self):
        valid = "ID 001234567890123456789 Amount 1,234.56 Balance (88.00) Rate 12% signed −45.60"
        self.assertEqual(
            [match.group(0) for match in module.NUMBER.finditer(valid)],
            ["001234567890123456789", "1,234.56", "(88.00)", "12%", "−45.60"],
        )
        malformed = "Code 123ABC Version 1.2.3 Group 1,23 Group 1234,567 Underscore 12_34"
        self.assertEqual(list(module.NUMBER.finditer(malformed)), [])

    def test_uncertain_text_search_never_emits_coordinates(self):
        class Searcher:
            def __init__(self, matches):
                self.matches = iter(matches)
            def get_next(self):
                return next(self.matches, None)
            def close(self):
                pass

        class MismatchedPage:
            def search(self, *_args, **_kwargs):
                return Searcher([(10, 4)])
            def get_text_range(self, *_args):
                return "9999"
            def get_charbox(self, _index):
                raise AssertionError("mismatched text must not request boxes")

        class BrokenBoxPage(MismatchedPage):
            def get_text_range(self, *_args):
                return "1234"
            def get_charbox(self, _index):
                raise IndexError("synthetic PDFium index mismatch")

        box, status = module._locate_unique_candidate(MismatchedPage(), "1234")
        self.assertIsNone(box)
        self.assertIn("不一致", status)
        box, status = module._locate_unique_candidate(BrokenBoxPage(), "1234")
        self.assertIsNone(box)
        self.assertIn("异常", status)

    def test_cli_emits_report_and_creates_review_workbook(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = directory / "synthetic.pdf", directory / "review.xlsx"
            make_pdf(source, [b"BT /F1 12 Tf 72 720 Td (ID 00042 Amount 12.30) Tj ET"])
            result = subprocess.run([sys.executable, str(SCRIPT), str(source), str(output)], capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["pages"], 1)
            self.assertEqual(report["pages_with_text"], 1)
            self.assertTrue(output.is_file())

    def test_text_layer_numeric_candidates_provenance_and_formula_safety(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = directory / "synthetic.pdf", directory / "review.xlsx"
            text = b"BT /F1 12 Tf 72 720 Td (ID 001234567890123456789 Amount 1,234.56 Balance \\(88.00\\) Zero 0.00 Repeat 0.00 Formula =1+1) Tj ET"
            make_pdf(source, [text, None])
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            result = module.run(source, output)
            self.assertEqual(result["pages"], 2)
            self.assertEqual(result["pages_with_text"], 1)
            self.assertEqual(result["source_sha256"], before)
            self.assertTrue(output.is_file())
            self.assertEqual(list(directory.glob(".ledger-pdf-text-*")), [])

            workbook = load_workbook(output, read_only=True, data_only=False)
            try:
                page_status = list(workbook["页码状态"].values)
                self.assertEqual(page_status[1][0:3], (1, page_status[1][1], "已提取文字层"))
                self.assertEqual(page_status[2][0:3], (2, 0, "未发现文字层"))
                raw = list(workbook["页面原文"].values)
                original = "".join(row[4] for row in raw[1:])
                for value in ("001234567890123456789", "1,234.56", "(88.00)", "0.00", "=1+1"):
                    self.assertIn(value, original)
                candidate_rows = list(workbook["数字候选"].values)
                candidates = [row[2] for row in candidate_rows[1:]]
                self.assertIn("001234567890123456789", candidates)
                self.assertIn("1,234.56", candidates)
                self.assertIn("(88.00)", candidates)
                self.assertIn("0.00", candidates)
                for row in workbook["数字候选"].iter_rows(min_row=2):
                    self.assertEqual(row[2].data_type, "s")
                    self.assertEqual(row[9].value, "待人工逐字符核对原页")
                unique_amount = next(row for row in candidate_rows[1:] if row[2] == "1,234.56")
                self.assertEqual(unique_amount[8], "已唯一定位（仅供原页定位）")
                self.assertIsNotNone(unique_amount[4])
                self.assertLess(unique_amount[4], unique_amount[6])
                repeated_zeroes = [row for row in candidate_rows[1:] if row[2] == "0.00"]
                self.assertEqual(len(repeated_zeroes), 2)
                self.assertTrue(all(row[4:8] == (None, None, None, None) for row in repeated_zeroes))
                self.assertTrue(all(row[8] == "同值在本页多处出现，未定位" for row in repeated_zeroes))
                self.assertFalse(any(cell.data_type == "f" for row in workbook["页面原文"].iter_rows() for cell in row))
            finally:
                workbook.close()
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_no_text_stops_and_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = directory / "scan-only.pdf", directory / "review.xlsx"
            make_pdf(source, [None, None])
            with self.assertRaisesRegex(ValueError, "未发现可提取"):
                module.run(source, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(directory.glob(".ledger-pdf-text-*")), [])

    def test_long_page_is_chunked_without_losing_offsets_or_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = directory / "long-page.pdf", directory / "review.xlsx"
            line = "A" * 500
            content = "BT /F1 1 Tf 1 780 Td " + " ".join(f"({line}) Tj 0 -10 Td" for _ in range(60)) + " (Amount 123.45) Tj ET"
            make_pdf(source, [content.encode("ascii")])
            extracted = module._extract(source)[0]["text"]
            self.assertGreater(len(extracted), module.TEXT_CHUNK)
            module.run(source, output)

            workbook = load_workbook(output, read_only=True, data_only=False)
            try:
                rows = list(workbook["页面原文"].values)[1:]
                self.assertGreater(len(rows), 1)
                self.assertEqual("".join(row[4] for row in rows), extracted)
                self.assertEqual(rows[0][2], 0)
                for previous, current in zip(rows, rows[1:]):
                    self.assertEqual(previous[3], current[2])
                self.assertEqual(rows[-1][3], len(extracted))
                self.assertTrue(all(len(row[4]) <= module.TEXT_CHUNK for row in rows))
                numbers = list(workbook["数字候选"].values)[1:]
                self.assertEqual(numbers[-1][2], "123.45")
                self.assertEqual(numbers[-1][1], extracted.index("123.45"))
            finally:
                workbook.close()

    def test_existing_output_source_change_and_readback_failure_are_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "synthetic.pdf"
            make_pdf(source, [b"BT /F1 12 Tf 72 720 Td (Amount 12.30) Tj ET"])
            existing = directory / "existing.xlsx"
            existing.write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                module.run(source, existing)
            self.assertEqual(existing.read_bytes(), b"keep")

            changed_output = directory / "changed.xlsx"
            real_hash = module.sha256(source)
            with patch.object(module, "sha256", side_effect=[real_hash, "changed"]):
                with self.assertRaisesRegex(ValueError, "源文件发生变化"):
                    module.run(source, changed_output)
            self.assertFalse(changed_output.exists())
            self.assertEqual(list(directory.glob(".ledger-pdf-text-*")), [])

            readback_output = directory / "readback.xlsx"
            with patch.object(module, "_verify_workbook", side_effect=ValueError("模拟回读失败")):
                with self.assertRaisesRegex(ValueError, "模拟回读失败"):
                    module.run(source, readback_output)
            self.assertFalse(readback_output.exists())
            self.assertEqual(list(directory.glob(".ledger-pdf-text-*")), [])


if __name__ == "__main__":
    unittest.main()
