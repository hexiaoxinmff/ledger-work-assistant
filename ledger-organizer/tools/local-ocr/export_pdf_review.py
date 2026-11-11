"""Collect page-specific OCR grid JSON into a traceable review workbook."""
import argparse,hashlib,json
from pathlib import Path
from openpyxl import Workbook,load_workbook

def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def append_text(ws,values,indices):
 ws.append(values)
 for col in indices:
  if isinstance(ws.cell(ws.max_row,col).value,str):ws.cell(ws.max_row,col).data_type='s'

def run(pdf,pages_dir,output):
 pdf=Path(pdf).resolve();directory=Path(pages_dir).resolve();output=Path(output).resolve()
 if output.suffix.lower()!='.xlsx' or output==pdf:raise ValueError('输出应为新 XLSX')
 sourcehash=sha(pdf); manifestfile=directory/'pages.json';manhash=sha(manifestfile); manifest=json.loads(manifestfile.read_text(encoding='utf8'))
 if manifest.get('source_sha256')!=sourcehash:raise ValueError('PDF 来源哈希不一致')
 count=manifest.get('page_count');pages=manifest.get('pages')
 if not isinstance(count,int) or not 1<=count<=20 or not isinstance(pages,list) or len(pages)!=count:raise ValueError('页数无效')
 w=Workbook();review=w.active;review.title='逐格复核';review.append(['PDF页码','行','列','识别原文','页内位置_像素','复核状态'])
 missing=w.create_sheet('未归属片段');missing.append(['PDF页码','识别原文','页内位置_像素','复核状态'])
 info=w.create_sheet('来源');info.append(['项目','内容']);append_text(info,['PDF文件名',pdf.name],[2]);info.append(['PDF SHA-256',sourcehash]);info.append(['页面清单 SHA-256',manhash]);info.append(['注意','所有格子包括空白和未归属片段均需对原 PDF 人工核对'])
 expected=[];miss_expected=[];proof=[]
 for i,p in enumerate(pages,1):
  name=f'page_{i:04d}.png'
  if p.get('page')!=i or p.get('image')!=name:raise ValueError('页面顺序或文件名无效')
  img=directory/name;ocr=directory/f'page_{i:04d}_ocr.json';grid=directory/f'page_{i:04d}_grid.json'
  imgsha=sha(img);ocrsha=sha(ocr);gridsha=sha(grid)
  if imgsha!=p.get('sha256'):raise ValueError('页面图片哈希不一致')
  ocr_data=json.loads(ocr.read_text(encoding='utf8'));g=json.loads(grid.read_text(encoding='utf8'))
  if ocr_data.get('来源sha256')!=imgsha or g.get('来源sha256')!=imgsha or g.get('OCR结果sha256')!=ocrsha:raise ValueError('页面识别结果不匹配')
  rows,cols=g.get('行数'),g.get('列数');cells=g.get('单元格');unassigned=g.get('未归属片段')
  if not isinstance(rows,int) or not isinstance(cols,int) or not 1<=rows<=100 or not 1<=cols<=30 or not isinstance(cells,list) or len(cells)!=rows*cols or not isinstance(unassigned,list):raise ValueError('网格数据无效')
  ws=w.create_sheet(f'页{i:03d}_待核对');seen=set()
  for c in cells:
   r,k,text,box=c.get('行'),c.get('列'),c.get('识别文本'),c.get('边界_像素')
   if not isinstance(r,int) or not isinstance(k,int) or not 1<=r<=rows or not 1<=k<=cols or (r,k) in seen or not isinstance(text,str) or len(text)>32767 or not isinstance(box,list) or len(box)!=4:raise ValueError('单元格无效')
   seen.add((r,k));cell=ws.cell(r,k);cell.value=text;cell.data_type='s'
   coords=json.dumps(box,ensure_ascii=False);append_text(review,[i,r,k,text,coords,'待人工核对原PDF'],[4]);expected.append((i,r,k,text or None,coords,'待人工核对原PDF'))
  for part in unassigned:
   text,box=part.get('识别文本'),part.get('位置_像素')
   if not isinstance(text,str) or len(text)>32767 or not isinstance(box,list):raise ValueError('识别片段无效')
   coords=json.dumps(box,ensure_ascii=False);append_text(missing,[i,text,coords,'待人工核对原PDF'],[2]);miss_expected.append((i,text or None,coords,'待人工核对原PDF'))
  append_text(info,[f'第{i}页图片 SHA-256',imgsha],[]);append_text(info,[f'第{i}页 OCR JSON SHA-256',ocrsha],[]);append_text(info,[f'第{i}页网格 JSON SHA-256',gridsha],[])
  proof.extend([(img,imgsha),(ocr,ocrsha),(grid,gridsha)])
 with open(output,'xb') as f:w.save(f)
 if sha(pdf)!=sourcehash or sha(manifestfile)!=manhash or any(sha(f)!=h for f,h in proof):raise ValueError('输入处理期间发生变化')
 check=load_workbook(output,read_only=True,data_only=False)
 try:
  if list(check['逐格复核'].values)[1:]!=expected or list(check['未归属片段'].values)[1:]!=miss_expected:raise ValueError('复核清单回读不一致')
  for page,row,col,text,_,_ in expected:
   if check[f'页{page:03d}_待核对'].cell(row,col).value!=text:raise ValueError('输出表格回读不一致')
 finally:check.close()
 return count,len(expected),len(miss_expected)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('pdf');p.add_argument('pages_dir');p.add_argument('output');a=p.parse_args();print('页面、单元格、未归属片段:',run(a.pdf,a.pages_dir,a.output))
