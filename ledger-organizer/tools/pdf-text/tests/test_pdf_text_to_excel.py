"""Synthetic searchable-PDF extraction tests; no OCR or business data."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pymupdf
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
        valid = "ID 001234567890123456789 Amount 1,234.56 Balance (88.00) Credit (1,234.56) Scientific 1.23E+05 negative -4.5e-2 Fullwidth １，２３４．５６ Rate １２．５％ signed −45.60"
        self.assertEqual(
            [match.group(0) for match in module.NUMBER.finditer(valid)],
            ["001234567890123456789", "1,234.56", "(88.00)", "(1,234.56)", "1.23E+05", "-4.5e-2", "１，２３４．５６", "１２．５％", "−45.60"],
        )
        malformed = "Code 123ABC Version 1.2.3 ScientificBad 1.2E Group 1,23 Group 1234,567 BadCredit (12,34) BadLongCredit (1234,567) Underscore 12_34 FullwidthBad １，２３"
        self.assertEqual(list(module.NUMBER.finditer(malformed)), [])

    def test_chinese_amount_candidates_preserve_text_and_skip_ordinals(self):
        text = "金额人民币叁佰伍拾元整，欠款三百五十元，金额负壹仟贰佰元整，余额三万零五百，金额人民币1,234.56元整，欠款负100元；第十二项，第一百项，编号〇〇〇二号"
        self.assertEqual(
            [match.group(0) for match in module.NUMBER.finditer(text)],
            ["人民币叁佰伍拾元整", "三百五十元", "负壹仟贰佰元整", "三万零五百", "人民币1,234.56元整", "负100元"],
        )

    def test_pdfium_extracts_real_chinese_cid_font_amount_text(self):
        lines = [
            "金额人民币叁佰伍拾元整",
            "欠款人民币1,234.56元整",
            "第十二项",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = directory / "synthetic-cjk-font.pdf", directory / "review.xlsx"
            document = pymupdf.open()
            page = document.new_page()
            for line_number, line in enumerate(lines):
                page.insert_text(
                    (72, 72 + line_number * 24),
                    line,
                    fontname="china-s",
                    fontsize=12,
                )
            document.save(source)
            document.close()
            before = hashlib.sha256(source.read_bytes()).hexdigest()

            result = module.run(source, output)
            self.assertEqual(result["pages"], 1)
            self.assertEqual(result["number_candidates"], 2)
            self.assertEqual(result["source_sha256"], before)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

            workbook = load_workbook(output, read_only=True, data_only=False)
            try:
                raw = list(workbook["页面原文"].values)
                extracted = "".join(row[4] for row in raw[1:])
                for line in lines:
                    self.assertIn(line, extracted)
                candidates = list(workbook["数字候选"].values)[1:]
                by_text = {row[2]: row for row in candidates}
                expected = ["人民币叁佰伍拾元整", "人民币1,234.56元整"]
                self.assertEqual(set(by_text), set(expected))
                for phrase in expected:
                    self.assertEqual(by_text[phrase][1], extracted.index(phrase))
                    self.assertEqual(by_text[phrase][9], "待人工逐字符核对原页")
                    self.assertIsNotNone(by_text[phrase][4])
            finally:
                workbook.close()

    def test_chinese_amount_candidates_survive_pdf_export_with_offsets_and_review_state(self):
        text = "金额人民币叁佰伍拾元整，欠款人民币1,234.56元整，补记廿七、卅元、卌；第十二项"

        class Searcher:
            def __init__(self, match):
                self.match = match
                self.used = False
            def get_next(self):
                if self.used:
                    return None
                self.used = True
                return self.match
            def close(self):
                pass

        class TextPage:
            def get_text_bounded(self):
                return text
            def search(self, candidate, match_case=True):
                self.assert_match_case = match_case
                start = text.index(candidate)
                return Searcher((start, len(candidate)))
            def get_text_range(self, start, count):
                return text[start:start + count]
            def get_charbox(self, index):
                return (float(index), 0.0, float(index + 1), 1.0)
            def close(self):
                pass

        class Page:
            def get_textpage(self):
                return TextPage()
            def close(self):
                pass

        class Document:
            def __len__(self):
                return 1
            def __getitem__(self, index):
                if index != 0:
                    raise IndexError(index)
                return Page()
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = directory / "synthetic-cjk.pdf", directory / "review.xlsx"
            source.write_bytes(b"%PDF-1.4 synthetic mocked text layer")
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch.object(module.pdfium, "PdfDocument", return_value=Document()):
                result = module.run(source, output)
            self.assertEqual(result["number_candidates"], 5)
            self.assertEqual(result["source_sha256"], before)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            workbook = load_workbook(output, read_only=True, data_only=False)
            try:
                raw = list(workbook["页面原文"].values)
                exported_text = "".join(row[4] for row in raw[1:])
                for phrase in ("人民币叁佰伍拾元整", "人民币1,234.56元整", "第十二项"):
                    self.assertIn(phrase, exported_text)
                rows = list(workbook["数字候选"].values)[1:]
                by_text = {row[2]: row for row in rows}
                expected = ["人民币叁佰伍拾元整", "人民币1,234.56元整", "廿七", "卅元", "卌"]
                self.assertEqual(set(by_text), set(expected))
                for phrase in expected:
                    self.assertEqual(by_text[phrase][1], text.index(phrase))
                    self.assertEqual(by_text[phrase][9], "待人工逐字符核对原页")
                    self.assertIsNotNone(by_text[phrase][4])
            finally:
                workbook.close()

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
            manifest = json.loads(Path(str(output) + ".manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_sha256"], before)
            self.assertEqual(manifest["output_sha256"], module.output_sha256(output))
            self.assertEqual(manifest["number_candidates"], result["number_candidates"])
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

    def test_text_limit_stops_before_numeric_candidate_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "oversized-text.pdf"
            payload = b"BT /F1 12 Tf 72 720 Td (" + b"A" * 50 + b" 123) Tj ET"
            make_pdf(source, [payload])
            with patch.object(module, "MAX_TOTAL_CHARS", 10), patch.object(
                module,
                "_locate_unique_candidate",
                side_effect=AssertionError("oversized page must stop before candidate location"),
            ) as locate:
                with self.assertRaisesRegex(ValueError, "安全处理上限"):
                    module._extract(source)
            locate.assert_not_called()

    def test_no_text_stops_and_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = directory / "scan-only.pdf", directory / "review.xlsx"
            make_pdf(source, [None, None])
            with self.assertRaisesRegex(ValueError, "未发现可提取"):
                module.run(source, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(directory.glob(".ledger-pdf-text-*")), [])
            self.assertFalse(Path(str(output) + ".manifest.json").exists())

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


    def test_manifest_publish_failure_removes_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = directory / "synthetic.pdf", directory / "review.xlsx"
            make_pdf(source, [b"BT /F1 12 Tf 72 720 Td (Amount 12.30) Tj ET"])
            real_link = module.os.link
            calls = []

            def fail_on_manifest(src, dst):
                calls.append(dst)
                if len(calls) == 2:
                    raise OSError("manifest link failure")
                return real_link(src, dst)

            with patch.object(module.os, "link", side_effect=fail_on_manifest):
                with self.assertRaisesRegex(OSError, "manifest link failure"):
                    module.run(source, output)
            self.assertFalse(output.exists())
            self.assertFalse(Path(str(output) + ".manifest.json").exists())
            self.assertEqual(list(directory.glob(".ledger-pdf-text-*")), [])
            self.assertEqual(list(directory.glob(".ledger-pdf-text-manifest-*")), [])

    def test_pdf_size_limit_runs_before_hash_or_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "oversized.pdf"
            output = directory / "review.xlsx"
            make_pdf(source, [b"BT /F1 12 Tf 72 720 Td (Amount 12.30) Tj ET"])
            with patch.object(module, "MAX_PDF_BYTES", 1):
                with patch.object(module, "sha256") as digest:
                    with patch.object(module, "_extract") as extract:
                        with self.assertRaisesRegex(ValueError, "PDF 文件超过"):
                            module.run(source, output)
                        digest.assert_not_called()
                        extract.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(list(directory.glob(".ledger-pdf-text-*")), [])

    def test_pdf_hash_rejects_growth_after_initial_size_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "changed.pdf"
            source.write_bytes(b"two bytes")
            with patch.object(module.os.path, "getsize", return_value=1):
                with self.assertRaisesRegex(ValueError, "读取期间超过"):
                    module.sha256(source, max_bytes=1)

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
