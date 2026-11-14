"""Export experimental OCR grid JSON to an all-pending review workbook."""
import argparse, hashlib, json, math, os, tempfile
from pathlib import Path
from openpyxl import Workbook,load_workbook


def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def set_text(cell,value):
    if len(value)>32767:raise ValueError('单元格文字超长')
    cell.value=value
    cell.data_type='s'


def _pixel_box_json(box):
    if not isinstance(box,list) or len(box)!=4:
        raise ValueError('OCR 边界框格式无效')
    for point in box:
        if not isinstance(point,list) or len(point)!=2:
            raise ValueError('OCR 边界框格式无效')
        if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) for value in point):
            raise ValueError('OCR 边界框坐标无效')
    return json.dumps(box,ensure_ascii=False)


def _fragment_row(fragment, row, col, association):
    index=fragment.get('OCR结果序号');text=fragment.get('识别文本');score=fragment.get('模型分数');box=fragment.get('位置_像素')
    if type(index) is not int or index<1 or not isinstance(text,str) or len(text)>32767:
        raise ValueError('OCR 片段编号或原文无效')
    if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:
        raise ValueError('OCR 模型分数无效')
    if fragment.get('复核状态')!='待人工核对原图':
        raise ValueError('OCR 片段复核状态无效')
    return (index,row,col,association,text,float(score),_pixel_box_json(box),'待人工核对原图')


def run(image,table_json,output):
    image=Path(image).resolve();table_json=Path(table_json).resolve();output=Path(output).resolve()
    if len({str(image),str(table_json),str(output)})<3 or output.suffix.lower()!='.xlsx':raise ValueError('输入输出必须不同且输出为 XLSX')
    if not output.parent.is_dir():raise FileNotFoundError(f'输出目录不存在：{output.parent}')
    if os.path.lexists(output):raise FileExistsError(output)
    imagehash=sha(image);jsonhash=sha(table_json);data=json.loads(table_json.read_text(encoding='utf8'))
    if data.get('来源sha256')!=imagehash:raise ValueError('原图和识别结果哈希不一致')
    rows,cols=data.get('行数'),data.get('列数');cells=data.get('单元格');unassigned=data.get('未归属片段');ocr_count=data.get('OCR识别条数')
    if type(rows) is not int or type(cols) is not int or not (1<=rows<=100 and 1<=cols<=30) or not isinstance(cells,list) or len(cells)!=rows*cols or not isinstance(unassigned,list) or type(ocr_count) is not int or ocr_count<0:
        raise ValueError('网格数据无效或缺少 OCR 识别条数')
    w=Workbook()
    try:
        grid=w.active;grid.title='待核对表格'
        review=w.create_sheet('逐格复核');review.append(['行','列','识别原文','原图位置_像素','复核状态'])
        detail=w.create_sheet('识别片段明细')
        detail.append(['OCR结果序号','所属网格行','所属网格列','归属状态','识别原文','模型分数（仅供参考）','原图位置_像素','复核状态'])
        seen=set();expected=[];detail_rows=[]
        for c in cells:
            row,col,text,bbox,fragments=c.get('行'),c.get('列'),c.get('识别文本'),c.get('边界_像素'),c.get('片段')
            if type(row) is not int or type(col) is not int or not(1<=row<=rows and 1<=col<=cols) or (row,col) in seen or not isinstance(text,str) or len(text)>32767 or not isinstance(bbox,list) or len(bbox)!=4 or not isinstance(fragments,list):
                raise ValueError('单元格数据无效')
            seen.add((row,col));set_text(grid.cell(row,col),text)
            coordinate=json.dumps(bbox,ensure_ascii=False);review.append([row,col,text,coordinate,'待人工核对原图']);review.cell(review.max_row,3).data_type='s'
            expected.append((row,col,text if text else None,coordinate,'待人工核对原图'))
            cell_fragments=[]
            for fragment in fragments:
                item=_fragment_row(fragment,row,col,'已归入网格单元格')
                cell_fragments.append(item);detail_rows.append(item)
            if text!=' '.join(item[4] for item in cell_fragments):
                raise ValueError('单元格拼接文本与 OCR 片段明细不一致')
        if len(seen)!=rows*cols:raise ValueError('单元格缺失')
        for fragment in unassigned:
            detail_rows.append(_fragment_row(fragment,None,None,'未归属'))
        detail_rows.sort(key=lambda item:item[0])
        if len(detail_rows)!=ocr_count or [item[0] for item in detail_rows]!=list(range(1,ocr_count+1)):
            raise ValueError('OCR 片段存在缺失、重复或序号不连续')
        for item in detail_rows:
            detail.append(item)
            detail.cell(detail.max_row,5).data_type='s'
        other=w.create_sheet('未归属片段');other.append(['OCR结果序号','识别原文','模型分数（仅供参考）','位置_像素','复核状态'])
        for fragment in unassigned:
            index,row,col,association,text,score,coordinate,status=_fragment_row(fragment,None,None,'未归属')
            other.append([index,text,score,coordinate,status]);other.cell(other.max_row,2).data_type='s'
        note=w.create_sheet('说明');note.append(['项目','内容']);note.append(['原图文件名',image.name]);note.cell(2,2).data_type='s';note.append(['原图 SHA-256',imagehash]);note.append(['网格 JSON SHA-256',jsonhash]);note.append(['OCR 识别条数',ocr_count]);note.append(['适用限制','仅虚构样例；模型分数只作参考，不证明识别正确；网格、文字和空白格均须对照原图人工复核'])
        if sha(image)!=imagehash or sha(table_json)!=jsonhash:raise ValueError('源文件在处理期间变化')
        fd,temporary=tempfile.mkstemp(prefix='.ledger-grid-review-',suffix='.tmp.xlsx',dir=output.parent)
        try:
            with os.fdopen(fd,'wb') as stream:w.save(stream)
            check=load_workbook(temporary,read_only=True,data_only=False)
            try:
                if list(check['逐格复核'].values)[1:]!=expected:raise ValueError('复核清单回读不一致')
                for row,col,text,_,_ in expected:
                    if check['待核对表格'].cell(row,col).value!=text:raise ValueError('表格回读不一致')
                actual_detail=list(check['识别片段明细'].values)[1:]
                if actual_detail!=detail_rows:raise ValueError('OCR 片段明细回读不一致')
                actual_other=list(check['未归属片段'].values)[1:]
                wanted_other=[(v['OCR结果序号'],v['识别文本'] or None,float(v['模型分数']),_pixel_box_json(v['位置_像素']),'待人工核对原图') for v in unassigned]
                if actual_other!=wanted_other:raise ValueError('未归属片段回读不一致')
            finally:check.close()
            if sha(image)!=imagehash or sha(table_json)!=jsonhash:raise ValueError('源文件在处理期间变化')
            os.link(temporary,output)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
    finally:w.close()
    return len(cells),len(unassigned)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image');p.add_argument('table_json');p.add_argument('output');a=p.parse_args()
    print('待核对单元格、未归属片段:',run(a.image,a.table_json,a.output))
