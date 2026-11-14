import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile
from openpyxl import load_workbook

spec=importlib.util.spec_from_file_location('docx_tables',Path(__file__).resolve().parents[1]/'docx_tables.py')
converter=importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)

def document(path,content):
    xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+content+'</w:body></w:document>'
    with zipfile.ZipFile(path,'w') as archive:archive.writestr('word/document.xml',xml)

class SpecialContent(unittest.TestCase):
    def test_special_content_is_not_silently_dropped(self):
        cases=['<w:r><w:sym w:font="Symbol" w:char="F02D"/></w:r>', '<w:r><w:fldChar w:fldCharType="begin"/></w:r>', '<w:sdt><w:sdtContent><w:r><w:t>123</w:t></w:r></w:sdtContent></w:sdt>', '<w:r><w:footnoteReference w:id="1"/></w:r>']
        cases.extend(['<w:r><w:endnoteReference w:id="1"/></w:r>', '<w:altChunk/>'])
        for special in cases:
            with self.subTest(special=special),tempfile.TemporaryDirectory() as temporary:
                source=Path(temporary)/'source.docx';output=Path(temporary)/'output.xlsx'
                document(source,'<w:tbl><w:tr><w:tc><w:p>'+special+'<w:r><w:t>100</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
                with self.assertRaisesRegex(ValueError,'特殊内容'):converter.run(source,output)
                self.assertFalse(output.exists())
                self.assertEqual(list(Path(temporary).glob('.ledger-docx-*')),[])

    def test_wrapped_table_and_plain_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);source=directory/'source.docx';output=directory/'output.xlsx'
            table='<w:tbl><w:tr><w:tc><w:p><w:r><w:t>001234567890123456789</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            document(source,table+'<w:sdt><w:sdtContent>'+table+'</w:sdtContent></w:sdt>')
            with self.assertRaisesRegex(ValueError,'特殊内容'):converter.run(source,output)
            self.assertFalse(output.exists())
            document(source,table)
            self.assertEqual(converter.run(source,output),1)
            workbook=load_workbook(output,read_only=True)
            try:
                self.assertEqual(workbook['表格1']['A1'].value,'001234567890123456789')
                self.assertEqual(workbook['表格1']['A1'].data_type,'s')
            finally:workbook.close()

    def test_failed_conversion_never_publishes_unverified_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);source=directory/'source.docx';output=directory/'output.xlsx'
            table='<w:tbl><w:tr><w:tc><w:p><w:r><w:t>金额 123.45</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            document(source,table)
            original_sha=converter.sha(source)

            with self.subTest(failure='write'),mock.patch.object(converter.Workbook,'save',side_effect=OSError('simulated write failure')):
                with self.assertRaisesRegex(OSError,'simulated write failure'):converter.run(source,output)
                self.assertFalse(output.exists())
                self.assertEqual(list(directory.glob('.ledger-docx-*')),[])

            with self.subTest(failure='readback'),mock.patch.object(converter,'load_workbook',side_effect=ValueError('simulated readback failure')):
                with self.assertRaisesRegex(ValueError,'simulated readback failure'):converter.run(source,output)
                self.assertFalse(output.exists())
                self.assertEqual(list(directory.glob('.ledger-docx-*')),[])

            with self.subTest(failure='source changed'),mock.patch.object(converter,'sha',side_effect=[original_sha,'changed']):
                with self.assertRaisesRegex(ValueError,'输入处理期间发生变化'):converter.run(source,output)
                self.assertFalse(output.exists())
                self.assertEqual(list(directory.glob('.ledger-docx-*')),[])

            output.write_bytes(b'existing workbook')
            with self.assertRaises(FileExistsError):converter.run(source,output)
            self.assertEqual(output.read_bytes(),b'existing workbook')
            self.assertEqual(list(directory.glob('.ledger-docx-*')),[])

if __name__=='__main__':unittest.main()
