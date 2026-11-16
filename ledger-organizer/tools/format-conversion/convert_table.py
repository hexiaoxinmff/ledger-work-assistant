"""Local CSV/XLSX value conversion, with explicit limits and verification."""
import argparse, csv, hashlib, itertools, json, os, posixpath, re, tempfile, unicodedata, zipfile
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell


def sha(path, max_bytes=None):
    if max_bytes is not None and os.path.getsize(path)>max_bytes:
        raise ValueError('源文件超过大小上限，未开始哈希')
    h=hashlib.sha256()
    total=0
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):
            total+=len(chunk)
            if max_bytes is not None and total>max_bytes:
                raise ValueError('源文件在哈希期间超过大小上限')
            h.update(chunk)
    return h.hexdigest()



MAX_CSV_BYTES = 100 * 1024 * 1024
MAX_CSV_RECORD_CHARS = 1_048_576
MAX_CSV_PHYSICAL_LINE_CHARS = 65_536
MAX_CSV_CELLS = 10_000_000


class _BoundedCsvLines:
    """Bound each physical line and logical CSV record before csv.reader allocates cells."""
    def __init__(self, stream):
        self.stream = stream
        self.record_chars = 0

    def __iter__(self):
        return self

    def __next__(self):
        line = self.stream.readline(MAX_CSV_PHYSICAL_LINE_CHARS + 1)
        if line == "":
            raise StopIteration
        if len(line) > MAX_CSV_PHYSICAL_LINE_CHARS:
            raise ValueError("CSV 单行超过 65536 个字符上限")
        self.record_chars += len(line)
        if self.record_chars > MAX_CSV_RECORD_CHARS:
            raise ValueError("CSV 单条记录超过 1048576 个字符上限")
        return line

    def finish_record(self):
        self.record_chars = 0


def _csv_rows(stream, separator):
    lines = _BoundedCsvLines(stream)
    reader = csv.reader(lines, strict=True, delimiter=separator)
    for row in reader:
        lines.finish_record()
        yield row


def _csv_to_write_only_workbook(source, encoding, separator, expected_columns):
    if os.path.getsize(source) > MAX_CSV_BYTES:
        raise ValueError("CSV 文件超过 100 MiB 上限")
    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet("转换结果")
    row_count = 0
    column_count = None
    cell_count = 0
    try:
        with open(source, encoding=encoding, newline="") as stream:
            for row in _csv_rows(stream, separator):
                if row_count == 0:
                    column_count = len(row)
                    if column_count == 0:
                        raise ValueError("CSV 列数不一致或存在空行")
                    if column_count > 16384:
                        raise ValueError("内容超过 Excel 容量")
                    if expected_columns is not None and column_count != expected_columns:
                        raise ValueError(f"实际列数不符合预期 {expected_columns} 列，请核对分隔符、工作表及表头")
                if len(row) != column_count:
                    raise ValueError("CSV 列数不一致或存在空行")
                if any(len(value) > 32767 for value in row):
                    raise ValueError("内容超过 Excel 容量")
                row_count += 1
                cell_count += column_count
                if row_count > 1048576 or cell_count > MAX_CSV_CELLS:
                    raise ValueError("CSV 行数或单元格数超过安全处理上限")
                cells = []
                for value in row:
                    cell = WriteOnlyCell(worksheet, value=value)
                    cell.data_type = "s"
                    cells.append(cell)
                worksheet.append(cells)
        if row_count == 0:
            raise ValueError("CSV 为空")
    except Exception:
        worksheet.close()
        workbook.close()
        raise
    return workbook, row_count, column_count


MAX_XLSX_BYTES = 100 * 1024 * 1024
MAX_XLSX_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_XLSX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_XLSX_SHARED_STRINGS_BYTES = 16 * 1024 * 1024
MAX_XLSX_ENTRIES = 10000
MAX_XLSX_METADATA_BYTES = 4 * 1024 * 1024


def _inspect_xlsx_archive(source, requested_sheet):
    if os.path.getsize(source) > MAX_XLSX_BYTES:
        raise ValueError("XLSX 文件超过 100 MiB 上限")
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_XLSX_ENTRIES:
                raise ValueError("XLSX ZIP 条目超过安全上限")
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("XLSX ZIP 包含重复文件名")
            total_size = 0
            for entry in entries:
                if entry.flag_bits & 0x1:
                    raise ValueError("不支持加密的 XLSX ZIP 条目")
                if entry.file_size > MAX_XLSX_MEMBER_BYTES:
                    raise ValueError("XLSX 内部文件超过 128 MiB 上限")
                if entry.filename == "xl/sharedStrings.xml" and entry.file_size > MAX_XLSX_SHARED_STRINGS_BYTES:
                    raise ValueError("XLSX 共享字符串表超过 16 MiB 上限")
                total_size += entry.file_size
                if total_size > MAX_XLSX_TOTAL_UNCOMPRESSED_BYTES:
                    raise ValueError("XLSX 解压后总大小超过 512 MiB 上限")
            by_name = {entry.filename: entry for entry in entries}
            workbook_info = by_name.get("xl/workbook.xml")
            rels_info = by_name.get("xl/_rels/workbook.xml.rels")
            if workbook_info is None or rels_info is None:
                raise ValueError("XLSX 缺少工作簿结构文件")
            if workbook_info.file_size > MAX_XLSX_METADATA_BYTES or rels_info.file_size > MAX_XLSX_METADATA_BYTES:
                raise ValueError("XLSX 工作簿元数据超过 4 MiB 上限")
            workbook_root = ET.fromstring(archive.read(workbook_info))
            rels_root = ET.fromstring(archive.read(rels_info))
            relation_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
            package_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
            rels = {
                rel.attrib.get("Id"): rel
                for rel in rels_root.findall(package_ns + "Relationship")
            }
            sheets = []
            for node in workbook_root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
                name = node.attrib.get("name")
                relation_id = node.attrib.get(relation_ns + "id")
                relation = rels.get(relation_id)
                if not name or relation is None or relation.attrib.get("TargetMode") == "External":
                    raise ValueError("XLSX 工作表关系无效")
                target = relation.attrib.get("Target", "")
                sheet_path = (
                    posixpath.normpath(target.lstrip("/"))
                    if target.startswith("/")
                    else posixpath.normpath(posixpath.join("xl", target))
                )
                if not sheet_path.startswith("xl/") or sheet_path not in by_name:
                    raise ValueError("XLSX 工作表路径无效")
                sheets.append((name, sheet_path))
            if not sheets:
                raise ValueError("XLSX 未包含工作表")
            if requested_sheet is None:
                if len(sheets) != 1:
                    raise ValueError("多个工作表，请指定 --sheet")
                selected = sheets[0]
            else:
                selected = next((item for item in sheets if item[0] == requested_sheet), None)
                if selected is None:
                    raise ValueError("指定的工作表不存在")
            sheet_info = by_name[selected[1]]
            if sheet_info.file_size > MAX_XLSX_MEMBER_BYTES:
                raise ValueError("工作表内容超过 128 MiB 上限")
            pattern = re.compile(rb"<(?:[A-Za-z_][A-Za-z0-9_.-]*:)?mergeCells(?=[\s>/])")
            tail = b""
            with archive.open(sheet_info) as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    data = tail + chunk
                    if pattern.search(data):
                        raise ValueError("存在合并单元格，请先人工确认处理方式")
                    tail = data[-64:]
            return [name for name, _ in sheets]
    except zipfile.BadZipFile as exc:
        raise ValueError("XLSX ZIP 结构无效或损坏") from exc


def _xlsx_cell_text(cell, allow_display_loss):
    if cell.data_type in ('f','e'):
        raise ValueError('存在公式或错误值，不能安全转为 CSV')
    if isinstance(cell.value,str) and len(cell.value)>32767:
        raise ValueError(f'{cell.coordinate} 的文本超过 Excel 单元格容量')
    if isinstance(cell.value,(int,float)) and not isinstance(cell.value,bool):
        try:
            significant=len(Decimal(str(cell.value)).normalize().as_tuple().digits)
        except (InvalidOperation,ValueError):
            significant=0
        if significant>15:
            raise ValueError(f'{cell.coordinate} 的数值超过 15 位有效数字，Excel 数值可能已丢失精度；请对照原始资料，将已核实的编号/数值按文本保存后再转换')
    if (cell.data_type=='d' or (cell.data_type=='n' and cell.value is not None and cell.number_format.lower()!='general')) and not allow_display_loss:
        raise ValueError(f'{cell.coordinate} 的数字或日期显示依赖格式；CSV 无法保存显示格式。请核对原表，如接受导出底层值可指定 --allow-display-loss')
    value='' if cell.value is None else str(cell.value)
    if _unsafe_csv_formula_text(value):
        raise ValueError('存在可能被电子表格执行的文本（含前导空白后的公式前缀），需人工处理')
    return value


def _xlsx_csv_rows(source, sheet, allow_display_loss, expected_columns):
    """Preflight dimensions, then yield validated/padded rows without retaining the sheet."""
    workbook=load_workbook(source,read_only=True,data_only=False)
    try:
        worksheet=workbook[sheet] if sheet else workbook.active
        worksheet.reset_dimensions()
        row_count=0
        max_columns=0
        for row in worksheet.iter_rows():
            if len(row)>16384:
                raise ValueError('工作表列数超过 Excel 容量')
            row_count+=1
            max_columns=max(max_columns,len(row))
            if row_count>1048576:
                raise ValueError('表格行数超过 Excel 容量')
            if row_count*max_columns>1000000:
                raise ValueError('表格范围过大，请缩小范围（最多 100 万个单元格）')
            for cell in row:
                _xlsx_cell_text(cell,allow_display_loss)
        if row_count*max_columns>1000000:
            raise ValueError('表格范围过大，请缩小范围（最多 100 万个单元格）')
        if expected_columns is not None and max_columns!=expected_columns:
            raise ValueError(f'实际列数不符合预期 {expected_columns} 列，请核对分隔符、工作表及表头')
        worksheet.reset_dimensions()
        emitted=0
        for row in worksheet.iter_rows():
            emitted+=1
            if emitted>row_count:
                raise ValueError('工作表在转换期间发生变化')
            values=[_xlsx_cell_text(cell,allow_display_loss) for cell in row]
            values.extend(['']*(max_columns-len(values)))
            yield values
        if emitted!=row_count:
            raise ValueError('工作表在转换期间发生变化')
    finally:
        workbook.close()


def _update_row_digest(digest, row):
    digest.update(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
    digest.update(b'\\n')


def _unsafe_csv_formula_text(value):
    candidate = value.lstrip()
    leading = value[:len(value) - len(candidate)]
    candidate = unicodedata.normalize('NFKC', candidate)
    if any(ord(char) < 0x20 for char in leading):
        return True
    if candidate.startswith(('=', '+', '@')):
        return True
    if candidate.startswith('-') and not (
        re.fullmatch(r'-(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', candidate)
        or re.fullmatch(r'-\d+(?:\.\d+)?[eE][+\-]?\d+', candidate)
    ):
        return True
    return False


def run(source,output,encoding='utf-8-sig',sheet=None,allow_display_loss=False,delimiter=None,expected_columns=None):
    if expected_columns is not None and (type(expected_columns) is not int or not 1<=expected_columns<=16384):raise ValueError('预期列数必须为 1 至 16384 的整数')
    if os.path.realpath(source)==os.path.realpath(output):raise ValueError('输出不可覆盖输入')
    src=os.path.splitext(source)[1].lower(); dst=os.path.splitext(output)[1].lower()
    text_format=src if src in ('.csv','.tsv') else dst
    if delimiter not in (None,',',';','\t'):raise ValueError('分隔符只支持逗号、分号或制表符')
    if text_format=='.tsv' and delimiter not in (None,'\t'):raise ValueError('TSV 必须使用制表符')
    separator=delimiter if delimiter is not None else ('\t' if text_format=='.tsv' else ',')
    csv_to_xlsx = src in ('.csv','.tsv') and dst=='.xlsx'
    if csv_to_xlsx and os.path.getsize(source)>MAX_CSV_BYTES:raise ValueError('CSV 文件超过 100 MiB 上限')
    xlsx_to_csv = src=='.xlsx' and dst in ('.csv','.tsv')
    if xlsx_to_csv:
        xlsx_sheetnames=_inspect_xlsx_archive(source,sheet)
    if not csv_to_xlsx and not xlsx_to_csv:raise ValueError('仅支持 CSV/TSV 与 XLSX 互转')
    input_limit=MAX_CSV_BYTES if csv_to_xlsx else MAX_XLSX_BYTES
    before=sha(source,input_limit)
    csv_row_count = csv_column_count = None
    if csv_to_xlsx:
        if encoding not in ('utf-8','utf-8-sig','utf-16','gb18030','gbk'):raise ValueError('不支持该编码，请确认实际编码')
        w,csv_row_count,csv_column_count=_csv_to_write_only_workbook(source,encoding,separator,expected_columns)
        rows=None
    elif xlsx_to_csv:
        rows=None
    else:raise ValueError('仅支持 CSV/TSV 与 XLSX 互转')
    if expected_columns is not None and rows is not None and any(len(row)!=expected_columns for row in rows):
        raise ValueError(f'实际列数不符合预期 {expected_columns} 列，请核对分隔符、工作表及表头')
    # Stage beside the destination, verify, then publish without overwriting.
    # The temporary file may contain the same sensitive values as the source.
    parent=os.path.dirname(os.path.abspath(output))
    manifest_path = output + '.manifest.json'
    if os.path.realpath(source) == os.path.realpath(manifest_path):
        raise ValueError('运行清单不可覆盖输入')
    if os.path.lexists(output) or os.path.lexists(manifest_path):
        raise FileExistsError('输出文件或运行清单已存在，请使用新路径')
    fd,tempname=tempfile.mkstemp(prefix='.ledger-conversion-',suffix='.tmp',dir=parent)
    try:
        if dst=='.xlsx':
            try:
                with os.fdopen(fd,'wb') as f:w.save(f)
            except Exception:
                if csv_to_xlsx:
                    for worksheet in w.worksheets:
                        try:worksheet.close()
                        except Exception:pass
                    try:w.close()
                    except Exception:pass
                raise
            with open(tempname,'rb') as staged:
                check=load_workbook(staged,read_only=True,data_only=False)
                try:
                    actual_rows=check.active.iter_rows(values_only=True)
                    if csv_to_xlsx:
                        sentinel=object()
                        with open(source,encoding=encoding,newline='') as original:
                            expected_rows=_csv_rows(original,separator)
                            for expected,actual in itertools.zip_longest(expected_rows,actual_rows,fillvalue=sentinel):
                                if expected is sentinel or actual is sentinel:
                                    raise ValueError('转换后行数回读不一致')
                                normalized=['' if value is None else value for value in actual]
                                normalized.extend([''] * (csv_column_count-len(normalized)))
                                if normalized!=expected:raise ValueError('转换后回读不一致')
                    else:
                        actual=[[v if v is not None else '' for v in row] for row in actual_rows]
                        if actual!=rows:raise ValueError('转换后回读不一致')
                finally:check.close()
        else:
            xlsx_row_count=0
            expected_digest=hashlib.sha256()
            with os.fdopen(fd,'w',encoding='utf-8-sig',newline='') as f:
                writer=csv.writer(f,delimiter=separator)
                if xlsx_to_csv:
                    def checked_rows():
                        nonlocal xlsx_row_count
                        for row in _xlsx_csv_rows(source,sheet,allow_display_loss,expected_columns):
                            _update_row_digest(expected_digest,row)
                            xlsx_row_count+=1
                            yield row
                    writer.writerows(checked_rows())
                else:
                    writer.writerows(rows)
            with open(tempname,encoding='utf-8-sig',newline='') as f:
                reader=csv.reader(f,strict=True,delimiter=separator)
                if xlsx_to_csv:
                    actual_digest=hashlib.sha256()
                    actual_count=0
                    for row in reader:
                        _update_row_digest(actual_digest,row)
                        actual_count+=1
                    if actual_count!=xlsx_row_count or actual_digest.digest()!=expected_digest.digest():
                        raise ValueError('转换后回读不一致')
                elif list(reader)!=rows:
                    raise ValueError('转换后回读不一致')
        if sha(source,input_limit)!=before:raise ValueError('源文件发生变化，结果不可交付')
        output_reserved = False
        manifest_reserved = False
        manifest_temp = None
        try:
            os.link(tempname, output)
            output_reserved = True
            output_sha = sha(output)
            row_count = csv_row_count if csv_to_xlsx else xlsx_row_count
            manifest = {
                "format_conversion_version": "0.1",
                "source_path": os.path.abspath(source),
                "output_path": os.path.abspath(output),
                "source_sha256": before,
                "output_sha256": output_sha,
                "source_format": src,
                "output_format": dst,
                "rows": row_count,
                "columns": csv_column_count if csv_to_xlsx else expected_columns,
                "encoding": encoding if csv_to_xlsx else None,
                "delimiter": separator,
                "sheet": sheet if xlsx_to_csv else None,
            }
            mfd, manifest_temp = tempfile.mkstemp(
                prefix='.ledger-conversion-manifest-', suffix='.tmp', dir=parent
            )
            with os.fdopen(mfd, 'w', encoding='utf-8') as stream:
                json.dump(manifest, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(manifest_temp, manifest_path)
            manifest_reserved = True
        finally:
            if manifest_temp and os.path.exists(manifest_temp):
                os.unlink(manifest_temp)
            if output_reserved and not manifest_reserved:
                try:
                    os.unlink(output)
                except FileNotFoundError:
                    pass
    finally:
        if os.path.exists(tempname):
            os.unlink(tempname)
    return csv_row_count if csv_to_xlsx else (xlsx_row_count if xlsx_to_csv else len(rows))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('output');p.add_argument('--encoding',default='utf-8-sig');p.add_argument('--sheet');p.add_argument('--delimiter',choices=('comma','semicolon','tab'));p.add_argument('--expected-columns',type=int,help='按已确认的表结构核对列数');p.add_argument('--allow-display-loss',action='store_true',help='已确认接受 XLSX 数字/日期按底层值导出，不保留显示格式');a=p.parse_args()
    delimiter={'comma':',','semicolon':';','tab':'\t'}.get(a.delimiter)
    print('转换完成，行数:',run(a.source,a.output,a.encoding,a.sheet,a.allow_display_loss,delimiter,a.expected_columns))
    if a.output.lower().endswith(('.csv','.tsv')):print('注意：CSV/TSV 不保存单元格类型或格式；用表格软件打开时请将编号等字段按文本导入，并对照原表复核。')
