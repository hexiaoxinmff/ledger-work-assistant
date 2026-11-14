"""Extract simple text-only DOCX tables to a traceable XLSX; no OCR."""
import argparse, hashlib, os, zipfile
from xml.etree import ElementTree as ET
from openpyxl import Workbook, load_workbook

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1048576), b""): h.update(b)
    return h.hexdigest()

def extract(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    if body is None: raise ValueError("无法读取文档正文")
    for control in body.iter(W + "sdt"):
        if control.find('.//' + W + 'tbl') is not None:
            raise ValueError("表格被内容控件包裹，存在不支持的特殊内容；请人工确认转换方式")
    tables = body.findall(W + "tbl")
    if not tables: raise ValueError("未发现正文表格；本工具不提取正文或 OCR")
    rows = []
    for ti, tbl in enumerate(tables, 1):
        for tag in ('sym', 'sdt', 'fldChar', 'footnoteReference', 'endnoteReference', 'altChunk'):
            if tbl.find('.//' + W + tag) is not None:
                raise ValueError(f"第 {ti} 个表格包含特殊内容 {tag}，无法保证原文完整；请人工确认转换方式")
        if tbl.findall(".//" + W + "gridSpan") or tbl.findall(".//" + W + "vMerge") or tbl.findall(".//" + W + "tbl"):
            raise ValueError("合并单元格或嵌套表格需用其他方法处理")
        for ri, row in enumerate(tbl.findall(W + "tr"), 1):
            for ci, cell in enumerate(row.findall(W + "tc"), 1):
                if any(cell.findall(".//" + W + tag) for tag in ("drawing", "pict", "object", "instrText", "fldSimple", "tab", "br", "cr", "ins", "del")):
                    raise ValueError("表格包含图片、域、制表符、换行或修订，无法安全提取")
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

    before = sha(source)
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
                if any(ch.isdigit() for ch in value):
                    audit.append([ti, ri, ci, value, "待人工复核"])
                    audit.cell(audit.max_row, 4).data_type = "s"
            wb.save(temporary)
        finally:
            wb.close()

        if sha(source) != before:
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
                for ti, ri, ci, value in rows if any(ch.isdigit() for ch in value)
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
