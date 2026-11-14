"""Collect page-specific OCR grids into a source-traceable review workbook."""
import argparse,hashlib,json,zipfile,os,tempfile,math
from collections import Counter
from io import BytesIO
from openpyxl.drawing.image import Image as ExcelImage
from pathlib import Path
from openpyxl import Workbook,load_workbook
from openpyxl.worksheet.datavalidation import DataValidation

def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def append_text(ws,values,indices):
 ws.append(values)
 for col in indices:
  if isinstance(ws.cell(ws.max_row,col).value,str):ws.cell(ws.max_row,col).data_type='s'

def _ocr_box_json(box):
 if not isinstance(box,list) or len(box)!=4:raise ValueError('OCR 边界框格式无效')
 for point in box:
  if not isinstance(point,list) or len(point)!=2:raise ValueError('OCR 边界框格式无效')
  if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in point):raise ValueError('OCR 边界框坐标无效')
 return json.dumps(box,ensure_ascii=False)

def _fragment_row(page,index,row,col,status,fragment):
 stored_index=fragment.get('OCR结果序号');text=fragment.get('识别文本');score=fragment.get('模型分数')
 if type(stored_index) is not int or stored_index!=index or not isinstance(text,str) or len(text)>32767:raise ValueError('OCR 片段编号或原文无效')
 if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:raise ValueError('OCR 模型分数无效')
 if fragment.get('复核状态')!='待人工核对原图':raise ValueError('OCR 片段复核状态无效')
 coords=_ocr_box_json(fragment.get('位置_像素'))
 return (page,index,row,col,status,text,float(score),coords,'待人工核对原PDF')

def run(pdf,pages_dir,output,embed_previews=False):
 pdf=Path(pdf).resolve();directory=Path(pages_dir).resolve();output=Path(output).resolve()
 if output.suffix.lower()!='.xlsx' or output==pdf:raise ValueError('输出应为新 XLSX')
 if not output.parent.is_dir():raise FileNotFoundError(f'输出目录不存在：{output.parent}')
 if os.path.lexists(output):raise FileExistsError(output)
 sourcehash=sha(pdf);manifestfile=directory/'pages.json';manhash=sha(manifestfile);manifest=json.loads(manifestfile.read_text(encoding='utf8'))
 if manifest.get('source_sha256')!=sourcehash:raise ValueError('PDF 来源哈希不一致')
 count=manifest.get('page_count');pages=manifest.get('pages')
 if type(count) is not int or not 1<=count<=20 or not isinstance(pages,list) or len(pages)!=count:raise ValueError('页数无效')
 w=Workbook();review=w.active;review.title='逐格复核';review.append(['PDF页码','行','列','识别原文','页内位置_像素','复核状态','人工复核选择','人工修正原文'])
 missing=w.create_sheet('未归属片段');missing.append(['PDF页码','OCR结果序号','识别原文','模型分数（仅供参考）','页内位置_像素','复核状态'])
 details=w.create_sheet('识别片段明细');details.append(['PDF页码','OCR结果序号','所属网格行','所属网格列','归属状态','识别原文','模型分数（仅供参考）','页内位置_像素','复核状态'])
 info=w.create_sheet('来源');info.append(['项目','内容']);append_text(info,['PDF文件名',pdf.name],[2]);info.append(['PDF SHA-256',sourcehash]);info.append(['页面清单 SHA-256',manhash]);info.append(['注意','所有格子包括空白和未归属片段均需对原 PDF 人工核对；模型分数只作参考，不证明识别正确']);info.append(['复核操作','逐格复核表 G 列选择原文一致、人工修正、原文为空或无法辨认；仅人工修正时在 H 列输入文本。未归属片段需单独处理。']);info.append(['长编号','修正原文列按文本保存；如软件仍自动转成数值，请先设置文本再输入，不能恢复已经丢失的前导零。'])
 expected=[];miss_expected=[];detail_expected=[];proof=[];preview_streams=[];preview_hashes=[]
 for i,p in enumerate(pages,1):
  name=f'page_{i:04d}.png'
  if p.get('page')!=i or p.get('image')!=name:raise ValueError('页面顺序或文件名无效')
  img=directory/name;ocr=directory/f'page_{i:04d}_ocr.json';grid=directory/f'page_{i:04d}_grid.json'
  imgsha=sha(img);ocrsha=sha(ocr);gridsha=sha(grid)
  if imgsha!=p.get('sha256'):raise ValueError('页面图片哈希不一致')
  ocr_data=json.loads(ocr.read_text(encoding='utf8'));g=json.loads(grid.read_text(encoding='utf8'))
  if ocr_data.get('来源sha256')!=imgsha or g.get('来源sha256')!=imgsha or g.get('OCR结果sha256')!=ocrsha:raise ValueError('页面识别结果不匹配')
  rows,cols=g.get('行数'),g.get('列数');cells=g.get('单元格');unassigned=g.get('未归属片段');ocr_count=g.get('OCR识别条数')
  if type(rows) is not int or type(cols) is not int or not 1<=rows<=100 or not 1<=cols<=30 or not isinstance(cells,list) or len(cells)!=rows*cols or not isinstance(unassigned,list) or type(ocr_count) is not int or ocr_count<0:raise ValueError('网格数据无效或缺少 OCR 识别条数')
  ws=w.create_sheet(f'页{i:03d}_待核对');seen=set();page_details=[]
  for c in cells:
   r,k,text,box,fragments=c.get('行'),c.get('列'),c.get('识别文本'),c.get('边界_像素'),c.get('片段')
   if type(r) is not int or type(k) is not int or not 1<=r<=rows or not 1<=k<=cols or (r,k) in seen or not isinstance(text,str) or len(text)>32767 or not isinstance(box,list) or len(box)!=4 or not isinstance(fragments,list):raise ValueError('单元格无效')
   seen.add((r,k));cell=ws.cell(r,k);cell.value=text;cell.data_type='s'
   coords=json.dumps(box,ensure_ascii=False);append_text(review,[i,r,k,text,coords,'待人工核对原PDF','待核对',None],[4]);review.cell(review.max_row,8).number_format='@';expected.append((i,r,k,text or None,coords,'待人工核对原PDF','待核对',None))
   cell_fragments=[]
   for fragment in fragments:
    item=_fragment_row(i,fragment.get('OCR结果序号'),r,k,'已归入网格单元格',fragment)
    cell_fragments.append(item);page_details.append(item)
   if text!=' '.join(item[5] for item in cell_fragments):raise ValueError('单元格拼接文本与 OCR 片段明细不一致')
  if len(seen)!=rows*cols:raise ValueError('单元格缺失')
  for fragment in unassigned:
   item=_fragment_row(i,fragment.get('OCR结果序号'),None,None,'未归属',fragment)
   page_details.append(item)
   miss_expected.append((i,item[1],item[5],item[6],item[7],item[8]))
  page_details.sort(key=lambda item:item[1])
  if len(page_details)!=ocr_count or [item[1] for item in page_details]!=list(range(1,ocr_count+1)):raise ValueError('OCR 片段存在缺失、重复或序号不连续')
  detail_expected.extend(page_details)
  if len(detail_expected)>1_048_575:raise ValueError('OCR 片段超过 Excel 工作表容量')
  append_text(info,[f'第{i}页 OCR 识别条数',ocr_count],[])
  append_text(info,[f'第{i}页图片 SHA-256',imgsha],[]);append_text(info,[f'第{i}页 OCR JSON SHA-256',ocrsha],[]);append_text(info,[f'第{i}页网格 JSON SHA-256',gridsha],[])
  if embed_previews:
   from PIL import Image as PILImage
   preview=w.create_sheet(f'页{i:03d}_原页预览')
   preview['A1']='缩略图仅用于定位；数字须对照原 PDF 原尺寸逐项核对。'
   with PILImage.open(img) as source_image:
    source_image.load();source_image.thumbnail((1400,1400))
    stream=BytesIO();source_image.save(stream,format='PNG');stream.seek(0)
   preview_hashes.append(hashlib.sha256(stream.getvalue()).hexdigest());preview_streams.append(stream)
   preview.add_image(ExcelImage(stream),'A3')
 proof.extend([(img,imgsha),(ocr,ocrsha),(grid,gridsha)])
 for item in detail_expected:
  append_text(details,item,[6])
 for item in miss_expected:
  append_text(missing,item,[3])
 review.freeze_panes='D2';review.column_dimensions['D'].width=25;review.column_dimensions['G'].width=18;review.column_dimensions['H'].width=28
 validation=DataValidation(type='list',formula1='"待核对,原文一致,人工修正,原文为空,无法辨认"',allow_blank=False)
 validation.error='请选择列表中的复核状态';validation.errorTitle='复核状态无效';validation.showErrorMessage=True
 review.add_data_validation(validation);validation.add(f'G2:G{len(expected)+1}')
 fd,tempname=tempfile.mkstemp(prefix='.ledger-pdf-review-',suffix='.tmp',dir=output.parent)
 try:
  with os.fdopen(fd,'wb') as f:w.save(f)
  if embed_previews:
   with zipfile.ZipFile(tempname) as z:
    stored=[hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('xl/media/') and n.endswith('.png')]
   if Counter(stored)!=Counter(preview_hashes):raise ValueError('原页预览图片回读不一致')
  with open(tempname,'rb') as staged:
   check=load_workbook(staged,read_only=True,data_only=False)
   try:
    if list(check['逐格复核'].values)[1:]!=expected or list(check['未归属片段'].values)[1:]!=miss_expected:raise ValueError('复核清单回读不一致')
    if list(check['识别片段明细'].values)[1:]!=detail_expected:raise ValueError('OCR 片段明细回读不一致')
    for page,row,col,text,_,_,_,_ in expected:
     if check[f'页{page:03d}_待核对'].cell(row,col).value!=text:raise ValueError('输出表格回读不一致')
   finally:check.close()
  if sha(pdf)!=sourcehash or sha(manifestfile)!=manhash or any(sha(f)!=h for f,h in proof):raise ValueError('输入处理期间发生变化')
  os.link(tempname,output)
 finally:os.unlink(tempname)
 w.close()
 return count,len(expected),len(miss_expected)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('pdf');p.add_argument('pages_dir');p.add_argument('output');p.add_argument('--embed-page-previews',action='store_true');a=p.parse_args();print('页面、单元格、未归属片段:',run(a.pdf,a.pages_dir,a.output,a.embed_page_previews))
