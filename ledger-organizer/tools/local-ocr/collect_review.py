"""Collect declared human review decisions; never certify financial correctness."""
import argparse,hashlib,json,math,os,tempfile
from pathlib import Path
from openpyxl import Workbook,load_workbook


def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()


def _fragment_row(page,row,col,association,fragment):
 index=fragment.get('OCR结果序号');text=fragment.get('识别文本');score=fragment.get('模型分数');box=fragment.get('位置_像素')
 if type(index) is not int or index<1 or not isinstance(text,str) or len(text)>32767:raise ValueError('OCR 片段编号或原文无效')
 if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:raise ValueError('OCR 模型分数无效')
 if fragment.get('复核状态')!='待人工核对原图':raise ValueError('OCR 片段复核状态无效')
 if not isinstance(box,list) or len(box)!=4:raise ValueError('OCR 边界框格式无效')
 for point in box:
  if not isinstance(point,list) or len(point)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in point):raise ValueError('OCR 边界框坐标无效')
 return (page,index,row,col,association,text,float(score),json.dumps(box,ensure_ascii=False),'待人工核对原PDF')


def run(pdf,pages_dir,reviewed,output):
 pdf=Path(pdf).resolve();directory=Path(pages_dir).resolve();reviewed=Path(reviewed).resolve();output=Path(output).resolve()
 if output.suffix.lower()!='.xlsx' or len({str(pdf),str(reviewed),str(output)})!=3:raise ValueError('输入输出必须是不同文件，输出为 XLSX')
 if not output.parent.is_dir():raise FileNotFoundError(f'输出目录不存在：{output.parent}')
 if os.path.lexists(output):raise FileExistsError(output)
 pdfhash=sha(pdf);reviewhash=sha(reviewed);manifestfile=directory/'pages.json';manhash=sha(manifestfile);manifest=json.loads(manifestfile.read_text(encoding='utf8'))
 if manifest.get('source_sha256')!=pdfhash:raise ValueError('PDF 来源哈希不一致')
 pages=manifest.get('pages');count=manifest.get('page_count')
 if type(count) is not int or not 1<=count<=20 or not isinstance(pages,list) or len(pages)!=count:raise ValueError('页数无效')
 expected=[];expected_fragments=[];proof=[];expected_provenance={"PDF SHA-256":pdfhash,"页面清单 SHA-256":manhash}
 for i,item in enumerate(pages,1):
  name=f'page_{i:04d}.png'
  if item.get('page')!=i or item.get('image')!=name:raise ValueError('页面顺序无效')
  image=directory/name;ocr=directory/f'page_{i:04d}_ocr.json';grid=directory/f'page_{i:04d}_grid.json'
  ih,oh,gh=sha(image),sha(ocr),sha(grid)
  if ih!=item.get('sha256'):raise ValueError('页面图片哈希不符')
  o=json.loads(ocr.read_text(encoding='utf8'));g=json.loads(grid.read_text(encoding='utf8'))
  if o.get('来源sha256')!=ih or g.get('来源sha256')!=ih or g.get('OCR结果sha256')!=oh:raise ValueError('识别来源不匹配')
  ocr_rows=o.get('结果')
  rows,cols,cells,unassigned,ocr_count=g.get('行数'),g.get('列数'),g.get('单元格'),g.get('未归属片段'),g.get('OCR识别条数')
  if type(rows) is not int or type(cols) is not int or not 1<=rows<=100 or not 1<=cols<=30 or not isinstance(cells,list) or len(cells)!=rows*cols or not isinstance(unassigned,list) or type(ocr_count) is not int or ocr_count<0 or not isinstance(ocr_rows,list) or len(ocr_rows)!=ocr_count:
   raise ValueError('网格数据无效或缺少完整 OCR 片段计数')
  if unassigned:raise ValueError('存在未归属片段，不能汇总为已完成复核')
  seen=set();page_fragments=[]
  for c in cells:
   row,col,text,box,fragments=c.get('行'),c.get('列'),c.get('识别文本'),c.get('边界_像素'),c.get('片段')
   if type(row) is not int or type(col) is not int or not 1<=row<=rows or not 1<=col<=cols or (row,col) in seen or not isinstance(text,str) or len(text)>32767 or not isinstance(box,list) or len(box)!=4 or not isinstance(fragments,list):raise ValueError('单元格无效')
   seen.add((row,col));expected.append((i,row,col,text or None,json.dumps(box,ensure_ascii=False),'待人工核对原PDF'))
   cell_fragments=[]
   for fragment in fragments:
    item_row=_fragment_row(i,row,col,'已归入网格单元格',fragment)
    cell_fragments.append(item_row);page_fragments.append(item_row)
   if text!=' '.join(fragment[5] for fragment in cell_fragments):raise ValueError('单元格拼接文本与 OCR 片段明细不一致')
  if len(seen)!=rows*cols:raise ValueError('单元格缺失')
  page_fragments.sort(key=lambda item:item[1])
  if len(page_fragments)!=ocr_count or [item[1] for item in page_fragments]!=list(range(1,ocr_count+1)):raise ValueError('OCR 片段存在缺失、重复或序号不连续')
  expected_fragments.extend(page_fragments)
  expected_provenance.update({f"第{i}页图片 SHA-256":ih,f"第{i}页 OCR JSON SHA-256":oh,f"第{i}页网格 JSON SHA-256":gh})
  proof.extend([(image,ih),(ocr,oh),(grid,gh)])
 if len(expected_fragments)>1_048_575:raise ValueError('OCR 片段超过 Excel 工作表容量')
 w=load_workbook(reviewed,read_only=True,data_only=False)
 try:
  required={'逐格复核','来源','识别片段明细','未归属片段'}
  if not required.issubset(w.sheetnames):raise ValueError('缺少复核、来源或 OCR 片段工作表')
  provenance={}
  for key,value in w['来源'].iter_rows(min_row=2,max_col=2,values_only=True):
   if key in expected_provenance:
    if key in provenance:raise ValueError('来源标识重复')
    provenance[key]=value
  if provenance!=expected_provenance:raise ValueError('来源哈希与复核表不一致')
  ws=w['逐格复核'];headers=tuple(next(ws.iter_rows(min_row=1,max_row=1,max_col=8,values_only=True)))
  if headers!=('PDF页码','行','列','识别原文','页内位置_像素','复核状态','人工复核选择','人工修正原文'):raise ValueError('复核表字段不匹配')
  if ws.max_row!=len(expected)+1:raise ValueError('复核记录数不符')
  detail_headers=tuple(next(w['识别片段明细'].iter_rows(min_row=1,max_row=1,max_col=9,values_only=True)))
  if detail_headers!=('PDF页码','OCR结果序号','所属网格行','所属网格列','归属状态','识别原文','模型分数（仅供参考）','页内位置_像素','复核状态'):raise ValueError('OCR 片段字段不匹配')
  actual_fragments=[tuple(row) for row in w['识别片段明细'].iter_rows(min_row=2,max_col=9,values_only=True)]
  if actual_fragments!=expected_fragments:raise ValueError('复核表 OCR 片段或来源发生改变')
  if w['未归属片段'].max_row!=1:raise ValueError('复核表未归属片段清单发生改变')
  decisions=[];unresolved=0
  for index,(cells,original) in enumerate(zip(ws.iter_rows(min_row=2,max_col=8),expected),2):
   vals=tuple(c.value for c in cells)
   if vals[:6]!=original or any(c.data_type=='f' for c in cells):raise ValueError(f'第 {index} 行识别原文或来源发生改变')
   choice,edited=vals[6:8];raw=original[3]
   if choice=='原文一致':
    if raw is None or edited is not None:raise ValueError(f'第 {index} 行不符合原文一致规则')
    result=raw
   elif choice=='人工修正':
    if not isinstance(edited,str) or edited=='':raise ValueError(f'第 {index} 行修正值必须为非空文本；长编号先设置文本格式')
    result=edited
   elif choice in ('原文为空','无法辨认'):
    if edited is not None:raise ValueError(f'第 {index} 行该状态不能同时填写修正值')
    result=None;unresolved+=choice=='无法辨认'
   else:raise ValueError(f'第 {index} 行尚未完成选择')
   decisions.append((original[0],original[1],original[2],raw,choice,result,original[4]))
 finally:w.close()
 output_w=Workbook();detail=output_w.active;detail.title='复核记录';detail.append(['PDF页码','行','列','OCR原文','人工选择','人工结果','页内位置_像素'])
 for row in decisions:
  detail.append(list(row))
  for col in (4,6):
   if isinstance(detail.cell(detail.max_row,col).value,str):detail.cell(detail.max_row,col).data_type='s'
 provenance_sheet=output_w.create_sheet('OCR片段来源')
 provenance_sheet.append(['PDF页码','OCR结果序号','所属网格行','所属网格列','归属状态','识别原文','模型分数（仅供参考）','页内位置_像素','复核状态'])
 for row in expected_fragments:
  provenance_sheet.append(list(row))
  provenance_sheet.cell(provenance_sheet.max_row,6).data_type='s'
 info=output_w.create_sheet('说明');info.append(['项目','内容']);info.append(['来源PDF SHA-256',pdfhash]);info.append(['复核表 SHA-256',reviewhash]);info.append(['页面清单 SHA-256',manhash]);info.append(['无法辨认数量',unresolved]);info.append(['OCR 片段数量',len(expected_fragments)]);info.append(['说明','人工选择由使用者声明，工具无法验证是否真的看过原件；模型分数只作参考，不是财务核准'])
 fd,tempname=tempfile.mkstemp(prefix='.ledger-review-',suffix='.tmp',dir=output.parent)
 try:
  with os.fdopen(fd,'wb') as f:output_w.save(f)
  with open(tempname,'rb') as staged:
   verify=load_workbook(staged,read_only=True,data_only=False)
   try:
    if list(verify['复核记录'].values)[1:]!=decisions:raise ValueError('复核记录回读不一致')
    if list(verify['OCR片段来源'].values)[1:]!=expected_fragments:raise ValueError('OCR 片段来源回读不一致')
   finally:verify.close()
  if sha(pdf)!=pdfhash or sha(reviewed)!=reviewhash or sha(manifestfile)!=manhash or any(sha(x)!=h for x,h in proof):raise ValueError('输入处理期间变化')
  os.link(tempname,output)
 finally:
  os.unlink(tempname);output_w.close()
 return len(decisions),unresolved

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('pdf');p.add_argument('pages_dir');p.add_argument('reviewed');p.add_argument('output');a=p.parse_args();print('已记录项、无法辨认项:',run(a.pdf,a.pages_dir,a.reviewed,a.output))
