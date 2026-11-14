"""Synthetic tests: distinguish cell values from Excel's displayed formatting."""
import csv, datetime, importlib.util, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook, load_workbook

HERE=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('convert_table',HERE/'convert_table.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ConvertTable(unittest.TestCase):
 def test_expected_columns_catches_wrong_separator(self):
  with tempfile.TemporaryDirectory() as temporary:
   directory=Path(temporary);source=directory/'input.csv';output=directory/'output.xlsx'
   with source.open('w',encoding='utf-8',newline='') as stream:csv.writer(stream,delimiter=';').writerows([['ID','amount','note'],['00042','12.30','ok']])
   with self.assertRaisesRegex(ValueError,'实际列数不符合预期 3'):module.run(str(source),str(output),expected_columns=3)
   self.assertFalse(output.exists());self.assertEqual(list(directory.glob('.ledger-conversion-*')),[])
   command=[sys.executable,str(HERE/'convert_table.py'),str(source),str(output),'--delimiter','semicolon','--expected-columns','3']
   result=subprocess.run(command,capture_output=True,text=True,encoding='utf8',timeout=30)
   self.assertEqual(result.returncode,0,result.stderr)
   with self.assertRaisesRegex(ValueError,'实际列数不符合预期 2'):module.run(str(output),str(directory/'bad.tsv'),expected_columns=2)
   self.assertFalse((directory/'bad.tsv').exists())
   for invalid in (0,-1,16385,True,'3'):
    with self.assertRaisesRegex(ValueError,'预期列数必须'):module.run(str(source),str(directory/'invalid.xlsx'),expected_columns=invalid)
 def test_tsv_and_semicolon_roundtrip(self):
  rows=[['ID','amount','note'],['001234567890123456789','12.30','inside\ttab;comma,quote"\nnext'],['00042','','pending']]
  for suffix,separator,option in (('.tsv','\t',None),('.csv',';',';')):
   with self.subTest(suffix=suffix),tempfile.TemporaryDirectory() as temporary:
    directory=Path(temporary);source=directory/('input'+suffix);xlsx=directory/'output.xlsx';restored=directory/('restored'+suffix)
    with source.open('w',encoding='utf-8-sig',newline='') as stream:csv.writer(stream,delimiter=separator).writerows(rows)
    before=module.sha(source)
    module.run(str(source),str(xlsx),delimiter=option)
    module.run(str(xlsx),str(restored),delimiter=option)
    with restored.open(encoding='utf-8-sig',newline='') as stream:self.assertEqual(list(csv.reader(stream,delimiter=separator)),rows)
    self.assertEqual(module.sha(source),before)
    with self.assertRaises(FileExistsError):module.run(str(source),str(xlsx),delimiter=option)
    if suffix=='.tsv':
     with self.assertRaisesRegex(ValueError,'TSV 必须'):module.run(str(source),str(directory/'bad.xlsx'),delimiter=';')
     self.assertFalse((directory/'bad.xlsx').exists())
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

 def test_formula_guard_checks_prefix_after_leading_whitespace(self):
  dangerous=[' =1+1','  +SUM(A1)','\t@SUM(A1)','\n＝1+1','  －cmd']
  for value in dangerous:
   with self.subTest(value=value),tempfile.TemporaryDirectory() as tmp:
    d=Path(tmp);source=d/'source.xlsx';output=d/'output.csv'
    workbook=Workbook();workbook.active['A1']=value;workbook.save(source);workbook.close()
    with self.assertRaisesRegex(ValueError,'前导空白后的公式前缀'):
     module.run(str(source),str(output),allow_display_loss=True)
    self.assertFalse(output.exists())
    self.assertEqual(list(d.glob('.ledger-conversion-*')),[])
  self.assertFalse(module._unsafe_csv_formula_text('-12.00'))
  self.assertFalse(module._unsafe_csv_formula_text('  -12.00'))
  self.assertFalse(module._unsafe_csv_formula_text('Amount =1+1'))

 def test_failed_or_changed_conversion_never_publishes_output(self):
  with tempfile.TemporaryDirectory() as tmp:
   directory=Path(tmp);csv_source=directory/'input.csv';xlsx_output=directory/'output.xlsx'
   rows=[['编号'],['001234567890123456789']]
   with csv_source.open('w',encoding='utf-8-sig',newline='') as stream:csv.writer(stream).writerows(rows)
   def broken_save(workbook,stream):
    stream.write(b'partial');raise OSError('simulated xlsx write failure')
   with patch.object(module.Workbook,'save',broken_save):
    with self.assertRaisesRegex(OSError,'simulated xlsx write failure'):module.run(str(csv_source),str(xlsx_output))
   self.assertFalse(xlsx_output.exists());self.assertEqual(list(directory.glob('.ledger-conversion-*.tmp')),[])
   with patch.object(module,'load_workbook',side_effect=ValueError('simulated xlsx readback failure')):
    with self.assertRaisesRegex(ValueError,'simulated xlsx readback failure'):module.run(str(csv_source),str(xlsx_output))
   self.assertFalse(xlsx_output.exists());self.assertEqual(list(directory.glob('.ledger-conversion-*.tmp')),[])
   real_sha=module.sha;source_checks=[]
   def changed_source(path):
    if Path(path).resolve()==csv_source.resolve():
     source_checks.append(1)
     if len(source_checks)==2:return 'changed'
    return real_sha(path)
   with patch.object(module,'sha',side_effect=changed_source):
    with self.assertRaisesRegex(ValueError,'源文件发生变化'):module.run(str(csv_source),str(xlsx_output))
   self.assertFalse(xlsx_output.exists());self.assertEqual(list(directory.glob('.ledger-conversion-*.tmp')),[])
   xlsx_source=directory/'source.xlsx';csv_output=directory/'output.csv'
   workbook=Workbook();workbook.active['A1']='00042';workbook.save(xlsx_source);workbook.close()
   class BrokenWriter:
    def writerows(self,rows):raise OSError('simulated csv write failure')
   with patch.object(module.csv,'writer',return_value=BrokenWriter()):
    with self.assertRaisesRegex(OSError,'simulated csv write failure'):module.run(str(xlsx_source),str(csv_output))
   self.assertFalse(csv_output.exists());self.assertEqual(list(directory.glob('.ledger-conversion-*.tmp')),[])
   with patch.object(module.csv,'reader',return_value=[['changed']]):
    with self.assertRaisesRegex(ValueError,'转换后回读不一致'):module.run(str(xlsx_source),str(csv_output))
   self.assertFalse(csv_output.exists());self.assertEqual(list(directory.glob('.ledger-conversion-*.tmp')),[])
   for source,output in ((csv_source,xlsx_output),(xlsx_source,csv_output)):
    with patch.object(module.os,'link',side_effect=OSError('hard links unsupported')):
     with self.assertRaisesRegex(OSError,'hard links unsupported'):module.run(str(source),str(output))
    self.assertFalse(output.exists());self.assertEqual(list(directory.glob('.ledger-conversion-*.tmp')),[])
    output.write_bytes(b'existing result')
    with self.assertRaises(FileExistsError):module.run(str(source),str(output))
    self.assertEqual(output.read_bytes(),b'existing result')

 def test_two_processes_do_not_overwrite_same_output(self):
  with tempfile.TemporaryDirectory() as tmp:
   directory=Path(tmp);source=directory/'input.csv';output=directory/'output.xlsx';start=directory/'start'
   with source.open('w',encoding='utf-8-sig',newline='') as stream:csv.writer(stream).writerows([['编号'],['00042']])
   child='''import importlib.util,sys,time\nfrom pathlib import Path\ns=importlib.util.spec_from_file_location("convert_child",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nreal=m.os.link\ndef barrier(src,dst):\n Path(sys.argv[4]).touch(exist_ok=False)\n deadline=time.monotonic()+20\n while not Path(sys.argv[5]).exists():\n  if time.monotonic()>deadline: raise TimeoutError("barrier timeout")\n  time.sleep(.01)\n return real(src,dst)\nm.os.link=barrier\ntry: m.run(sys.argv[2],sys.argv[3])\nexcept FileExistsError: sys.exit(17)\n'''
   processes=[]
   try:
    for index in range(2):
     processes.append(subprocess.Popen([sys.executable,'-c',child,str(HERE/'convert_table.py'),str(source),str(output),str(directory/f'ready{index}'),str(start)],stdout=subprocess.PIPE,stderr=subprocess.PIPE))
    deadline=time.monotonic()+20
    while not all((directory/f'ready{index}').exists() for index in range(2)):
     if any(process.poll() is not None for process in processes) or time.monotonic()>deadline:raise RuntimeError('children did not reach publish barrier')
     time.sleep(.01)
    start.touch();results=[process.communicate(timeout=30) for process in processes]
    self.assertEqual(sorted(process.returncode for process in processes),[0,17],results)
   finally:
    for process in processes:
     if process.poll() is None:process.kill();process.communicate()
   workbook=load_workbook(output,read_only=True)
   try:self.assertEqual(list(workbook.active.values),[('编号',),('00042',)])
   finally:workbook.close()
   self.assertEqual(list(directory.glob('.ledger-conversion-*.tmp')),[])

if __name__=='__main__':unittest.main()
