"""Extract an existing PDF text layer into a source-traceable review workbook."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import os
from pathlib import Path
import re
import tempfile

import pypdfium2 as pdfium
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font

MAX_PAGES = 200
MAX_TOTAL_CHARS = 500_000
TEXT_CHUNK = 30_000
NUMBER = re.compile(
    r"(?<![\w.])(?:\(\s*\d[\d,]*(?:\.\d+)?\s*\)|"
    r"[+\-−－]?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?|"
    r"[+\-−－]?\s*\d+(?:\.\d+)?)(?:%|％)?"
)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_text(value):
    for char in value:
        code = ord(char)
        if (code < 0x20 and char not in "\t\n\r") or 0xD800 <= code <= 0xDFFF:
            raise ValueError("PDF 提取文本含 Excel/XML 不支持的控制字符；停止以免静默改写原文")
    return value


def _append_text(cell, value):
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"


def _extract(pdf_path):
    document = pdfium.PdfDocument(str(pdf_path))
    pages = []
    try:
        count = len(document)
        if not 1 <= count <= MAX_PAGES:
            raise ValueError(f"仅处理 1–{MAX_PAGES} 页 PDF")
        total_chars = 0
        any_text = False
        for page_number in range(1, count + 1):
            page = document[page_number - 1]
            text_page = None
            try:
                text_page = page.get_textpage()
                text = _safe_text(text_page.get_text_bounded())
            finally:
                if text_page is not None:
                    text_page.close()
                page.close()
            total_chars += len(text)
            if total_chars > MAX_TOTAL_CHARS:
                raise ValueError(f"PDF 文字层超过 {MAX_TOTAL_CHARS} 个字符的安全处理上限")
            has_text = bool(text.strip())
            any_text = any_text or has_text
            candidates = []
            for match in NUMBER.finditer(text):
                start, end = match.span()
                candidates.append((start, match.group(0), text[max(0, start - 50):min(len(text), end + 50)]))
            pages.append({"page": page_number, "text": text, "has_text": has_text, "candidates": candidates})
        if not any_text:
            raise ValueError("未发现可提取的 PDF 文字层；文件可能是扫描件，请走 OCR 人工复核流程")
        return pages
    finally:
        document.close()


def _write_workbook(path, source_name, source_hash, pages):
    workbook = Workbook()
    status = workbook.active
    status.title = "页码状态"
    raw = workbook.create_sheet("页面原文")
    numbers = workbook.create_sheet("数字候选")
    info = workbook.create_sheet("运行说明")

    status_rows = [["页码", "提取字符数", "文字层状态", "复核说明"]]
    raw_rows = [["页码", "分块序号", "提取文本字符起始偏移", "提取文本字符结束偏移", "PDF 提取原文"]]
    number_rows = [["页码", "提取文本字符偏移", "数字候选原文", "上下文（PDF 提取原文）", "状态"]]
    for page in pages:
        if page["has_text"]:
            status_rows.append([page["page"], len(page["text"]), "已提取文字层", "不提取图片文字、矢量转曲文字或批注；顺序与版面未核验，请对照 PDF 原页复核"])
            for chunk_index, start in enumerate(range(0, len(page["text"]), TEXT_CHUNK), 1):
                end = min(len(page["text"]), start + TEXT_CHUNK)
                raw_rows.append([page["page"], chunk_index, start, end, page["text"][start:end]])
            for start, candidate, context in page["candidates"]:
                number_rows.append([page["page"], start, candidate, context, "待人工逐字符核对原页"])
        else:
            status_rows.append([page["page"], 0, "未发现文字层", "可能是扫描页、空白页或字体编码异常；不得当作空白业务页"])

    info_rows = [
        ["项目", "值"],
        ["来源文件名", source_name],
        ["来源 SHA-256", source_hash],
        ["PDF 页数", len(pages)],
        ["含可提取文字页数", sum(page["has_text"] for page in pages)],
        ["数字候选数", sum(len(page["candidates"]) for page in pages)],
        ["提取工具", f"pypdfium2 {importlib.metadata.version('pypdfium2')}"],
        ["生成时间 UTC", datetime.now(timezone.utc).isoformat()],
        ["处理边界", "仅提取 PDF 已有文字层；不做 OCR、不恢复表格列、不解释金额或业务含义。"],
        ["复核要求", "按页码对照原 PDF，核对文字顺序、数字、标点、空白及扫描页；图片文字、矢量转曲文字和批注可能未提取，所有数字候选均待复核。"],
        ["数据安全", "源 PDF 只读；输出为新文件。中断可能留下临时文件，需按源资料保护要求检查。"],
    ]

    for worksheet, rows in ((status, status_rows), (raw, raw_rows), (numbers, number_rows), (info, info_rows)):
        for row in rows:
            worksheet.append(row)
            for cell in worksheet[worksheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        for cell in worksheet[1]:
            cell.font = Font(bold=True)
    status.column_dimensions["A"].width = 10
    status.column_dimensions["B"].width = 15
    status.column_dimensions["C"].width = 20
    status.column_dimensions["D"].width = 65
    raw.column_dimensions["A"].width = 10
    raw.column_dimensions["B"].width = 12
    raw.column_dimensions["C"].width = 20
    raw.column_dimensions["D"].width = 20
    raw.column_dimensions["E"].width = 100
    numbers.column_dimensions["A"].width = 10
    numbers.column_dimensions["B"].width = 20
    numbers.column_dimensions["C"].width = 24
    numbers.column_dimensions["D"].width = 70
    numbers.column_dimensions["E"].width = 28
    info.column_dimensions["A"].width = 22
    info.column_dimensions["B"].width = 100
    workbook.save(path)
    workbook.close()
    return status_rows, raw_rows, number_rows, info_rows


def _verify_workbook(path, expected_rows):
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        for sheet_name, expected in zip(("页码状态", "页面原文", "数字候选", "运行说明"), expected_rows):
            actual = [list(row) for row in workbook[sheet_name].iter_rows(values_only=True)]
            if actual != expected:
                raise ValueError(f"输出回读不一致：{sheet_name}")
            if any(cell.data_type == "f" for row in workbook[sheet_name].iter_rows() for cell in row):
                raise ValueError(f"输出含公式：{sheet_name}")
    finally:
        workbook.close()


def run(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    if source.suffix.lower() != ".pdf":
        raise ValueError("输入必须是 PDF")
    if output.suffix.lower() != ".xlsx":
        raise ValueError("输出必须是 XLSX")
    if source == output:
        raise ValueError("输出不可覆盖输入")
    if not source.is_file():
        raise FileNotFoundError(source)
    if not output.parent.is_dir():
        raise FileNotFoundError(f"输出目录不存在：{output.parent}")
    if os.path.lexists(output):
        raise FileExistsError(output)

    source_hash = sha256(source)
    pages = _extract(source)
    fd, temporary = tempfile.mkstemp(prefix=".ledger-pdf-text-", suffix=".xlsx", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            expected_rows = _write_workbook(stream, source.name, source_hash, pages)
        _verify_workbook(temporary, expected_rows)
        if sha256(source) != source_hash:
            raise ValueError("处理期间 PDF 源文件发生变化，结果不可发布")
        os.link(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {
        "output": str(output),
        "source_sha256": source_hash,
        "pages": len(pages),
        "pages_with_text": sum(page["has_text"] for page in pages),
        "number_candidates": sum(len(page["candidates"]) for page in pages),
        "status": "所有提取内容和数字候选均待对照原 PDF 人工核对",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="包含可搜索文字层的 PDF")
    parser.add_argument("output", help="新建 XLSX 路径；不覆盖现有文件")
    args = parser.parse_args()
    import json
    print(json.dumps(run(args.source, args.output), ensure_ascii=False, indent=2))
