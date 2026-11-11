"""Synthetic PDF page-provenance tests; grid and OCR content are simulated."""
import hashlib,importlib.util,json,tempfile,unittest
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
   self.assertEqual(export.run(pdf,pages,out),(2,2,0))
   w=load_workbook(out,read_only=True);self.assertEqual(w['页001_待核对']['A1'].value,'001');self.assertEqual(w['页002_待核对']['A1'].value,'002');self.assertEqual(w['逐格复核']['A3'].value,2);w.close()
   with self.assertRaises(FileExistsError):export.run(pdf,pages,out)
   (pages/'page_0002_grid.json').unlink()
   with self.assertRaises(FileNotFoundError):export.run(pdf,pages,d/'incomplete.xlsx')
   self.assertFalse((d/'incomplete.xlsx').exists())

if __name__=='__main__':unittest.main()
