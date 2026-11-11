"""Synthetic PDF page-provenance tests; grid and OCR content are simulated."""
import hashlib,importlib.util,json,tempfile,unittest,zipfile,subprocess,sys,time
from unittest.mock import patch
from pathlib import Path
from PIL import Image
from openpyxl import load_workbook
HERE=Path(__file__).resolve().parent.parent

def load(name):
 s=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
render=load('render_pdf');export=load('export_pdf_review')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

class PdfReview(unittest.TestCase):
 def test_page_provenance_and_missing_page(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);pdf=d/'sample.pdf';pages=d/'pages';out=d/'review.xlsx'
   a=Image.new('RGB',(80,80),'white');b=Image.new('RGB',(80,80),'white');a.save(pdf,save_all=True,append_images=[b],resolution=100)
   self.assertEqual(render.run(pdf,pages),2)
   for i in (1,2):
    image=pages/f'page_{i:04d}.png';ocr=pages/f'page_{i:04d}_ocr.json';grid=pages/f'page_{i:04d}_grid.json'
    ocr.write_text(json.dumps({'来源sha256':sha(image),'结果':[]}),encoding='utf8')
    data={'来源sha256':sha(image),'OCR结果sha256':sha(ocr),'行数':1,'列数':1,'单元格':[{'行':1,'列':1,'识别文本':f'00{i}','边界_像素':[0,0,10,10]}],'未归属片段':[]}
    grid.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
   def broken_save(workbook,stream):
    stream.write(b'partial');raise OSError('simulated write failure')
   with patch.object(export.Workbook,'save',broken_save):
    with self.assertRaisesRegex(OSError,'simulated write failure'):export.run(pdf,pages,out)
   self.assertFalse(out.exists());self.assertEqual(list(d.glob('.ledger-pdf-review-*.tmp')),[])
   with patch.object(export,'load_workbook',side_effect=ValueError('simulated readback failure')):
    with self.assertRaisesRegex(ValueError,'simulated readback failure'):export.run(pdf,pages,out)
   self.assertFalse(out.exists());self.assertEqual(list(d.glob('.ledger-pdf-review-*.tmp')),[])
   real_sha=export.sha;pdf_checks=[]
   def changed_input(path):
    if Path(path).resolve()==pdf.resolve():
     pdf_checks.append(1)
     if len(pdf_checks)==2:return 'changed'
    return real_sha(path)
   with patch.object(export,'sha',side_effect=changed_input):
    with self.assertRaisesRegex(ValueError,'输入处理期间发生变化'):export.run(pdf,pages,out)
   self.assertFalse(out.exists());self.assertEqual(list(d.glob('.ledger-pdf-review-*.tmp')),[])
   # Align two real processes immediately before their atomic publish attempt.
   child='''import importlib.util,sys,time\nfrom pathlib import Path\ns=importlib.util.spec_from_file_location("export_child",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nreal=m.os.link\ndef barrier(src,dst):\n Path(sys.argv[5]).touch(exist_ok=False)\n deadline=time.monotonic()+20\n while not Path(sys.argv[6]).exists():\n  if time.monotonic()>deadline: raise TimeoutError("barrier timeout")\n  time.sleep(.01)\n return real(src,dst)\nm.os.link=barrier\ntry: m.run(sys.argv[2],sys.argv[3],sys.argv[4])\nexcept FileExistsError: sys.exit(17)\n'''
   target=d/'concurrent.xlsx';start=d/'start';procs=[];before=sha(pdf)
   try:
    for i in range(2):
     procs.append(subprocess.Popen([sys.executable,'-c',child,str(HERE/'export_pdf_review.py'),str(pdf),str(pages),str(target),str(d/f'ready{i}'),str(start)],stdout=subprocess.PIPE,stderr=subprocess.PIPE))
    deadline=time.monotonic()+20
    while not all((d/f'ready{i}').exists() for i in range(2)):
     if any(p.poll() is not None for p in procs) or time.monotonic()>deadline:raise RuntimeError('children did not reach publish barrier')
     time.sleep(.01)
    start.touch()
    results=[p.communicate(timeout=30) for p in procs]
    self.assertEqual(sorted(p.returncode for p in procs),[0,17],results)
   finally:
    for p in procs:
     if p.poll() is None:p.kill();p.communicate()
   self.assertEqual(sha(pdf),before);self.assertEqual(list(d.glob('.ledger-pdf-review-*.tmp')),[])
   check=load_workbook(target,read_only=True);self.assertEqual(check['逐格复核'].max_row,3);check.close()
   self.assertEqual(export.run(pdf,pages,out),(2,2,0))
   w=load_workbook(out,read_only=True);self.assertEqual(w['页001_待核对']['A1'].value,'001');self.assertEqual(w['页002_待核对']['A1'].value,'002');self.assertEqual(w['逐格复核']['A3'].value,2);self.assertNotIn('页001_原页预览',w.sheetnames);w.close()
   preview=d/'preview.xlsx';self.assertEqual(export.run(pdf,pages,preview,True),(2,2,0));w=load_workbook(preview,read_only=True);self.assertIn('页001_原页预览',w.sheetnames);self.assertIn('页002_原页预览',w.sheetnames);w.close()
   with zipfile.ZipFile(preview) as z:self.assertEqual(len([n for n in z.namelist() if n.startswith('xl/media/') and n.endswith('.png')]),2)
   with self.assertRaises(FileExistsError):export.run(pdf,pages,out)
   (pages/'page_0002_grid.json').unlink()
   with self.assertRaises(FileNotFoundError):export.run(pdf,pages,d/'incomplete.xlsx')
   self.assertFalse((d/'incomplete.xlsx').exists())

if __name__=='__main__':unittest.main()
