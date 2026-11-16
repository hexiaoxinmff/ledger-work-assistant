"""Extract simple text-only DOCX tables to a traceable XLSX; no OCR."""
import argparse, hashlib, os, tempfile, zipfile
from xml.etree import ElementTree as ET
from openpyxl import Workbook, load_workbook

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

MAX_DOCX_BYTES = 100 * 1024 * 1024
MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_DOCX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_DOCX_DOCUMENT_XML_BYTES = 64 * 1024 * 1024
MAX_DOCX_ENTRIES = 10_000
MAX_DOCX_CELLS = 1_000_000
CHINESE_FINANCIAL_DIGITS = set("壹贰貳叁參肆伍陆陸柒捌玖零〇")
CHINESE_NUMBER_DIGITS = set("零〇一二两兩三四五六七八九十拾百佰千仟万萬亿億兆廿卅卌")
CHINESE_NUMBER_UNITS = set("十拾百佰千仟万萬亿億元圆圓角分厘")

def contains_number(text):
    if any(char.isdigit() for char in text):
        return True
    if any(char in CHINESE_FINANCIAL_DIGITS for char in text):
        return True
    if any(char in "廿卅卌" for char in text):
        return True
    return (any(char in CHINESE_NUMBER_DIGITS for char in text)
            and any(char in CHINESE_NUMBER_UNITS for char in text))


def check_docx_size(path, max_bytes=MAX_DOCX_BYTES):
    if os.path.getsize(path) > max_bytes:
        raise ValueError("DOCX 文件超过 100 MiB 上限")


def sha(path, max_bytes=MAX_DOCX_BYTES):
    check_docx_size(path, max_bytes)
    h = hashlib.sha256()
    total = 0
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1048576), b""):
            total += len(b)
            if total > max_bytes:
                raise ValueError("DOCX 文件在读取期间超过 100 MiB 上限")
            h.update(b)
    return h.hexdigest()

def extract(path):
    check_docx_size(path, MAX_DOCX_BYTES)
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        if len(entries) > MAX_DOCX_ENTRIES:
            raise ValueError("DOCX ZIP 条目超过安全上限")
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("DOCX ZIP 包含重复文件名")
        total_size = 0
        for entry in entries:
            if entry.flag_bits & 0x1:
                raise ValueError("不支持加密的 DOCX ZIP 条目")
            if entry.file_size > MAX_DOCX_MEMBER_BYTES:
                raise ValueError("DOCX ZIP 成员超过 128 MiB 上限")
            total_size += entry.file_size
            if total_size > MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES:
                raise ValueError("DOCX 解压后总大小超过 512 MiB 上限")
        document_info = next((entry for entry in entries if entry.filename == "word/document.xml"), None)
        if document_info is None:
            raise ValueError("DOCX 缺少 word/document.xml")
        if document_info.file_size > MAX_DOCX_DOCUMENT_XML_BYTES:
            raise ValueError("DOCX 正文 XML 超过 64 MiB 上限")
        document_xml = z.read(document_info)
    if b"<!DOCTYPE" in document_xml.upper() or b"<!ENTITY" in document_xml.upper():
        raise ValueError("DOCX XML 含 DTD 或实体声明，停止解析")
    root = ET.fromstring(document_xml)
    body = root.find(W + "body")
    if body is None: raise ValueError("无法读取文档正文")
    for control in body.iter(W + "sdt"):
        if control.find('.//' + W + 'tbl') is not None:
            raise ValueError("表格被内容控件包裹，存在不支持的特殊内容；请人工确认转换方式")
    tables = body.findall(W + "tbl")
    if not tables: raise ValueError("未发现正文表格；本工具不提取正文或 OCR")
    rows = []
    cell_count = 0
    for ti, tbl in enumerate(tables, 1):
        for tag in ('sym', 'sdt', 'fldChar', 'footnoteReference', 'endnoteReference', 'altChunk'):
            if tbl.find('.//' + W + tag) is not None:
                raise ValueError(f"第 {ti} 个表格包含特殊内容 {tag}，无法保证原文完整；请人工确认转换方式")
        if tbl.findall(".//" + W + "gridSpan") or tbl.findall(".//" + W + "vMerge") or tbl.findall(".//" + W + "tbl"):
            raise ValueError("合并单元格或嵌套表格需用其他方法处理")
        for ri, row in enumerate(tbl.findall(W + "tr"), 1):
            for ci, cell in enumerate(row.findall(W + "tc"), 1):
                cell_count += 1
                if cell_count > MAX_DOCX_CELLS:
                    raise ValueError("DOCX 单元格超过 100 万个安全处理上限")
                if any(cell.findall(".//" + W + tag) for tag in ("drawing", "pict", "object", "instrText", "fldSimple", "tab", "br", "cr", "ins", "del")):
                    raise ValueError("表格包含图片、域、制表符、换行或修订，无法安全提取")
                # Word may encode visible or semantically meaningful run content
                # outside w:t (for example noBreakHyphen/softHyphen). Refuse
                # unknown run children so identifiers/numbers are never silently joined.
                for run in cell.iter(W + "r"):
                    for child in run:
                        if child.tag not in (W + "rPr", W + "t"):
                            local = child.tag.rsplit("}", 1)[-1]
                            raise ValueError(f"表格包含不支持的 Word 行内节点 {local}，无法保证原文完整；请人工确认转换方式")
                if cell.find(".//{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent") is not None:
                    raise ValueError("表格包含 Word AlternateContent 替代内容，无法保证原文完整；请人工确认转换方式")
                paragraphs = ["".join(n.text or "" for n in para.iter(W + "t")) for para in cell.findall(W + "p")]
                text = "\n".join(paragraphs)
                if len(text) > 32767: raise ValueError("单元格文字超出 Excel 容量")
                rows.append((ti, ri, ci, text))
    return rows

def run(source, output):
    source = os.path.abspath(source)
    output = os.path.abspath(output)
    if os.path.realpath(source) == os.path.realpath(output):
        raise ValueError("输出不可覆盖输入")
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    parent = os.path.dirname(output)
    if not os.path.isdir(parent):
        raise FileNotFoundError(f"输出目录不存在：{parent}")
    if os.path.lexists(output):
        raise FileExistsError(output)

    check_docx_size(source, MAX_DOCX_BYTES)
    before = sha(source, MAX_DOCX_BYTES)
    rows = extract(source)
    wb = Workbook()
    fd, temporary = tempfile.mkstemp(
        prefix=".ledger-docx-", suffix=".xlsx", dir=parent
    )
    try:
        os.close(fd)
        try:
            ws = wb.active
            ws.title = "表格单元格"
            ws.append(["文档表序号", "表内行", "表内列", "读取原文（文本）"])
            for row in rows:
                ws.append(row)
                for cell in ws[ws.max_row]:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
            # Reconstruct table cell grid as text; original styling is not reproduced.
            for table_id in sorted({r[0] for r in rows}):
                grid = wb.create_sheet("表格" + str(table_id))
                for ti, ri, ci, value in rows:
                    if ti == table_id:
                        cell = grid.cell(row=ri, column=ci, value=value)
                        if isinstance(value, str):
                            cell.data_type = "s"
            audit = wb.create_sheet("数字复核")
            audit.append(["文档表序号", "表内行", "表内列", "含数字原文", "复核状态"])
            for ti, ri, ci, value in rows:
                if contains_number(value):
                    audit.append([ti, ri, ci, value, "待人工复核"])
                    audit.cell(audit.max_row, 4).data_type = "s"
            wb.save(temporary)
        finally:
            wb.close()

        if sha(source, MAX_DOCX_BYTES) != before:
            raise ValueError("输入处理期间发生变化，结果不可交付")
        check = load_workbook(temporary, read_only=True, data_only=False)
        try:
            actual = list(check.active.values)[1:]
            expected = [(a, b, c, d if d else None) for a, b, c, d in rows]
            if actual != expected:
                raise ValueError("输出明细与读取原文不一致")
            for ti, ri, ci, value in rows:
                actual_value = check["表格" + str(ti)].cell(row=ri, column=ci).value
                if actual_value != (value if value else None):
                    raise ValueError("结构表回读不一致")
            audit_actual = list(check["数字复核"].values)[1:]
            audit_expected = [
                (ti, ri, ci, value, "待人工复核")
                for ti, ri, ci, value in rows if contains_number(value)
            ]
            if audit_actual != audit_expected:
                raise ValueError("数字复核清单回读不一致")
        finally:
            check.close()
        # Hard-link publication is atomic and refuses to overwrite an existing path.
        os.link(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return len(rows)

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("source"); parser.add_argument("output")
    args=parser.parse_args(); print("已提取单元格数:", run(args.source,args.output))
