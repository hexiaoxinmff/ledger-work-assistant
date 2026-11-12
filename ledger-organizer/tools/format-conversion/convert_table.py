"""Local CSV/XLSX value conversion, with explicit limits and verification."""
import argparse, csv, hashlib, os, re, tempfile
from openpyxl import Workbook, load_workbook


def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def run(source,output,encoding='utf-8-sig',sheet=None,allow_display_loss=False,delimiter=None,expected_columns=None):
    if expected_columns is not None and (type(expected_columns) is not int or not 1<=expected_columns<=16384):raise ValueError('预期列数必须为 1 至 16384 的整数')
    if os.path.realpath(source)==os.path.realpath(output):raise ValueError('输出不可覆盖输入')
    before=sha(source); src=os.path.splitext(source)[1].lower(); dst=os.path.splitext(output)[1].lower()
    text_format=src if src in ('.csv','.tsv') else dst
    if delimiter not in (None,',',';','\t'):raise ValueError('分隔符只支持逗号、分号或制表符')
    if text_format=='.tsv' and delimiter not in (None,'\t'):raise ValueError('TSV 必须使用制表符')
    separator=delimiter if delimiter is not None else ('\t' if text_format=='.tsv' else ',')
    if src in ('.csv','.tsv') and dst=='.xlsx':
        if encoding not in ('utf-8','utf-8-sig','utf-16','gb18030','gbk'):raise ValueError('不支持该编码，请确认实际编码')
        with open(source,encoding=encoding,newline='') as f:rows=list(csv.reader(f,strict=True,delimiter=separator))
        if not rows:raise ValueError('CSV 为空')
        if any(len(r)!=len(rows[0]) for r in rows) or not rows[0]:raise ValueError('CSV 列数不一致或存在空行')
        if len(rows)>1048576 or len(rows[0])>16384 or any(len(v)>32767 for r in rows for v in r):raise ValueError('内容超过 Excel 容量')
        w=Workbook();ws=w.active;ws.title='转换结果'
        for row in rows:
            ws.append(row)
            for c in ws[ws.max_row]:
                if isinstance(c.value,str):c.data_type='s'
    elif src=='.xlsx' and dst in ('.csv','.tsv'):
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
    else:raise ValueError('仅支持 CSV/TSV 与 XLSX 互转')
    if expected_columns is not None and any(len(row)!=expected_columns for row in rows):
        raise ValueError(f'实际列数不符合预期 {expected_columns} 列，请核对分隔符、工作表及表头')
    # Stage beside the destination, verify, then publish without overwriting.
    # The temporary file may contain the same sensitive values as the source.
    parent=os.path.dirname(os.path.abspath(output))
    fd,tempname=tempfile.mkstemp(prefix='.ledger-conversion-',suffix='.tmp',dir=parent)
    try:
        if dst=='.xlsx':
            with os.fdopen(fd,'wb') as f:w.save(f)
            with open(tempname,'rb') as staged:
                check=load_workbook(staged,read_only=True,data_only=False)
                try:
                    actual=[[v if v is not None else '' for v in row] for row in check.active.iter_rows(values_only=True)]
                    if actual!=rows:raise ValueError('转换后回读不一致')
                finally:check.close()
        else:
            with os.fdopen(fd,'w',encoding='utf-8-sig',newline='') as f:csv.writer(f,delimiter=separator).writerows(rows)
            with open(tempname,encoding='utf-8-sig',newline='') as f:
                if list(csv.reader(f,strict=True,delimiter=separator))!=rows:raise ValueError('转换后回读不一致')
        if sha(source)!=before:raise ValueError('源文件发生变化，结果不可交付')
        os.link(tempname,output)
    finally:os.unlink(tempname)
    return len(rows)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('output');p.add_argument('--encoding',default='utf-8-sig');p.add_argument('--sheet');p.add_argument('--delimiter',choices=('comma','semicolon','tab'));p.add_argument('--expected-columns',type=int,help='按已确认的表结构核对列数');p.add_argument('--allow-display-loss',action='store_true',help='已确认接受 XLSX 数字/日期按底层值导出，不保留显示格式');a=p.parse_args()
    delimiter={'comma':',','semicolon':';','tab':'\t'}.get(a.delimiter)
    print('转换完成，行数:',run(a.source,a.output,a.encoding,a.sheet,a.allow_display_loss,delimiter,a.expected_columns))
    if a.output.lower().endswith(('.csv','.tsv')):print('注意：CSV/TSV 不保存单元格类型或格式；用表格软件打开时请将编号等字段按文本导入，并对照原表复核。')
