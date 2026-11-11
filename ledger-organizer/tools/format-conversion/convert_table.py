"""Local CSV/XLSX value conversion, with explicit limits and verification."""
import argparse, csv, hashlib, os, re
from openpyxl import Workbook, load_workbook


def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def run(source,output,encoding='utf-8-sig',sheet=None,allow_display_loss=False):
    if os.path.realpath(source)==os.path.realpath(output):raise ValueError('输出不可覆盖输入')
    before=sha(source); src=os.path.splitext(source)[1].lower(); dst=os.path.splitext(output)[1].lower()
    if (src,dst)==('.csv','.xlsx'):
        if encoding not in ('utf-8','utf-8-sig','utf-16','gb18030','gbk'):raise ValueError('不支持该编码，请确认实际编码')
        with open(source,encoding=encoding,newline='') as f:rows=list(csv.reader(f,strict=True))
        if not rows:raise ValueError('CSV 为空')
        if any(len(r)!=len(rows[0]) for r in rows) or not rows[0]:raise ValueError('CSV 列数不一致或存在空行')
        if len(rows)>1048576 or len(rows[0])>16384 or any(len(v)>32767 for r in rows for v in r):raise ValueError('内容超过 Excel 容量')
        w=Workbook();ws=w.active;ws.title='转换结果'
        for row in rows:
            ws.append(row)
            for c in ws[ws.max_row]:
                if isinstance(c.value,str):c.data_type='s'
        with open(output,'xb') as f:w.save(f)
        check=load_workbook(output,read_only=True,data_only=False)
        try:
            actual=[[v if v is not None else '' for v in row] for row in check.active.iter_rows(values_only=True)]
            if actual!=rows:raise ValueError('转换后回读不一致')
        finally:check.close()
    elif (src,dst)==('.xlsx','.csv'):
        w=load_workbook(source,read_only=False,data_only=False)
        try:
            if sheet is None and len(w.sheetnames)!=1:raise ValueError('多个工作表，请指定 --sheet')
            if sheet is not None and sheet not in w.sheetnames:raise ValueError('指定的工作表不存在')
            ws=w[sheet] if sheet else w.active
            if ws.merged_cells.ranges:raise ValueError('存在合并单元格，请先人工确认处理方式')
            if ws.max_row*ws.max_column>1000000:raise ValueError('表格范围过大，请缩小范围')
            rows=[]
            for row in ws.iter_rows():
                line=[]
                for c in row:
                    if c.data_type in ('f','e'):raise ValueError('存在公式或错误值，不能安全转为 CSV')
                    if (c.data_type=='d' or (c.data_type=='n' and c.value is not None and c.number_format.lower()!='general')) and not allow_display_loss:
                        raise ValueError(f'{c.coordinate} 的数字或日期显示依赖格式；CSV 无法保存显示格式。请核对原表，如接受导出底层值可指定 --allow-display-loss')
                    v='' if c.value is None else str(c.value)
                    # CSV opened in spreadsheet software must not silently execute formulas.
                    if v.startswith(('=','+','@','\t','\r')) or (v.startswith('-') and not re.fullmatch(r'-\d+(?:\.\d+)?',v)):
                        raise ValueError('存在可能被电子表格执行的文本，需人工处理')
                    line.append(v)
                rows.append(line)
        finally:w.close()
        with open(output,'x',encoding='utf-8-sig',newline='') as f:csv.writer(f).writerows(rows)
        with open(output,encoding='utf-8-sig',newline='') as f:
            if list(csv.reader(f,strict=True))!=rows:raise ValueError('转换后回读不一致')
    else:raise ValueError('仅支持 CSV → XLSX 或 XLSX → CSV')
    if sha(source)!=before:raise ValueError('源文件发生变化，结果不可交付')
    return len(rows)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('output');p.add_argument('--encoding',default='utf-8-sig');p.add_argument('--sheet');p.add_argument('--allow-display-loss',action='store_true',help='已确认接受 XLSX 数字/日期按底层值导出，不保留显示格式');a=p.parse_args()
    print('转换完成，行数:',run(a.source,a.output,a.encoding,a.sheet,a.allow_display_loss))
    if a.output.lower().endswith('.csv'):print('注意：CSV 不保存单元格类型或格式；用表格软件打开时请将编号等字段按文本导入，并对照原表复核。')
