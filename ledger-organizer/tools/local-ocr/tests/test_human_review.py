"""Tests human-declared review, not human accuracy."""
import hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from openpyxl import load_workbook
HERE=Path(__file__).resolve().parent.parent

def load(name):
 spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
render=load('render_pdf');export=load('export_pdf_review');collect=load('collect_review')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

class HumanReview(unittest.TestCase):
 def test_human_decisions_and_fail_closed(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);pdf=d/'source.pdf';pages=d/'pages';review=d/'review.xlsx';out=d/'collected.xlsx'
   a=Image.new('RGB',(80,80),'white');b=Image.new('RGB',(80,80),'white');a.save(pdf,save_all=True,append_images=[b],resolution=100);render.run(pdf,pages)
   for i in (1,2):
    image=pages/f'page_{i:04d}.png';ocr=pages/f'page_{i:04d}_ocr.json';grid=pages/f'page_{i:04d}_grid.json';ocr.write_text(json.dumps({'来源sha256':sha(image),'结果':[]}),encoding='utf8')
    cells=[{'行':1,'列':n,'识别文本':val,'边界_像素':[n,0,n+1,5]} for n,val in enumerate(('001','8.0') if i==1 else ('','?'),1)]
    grid.write_text(json.dumps({'来源sha256':sha(image),'OCR结果sha256':sha(ocr),'行数':1,'列数':2,'单元格':cells,'未归属片段':[]},ensure_ascii=False),encoding='utf8')
   export.run(pdf,pages,review)
   with self.assertRaisesRegex(ValueError,'尚未完成选择'):collect.run(pdf,pages,review,out)
   self.assertFalse(out.exists())
   wb=load_workbook(review);ws=wb['逐格复核']
   for i,choice in enumerate(['原文一致','人工修正','原文为空','无法辨认'],2):ws.cell(i,7).value=choice
   ws['H3']=123;wb.save(review);wb.close()
   with self.assertRaisesRegex(ValueError,'必须为非空文本'):collect.run(pdf,pages,review,out)
   wb=load_workbook(review);ws=wb['逐格复核'];ws['H3']='000123456789012345678';wb.save(review);wb.close()
   self.assertEqual(collect.run(pdf,pages,review,out),(4,1))
   result=load_workbook(out);self.assertEqual(result['复核记录']['F2'].value,'001');self.assertEqual(result['复核记录']['F3'].value,'000123456789012345678');self.assertEqual(result['复核记录']['F3'].data_type,'s');self.assertEqual(result['说明']['B5'].value,1);result.close()
   before=sha(out)
   with self.assertRaises(FileExistsError):collect.run(pdf,pages,review,out)
   self.assertEqual(sha(out),before)
   wb=load_workbook(review);wb['逐格复核']['D2']='changed';wb.save(review);wb.close()
   with self.assertRaisesRegex(ValueError,'来源发生改变'):collect.run(pdf,pages,review,d/'tampered.xlsx')
   self.assertFalse((d/'tampered.xlsx').exists())
   wb=load_workbook(review);wb['逐格复核']['D2']='001';wb.save(review);wb.close()
   grid=pages/'page_0001_grid.json';data=json.loads(grid.read_text(encoding='utf8'));data['附加信息']='changed';grid.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
   with self.assertRaisesRegex(ValueError,'来源哈希'):collect.run(pdf,pages,review,d/'altered-grid.xlsx')
   self.assertFalse((d/'altered-grid.xlsx').exists())
   data['未归属片段']=[{'识别文本':'1','位置_像素':[[0,0],[1,0],[1,1],[0,1]]}];grid.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
   with self.assertRaisesRegex(ValueError,'未归属片段'):collect.run(pdf,pages,review,d/'unassigned.xlsx')
   self.assertFalse((d/'unassigned.xlsx').exists())

if __name__=='__main__':unittest.main()
