"""Conservative grid checks against partial borders; uses synthetic images."""
import importlib.util,unittest
from pathlib import Path
import cv2
import numpy as np
p=Path(__file__).resolve().parent.parent/'table_grid.py'
s=importlib.util.spec_from_file_location('table_grid',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def image(partial):
 a=np.full((200,300,3),255,np.uint8)
 for x in (20,280):cv2.line(a,(x,20),(x,180),(0,0,0),2)
 for y in (20,180):cv2.line(a,(20,y),(280,y),(0,0,0),2)
 if partial=='vertical':
  cv2.line(a,(20,100),(280,100),(0,0,0),2);cv2.line(a,(150,100),(150,180),(0,0,0),2)
 elif partial=='horizontal':
  cv2.line(a,(150,20),(150,180),(0,0,0),2);cv2.line(a,(150,100),(280,100),(0,0,0),2)
 else:
  cv2.line(a,(20,100),(280,100),(0,0,0),2);cv2.line(a,(150,20),(150,180),(0,0,0),2)
 return a

class PartialGrid(unittest.TestCase):
 def test_partial_lines_rejected(self):
  for mode in ('vertical','horizontal'):
   with self.subTest(mode=mode):
    with self.assertRaisesRegex(ValueError,'内部出现未识别'):m.lines(image(mode))
 def test_regular_grid_detected(self):
  xs,ys=m.lines(image('complete'));self.assertEqual(len(xs),3);self.assertEqual(len(ys),3)

if __name__=='__main__':unittest.main()
