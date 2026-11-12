import csv
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from openpyxl import load_workbook

TOOLS=Path(__file__).resolve().parents[1]
FIXTURES=Path(__file__).resolve().parent/'fixtures'
EXPECTED=[['ID','amount','note'],['001234567890123456789','12.30','first\nsecond'],['00042','-0.00',''],['00043','','pending']]

class AcceptanceFixtures(unittest.TestCase):
    def test_delivered_fixtures_through_cli(self):
        for filename,separator,options in [('acceptance.csv',',',[]),('acceptance.tsv','\t',[]),('acceptance_semicolon.csv',';',['--delimiter','semicolon'])]:
            with self.subTest(filename=filename),tempfile.TemporaryDirectory() as temporary:
                source=FIXTURES/filename
                source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
                with source.open(encoding='utf-8',newline='') as stream:self.assertEqual(list(csv.reader(stream,delimiter=separator)),EXPECTED)
                workbook_path=Path(temporary)/'output.xlsx'
                restored=Path(temporary)/filename
                for input_path,output_path in [(source,workbook_path),(workbook_path,restored)]:
                    result=subprocess.run([sys.executable,str(TOOLS/'format-conversion/convert_table.py'),str(input_path),str(output_path),*options],capture_output=True,text=True,encoding='utf8',timeout=30)
                    self.assertEqual(result.returncode,0,result.stderr)
                workbook=load_workbook(workbook_path,read_only=True,data_only=False)
                try:
                    self.assertEqual([[value if value is not None else '' for value in row] for row in workbook.active.values],EXPECTED)
                    self.assertEqual(workbook.active['A2'].data_type,'s')
                finally:workbook.close()
                with restored.open(encoding='utf-8-sig',newline='') as stream:self.assertEqual(list(csv.reader(stream,delimiter=separator)),EXPECTED)
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),source_hash)

if __name__=='__main__':unittest.main()
