"""Synthetic DOCX tests for Chinese-number review candidate coverage."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

from openpyxl import load_workbook

SCRIPT = Path(__file__).resolve().parents[1] / "docx_tables.py"
spec = importlib.util.spec_from_file_location("docx_tables", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(path, values):
    rows = "".join(
        "<w:tr><w:tc><w:p><w:r><w:t>" + value + "</w:t></w:r></w:p></w:tc></w:tr>"
        for value in values
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body><w:tbl>{rows}</w:tbl></w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)


class ChineseNumberCandidates(unittest.TestCase):
    def test_standalone_chinese_units_reach_review_sheet_without_rewriting(self):
        values = ["十元", "拾元", "百元", "佰元", "十", "十二元", "廿元", "卅元", "卌元", "廿七", "卅", "商户A"]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = directory / "fictional.docx", directory / "review.xlsx"
            make_docx(source, values)
            before = hashlib.sha256(source.read_bytes()).hexdigest()

            extracted_count = module.run(source, output)
            self.assertEqual(extracted_count, len(values))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

            workbook = load_workbook(output, read_only=True, data_only=False)
            try:
                original = list(workbook["表格单元格"].values)[1:]
                self.assertEqual([row[3] for row in original], values)
                candidates = list(workbook["数字复核"].values)[1:]
                self.assertEqual([row[3] for row in candidates], values[:-1])
                self.assertTrue(all(row[4] == "待人工复核" for row in candidates))
                self.assertTrue(all(cell.data_type != "f" for row in workbook["数字复核"].iter_rows() for cell in row))
            finally:
                workbook.close()

    def test_non_numeric_chinese_text_is_not_added(self):
        self.assertFalse(module.contains_number("商户资料"))
        self.assertTrue(module.contains_number("十元"))
        self.assertTrue(module.contains_number("拾元"))
        self.assertTrue(module.contains_number("百元"))
        self.assertTrue(module.contains_number("佰元"))
        self.assertTrue(module.contains_number("廿元"))
        self.assertTrue(module.contains_number("卅元"))
        self.assertTrue(module.contains_number("卌元"))
        self.assertTrue(module.contains_number("廿七"))
        self.assertTrue(module.contains_number("卅"))
        self.assertFalse(module.contains_number("商户资料"))


if __name__ == "__main__":
    unittest.main()
