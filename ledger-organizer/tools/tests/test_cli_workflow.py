"""Synthetic subprocess workflow: environment check, bundled conversion, readback."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from openpyxl import load_workbook

TOOLS=Path(__file__).resolve().parents[1]

class CliWorkflow(unittest.TestCase):
    def test_checked_interpreter_conversion_and_preservation(self):
        with tempfile.TemporaryDirectory(prefix='ledger-cli-') as temporary:
            directory=Path(temporary)
            source=directory/'synthetic.csv'
            workbook_path=directory/'result.xlsx'
            restored=directory/'restored.csv'
            expected=[['ID','amount','note'],['001234567890123456789','12.30','first\nsecond'],['00042','-0.00',''],['00043','','pending']]
            with source.open('w',encoding='utf-8-sig',newline='') as stream:
                csv.writer(stream).writerows(expected)
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            checked=subprocess.run([sys.executable,str(TOOLS/'check_environment.py'),'--task','table_conversion'],capture_output=True,text=True,encoding='utf8',timeout=30)
            self.assertEqual(checked.returncode,0,checked.stderr)
            report=json.loads(checked.stdout)
            self.assertTrue(report['dependency_check_passed'])
            self.assertEqual(Path(report['executable']).resolve(),Path(sys.executable).resolve())
            entrypoint=report['entrypoint']
            def convert(input_path,output_path):
                return subprocess.run([report['executable'],entrypoint,str(input_path),str(output_path)],capture_output=True,text=True,encoding='utf8',timeout=30)
            converted=convert(source,workbook_path)
            self.assertEqual(converted.returncode,0,converted.stderr)
            workbook=load_workbook(workbook_path,read_only=True,data_only=False)
            try:
                actual=[[value if value is not None else '' for value in row] for row in workbook.active.values]
                self.assertEqual(actual,expected)
                self.assertEqual(workbook.active['A2'].data_type,'s')
                self.assertEqual(workbook.active['B3'].value,'-0.00')
                self.assertIsNone(workbook.active['B4'].value)
            finally:
                workbook.close()
            result=convert(workbook_path,restored)
            self.assertEqual(result.returncode,0,result.stderr)
            with restored.open(encoding='utf-8-sig',newline='') as stream:
                self.assertEqual(list(csv.reader(stream)),expected)
            output_hash=hashlib.sha256(workbook_path.read_bytes()).hexdigest()
            repeated=convert(source,workbook_path)
            self.assertNotEqual(repeated.returncode,0)
            self.assertIn('FileExistsError',repeated.stderr)
            self.assertEqual(hashlib.sha256(workbook_path.read_bytes()).hexdigest(),output_hash)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
            self.assertEqual(list(directory.glob('.ledger-conversion-*')),[])

if __name__=='__main__':unittest.main()
