"""Synthetic DOCX archive/resource-boundary tests."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "docx_tables.py"
spec = importlib.util.spec_from_file_location("docx_tables_limits", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_archive(path, xml, extra_entries=()):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
        for name, value in extra_entries:
            archive.writestr(name, value)


def table_xml(cell_count=1):
    cells = "".join("<w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc>" for _ in range(cell_count))
    return (f'<w:document xmlns:w="{W_NS}"><w:body><w:tbl><w:tr>{cells}</w:tr>'
            '</w:tbl></w:body></w:document>').encode()


class DocxResourceLimits(unittest.TestCase):
    def test_rejects_compressed_file_above_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large.docx"
            make_archive(path, table_xml())
            with patch.object(module, "MAX_DOCX_BYTES", 1):
                with self.assertRaisesRegex(ValueError, "100 MiB"):
                    module.extract(path)

    def test_rejects_too_many_zip_entries_and_duplicate_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "entries.docx"
            make_archive(path, table_xml(), [("word/styles.xml", b"<styles/>")])
            with patch.object(module, "MAX_DOCX_ENTRIES", 1):
                with self.assertRaisesRegex(ValueError, "条目"):
                    module.extract(path)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("word/document.xml", table_xml())
                    archive.writestr("word/document.xml", table_xml())
            with self.assertRaisesRegex(ValueError, "重复文件名"):
                module.extract(path)

    def test_rejects_uncompressed_and_document_xml_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "size.docx"
            make_archive(path, table_xml())
            with patch.object(module, "MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES", 10):
                with self.assertRaisesRegex(ValueError, "解压后总大小"):
                    module.extract(path)
            with patch.object(module, "MAX_DOCX_DOCUMENT_XML_BYTES", 10):
                with self.assertRaisesRegex(ValueError, "正文 XML"):
                    module.extract(path)

    def test_rejects_cell_limit_and_dtd_entity_declarations(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cells.docx"
            make_archive(path, table_xml(2))
            with patch.object(module, "MAX_DOCX_CELLS", 1):
                with self.assertRaisesRegex(ValueError, "单元格"):
                    module.extract(path)

            make_archive(path, b'<!DOCTYPE w:document [<!ENTITY x "1">]><w:document/>')
            with self.assertRaisesRegex(ValueError, "DTD 或实体"):
                module.extract(path)


    def test_run_rejects_oversized_file_before_hashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "oversized.docx"
            output = directory / "review.xlsx"
            source.write_bytes(b"more than one byte")
            with patch.object(module, "MAX_DOCX_BYTES", 1):
                with patch.object(module, "sha") as digest:
                    with self.assertRaisesRegex(ValueError, "100 MiB"):
                        module.run(source, output)
                    digest.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(list(directory.glob(".ledger-docx-*")), [])

    def test_sha_rejects_growth_after_initial_size_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "changed.docx"
            source.write_bytes(b"two bytes")
            with patch.object(module.os.path, "getsize", return_value=1):
                with self.assertRaisesRegex(ValueError, "读取期间超过"):
                    module.sha(source, max_bytes=1)


if __name__ == "__main__":
    unittest.main()
