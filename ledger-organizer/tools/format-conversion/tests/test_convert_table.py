"""Synthetic tests: distinguish cell values from Excel's displayed formatting."""
import csv, datetime, importlib.util, tempfile, unittest
from pathlib import Path
from openpyxl import Workbook, load_workbook

HERE=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('convert_table',HERE/'convert_table.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ConvertTable(unittest.TestCase):
 def test_formatted_numbers_require_explicit_choice(self):
  cases=[(123,'00000'),(0.15,'0%'),(12.3,'0.00'),(datetime.datetime(2026,1,2),'yyyy-mm-dd')]
  for value,fmt in cases:
   with self.subTest(value=value),tempfile.TemporaryDirectory() as tmp:
    d=Path(tmp);src=d/'source.xlsx';out=d/'result.csv'
    w=Workbook();c=w.active['A1'];c.value=value;c.number_format=fmt;w.save(src);w.close()
    with self.assertRaisesRegex(ValueError,'A1.*显示依赖格式'):module.run(str(src),str(out))
    self.assertFalse(out.exists())
    self.assertEqual(module.run(str(src),str(out),allow_display_loss=True),1)
    with out.open(encoding='utf-8-sig',newline='') as f:actual=list(csv.reader(f))
    self.assertEqual(actual,[[str(value)]])

 def test_text_identifier_roundtrip_and_formula_guard(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);csv_in=d/'input.csv';xlsx=d/'middle.xlsx';csv_out=d/'output.csv'
   rows=[['编号','金额'],['001234567890123456789','12.30'],['00042','-12.00']]
   with csv_in.open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f).writerows(rows)
   module.run(str(csv_in),str(xlsx))
   w=load_workbook(xlsx);self.assertEqual(w.active['A2'].value,rows[1][0]);self.assertEqual(w.active['A2'].data_type,'s');w.close()
   module.run(str(xlsx),str(csv_out))
   with csv_out.open(encoding='utf-8-sig',newline='') as f:self.assertEqual(list(csv.reader(f)),rows)
   bad=d/'formula.xlsx';out=d/'bad.csv';w=Workbook();w.active['A1']='=1+1';w.save(bad);w.close()
   with self.assertRaisesRegex(ValueError,'公式'):module.run(str(bad),str(out),allow_display_loss=True)
   self.assertFalse(out.exists())

if __name__=='__main__':unittest.main()
