import importlib.util
from pathlib import Path
import tempfile
import unittest
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

if __name__=='__main__':unittest.main()
