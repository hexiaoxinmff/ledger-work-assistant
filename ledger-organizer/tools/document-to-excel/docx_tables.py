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
    tables = body.findall(W + "tbl")
    if not tables: raise ValueError("未发现正文表格；本工具不提取正文或 OCR")
    rows = []
    for ti, tbl in enumerate(tables, 1):
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
    if os.path.realpath(source) == os.path.realpath(output): raise ValueError("输出不可覆盖输入")
    before = sha(source); rows = extract(source)
    wb = Workbook(); ws = wb.active; ws.title = "表格单元格"
    ws.append(["文档表序号", "表内行", "表内列", "读取原文（文本）"])
    for row in rows:
        ws.append(row)
        for cell in ws[ws.max_row]:
            if isinstance(cell.value, str): cell.data_type = "s"
    with open(output, "xb") as f: wb.save(f)
    if sha(source) != before: raise ValueError("输入处理期间发生变化，结果不可交付")
    check = load_workbook(output, read_only=True, data_only=False)
    try:
        actual = list(check.active.values)[1:]
        expected = [(a,b,c,d if d else None) for a,b,c,d in rows]
        if actual != expected: raise ValueError("输出回读与读取原文不一致")
    finally: check.close()
    return len(rows)

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("source"); parser.add_argument("output")
    args=parser.parse_args(); print("已提取单元格数:", run(args.source,args.output))
