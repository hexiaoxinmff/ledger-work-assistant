"""Regression tests for DOCX special inline content preservation."""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "docx_tables.py"
SPEC = importlib.util.spec_from_file_location("docx_tables", SCRIPT)
DOCX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCX)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def make_docx(run_content):
    document = (
        f'<w:document xmlns:w="{W}" xmlns:mc="{MC}"><w:body><w:tbl>'
        f'<w:tr><w:tc><w:p>{run_content}</w:p></w:tc></w:tr>'
        f'</w:tbl><w:sectPr/></w:body></w:document>'
    )
    temp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    temp.close()
    with zipfile.ZipFile(temp.name, "w") as archive:
        archive.writestr("word/document.xml", document)
    return Path(temp.name)


class DocxSpecialTextTests(unittest.TestCase):
    def test_plain_text_is_preserved(self):
        path = make_docx('<w:r><w:t>编号001234</w:t></w:r>')
        try:
            self.assertEqual(DOCX.extract(path), [(1, 1, 1, "编号001234")])
        finally:
            path.unlink()

    def test_no_break_hyphen_is_rejected_instead_of_dropped(self):
        path = make_docx(
            '<w:r><w:t>001</w:t><w:noBreakHyphen/><w:t>234</w:t></w:r>'
        )
        try:
            with self.assertRaisesRegex(ValueError, "noBreakHyphen"):
                DOCX.extract(path)
        finally:
            path.unlink()

    def test_soft_hyphen_is_rejected_instead_of_dropped(self):
        path = make_docx(
            '<w:r><w:t>001</w:t><w:softHyphen/><w:t>234</w:t></w:r>'
        )
        try:
            with self.assertRaisesRegex(ValueError, "softHyphen"):
                DOCX.extract(path)
        finally:
            path.unlink()

    def test_alternate_content_is_rejected(self):
        path = make_docx(
            '<mc:AlternateContent><mc:Choice Requires="w">'
            '<w:r><w:t>001</w:t></w:r></mc:Choice>'
            '<mc:Fallback><w:r><w:t>002</w:t></w:r></mc:Fallback>'
            '</mc:AlternateContent>'
        )
        try:
            with self.assertRaisesRegex(ValueError, "AlternateContent"):
                DOCX.extract(path)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
