"""Export experimental OCR grid JSON to an all-pending review workbook."""
import argparse, hashlib, json
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


def run(image,table_json,output):
    image=Path(image).resolve();table_json=Path(table_json).resolve();output=Path(output).resolve()
    if len({str(image),str(table_json),str(output)})<3 or output.suffix.lower()!='.xlsx':raise ValueError('输入输出必须不同且输出为 XLSX')
    imagehash=sha(image);jsonhash=sha(table_json);data=json.loads(table_json.read_text(encoding='utf8'))
    if data.get('来源sha256')!=imagehash:raise ValueError('原图和识别结果哈希不一致')
    rows,cols=data.get('行数'),data.get('列数');cells=data.get('单元格');unassigned=data.get('未归属片段')
    if not isinstance(rows,int) or not isinstance(cols,int) or not (1<=rows<=100 and 1<=cols<=30) or not isinstance(cells,list) or len(cells)!=rows*cols or not isinstance(unassigned,list):raise ValueError('网格数据无效')
    w=Workbook();grid=w.active;grid.title='待核对表格'; review=w.create_sheet('逐格复核');review.append(['行','列','识别原文','原图位置_像素','复核状态'])
    seen=set();expected=[]
    for c in cells:
        row,col=c.get('行'),c.get('列');text=c.get('识别文本');bbox=c.get('边界_像素')
        if not isinstance(row,int) or not isinstance(col,int) or not(1<=row<=rows and 1<=col<=cols) or (row,col) in seen or not isinstance(text,str) or not isinstance(bbox,list) or len(bbox)!=4:raise ValueError('单元格数据无效')
        seen.add((row,col));set_text(grid.cell(row,col),text)
        coordinate=json.dumps(bbox,ensure_ascii=False);review.append([row,col,text,coordinate,'待人工核对原图']);review.cell(review.max_row,3).data_type='s'
        expected.append((row,col,text if text else None,coordinate,'待人工核对原图'))
    if len(seen)!=rows*cols:raise ValueError('单元格缺失')
    other=w.create_sheet('未归属片段');other.append(['识别原文','位置_像素','复核状态'])
    for fragment in unassigned:
        text=fragment.get('识别文本');box=fragment.get('位置_像素')
        if not isinstance(text,str) or not isinstance(box,list):raise ValueError('未归属片段无效')
        other.append([text,json.dumps(box,ensure_ascii=False),'待人工核对原图']);other.cell(other.max_row,1).data_type='s'
    note=w.create_sheet('说明');note.append(['项目','内容']);note.append(['原图文件名',image.name]);note.cell(2,2).data_type='s';note.append(['原图 SHA-256',imagehash]);note.append(['网格 JSON SHA-256',jsonhash]);note.append(['适用限制','仅虚构样例；网格和文字均须人工复核，空白不代表原图为空'])
    with open(output,'xb') as f:w.save(f)
    if sha(image)!=imagehash or sha(table_json)!=jsonhash:raise ValueError('源文件在处理期间变化')
    check=load_workbook(output,read_only=True,data_only=False)
    try:
        if list(check['逐格复核'].values)[1:]!=expected:raise ValueError('复核清单回读不一致')
        for row,col,text,_,_ in expected:
            if check['待核对表格'].cell(row,col).value!=text:raise ValueError('表格回读不一致')
        actual_other=list(check['未归属片段'].values)[1:]
        wanted_other=[(v['识别文本'] or None,json.dumps(v['位置_像素'],ensure_ascii=False),'待人工核对原图') for v in unassigned]
        if actual_other!=wanted_other:raise ValueError('未归属片段回读不一致')
    finally:check.close()
    return len(cells),len(unassigned)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image');p.add_argument('table_json');p.add_argument('output');a=p.parse_args()
    print('待核对单元格、未归属片段:',run(a.image,a.table_json,a.output))
