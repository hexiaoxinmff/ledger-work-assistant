"""Synthetic grid mapping tests; no real OCR or network required."""
import hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path
import cv2
import numpy as np
from openpyxl import load_workbook

HERE=Path(__file__).resolve().parent.parent

def load(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

grid=load('table_grid');export=load('export_review')

class GridReview(unittest.TestCase):
 def test_grid_and_export(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);im=d/'grid.png';ocr=d/'ocr.json';out=d/'grid.json';xlsx=d/'result.xlsx'
   array=np.full((200,300,3),255,dtype=np.uint8)
   for x in [20,150,280]:cv2.line(array,(x,20),(x,180),(0,0,0),2)
   for y in [20,100,180]:cv2.line(array,(20,y),(280,y),(0,0,0),2)
   ok,buf=cv2.imencode('.png',array);self.assertTrue(ok);im.write_bytes(buf.tobytes())
   h=hashlib.sha256(im.read_bytes()).hexdigest()
   entries=[{'识别文本':'=1+2','位置_像素':[[30,30],[90,30],[90,50],[30,50]]},{'识别文本':'cross','位置_像素':[[145,35],[160,35],[160,55],[145,55]]}]
   ocr.write_text(json.dumps({'来源sha256':h,'结果':entries},ensure_ascii=False),encoding='utf8')
   self.assertEqual(grid.map_table(im,ocr,out),(4,1));self.assertEqual(export.run(im,out,xlsx),(4,1))
   w=load_workbook(xlsx);self.assertEqual(w['待核对表格']['A1'].value,'=1+2');self.assertEqual(w['待核对表格']['A1'].data_type,'s');self.assertEqual(w['未归属片段']['A2'].value,'cross');w.close()
   with self.assertRaises(FileExistsError):grid.map_table(im,ocr,out)
   with self.assertRaises(FileExistsError):export.run(im,out,xlsx)
   ocr.write_text(json.dumps({'来源sha256':'invalid','结果':[]}),encoding='utf8')
   with self.assertRaises(ValueError):grid.map_table(im,ocr,d/'bad.json')
   self.assertFalse((d/'bad.json').exists())

if __name__=='__main__':unittest.main()
