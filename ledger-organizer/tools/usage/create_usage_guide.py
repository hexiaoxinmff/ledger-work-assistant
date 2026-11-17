#!/usr/bin/env python3
"""Create a dependency-free Word usage guide from Markdown-like tutorial text.

This helper is intentionally limited to tutorial content. It does not read business
files or include source data. Existing output files are never overwritten.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
CONTENT_TYPES = f'''{XML_HEADER}
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>'''
RELS = f'''{XML_HEADER}
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
DOC_RELS = f'''{XML_HEADER}
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'''
STYLES = f'''{XML_HEADER}
<w:styles xmlns:w="{NS}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:eastAsia="Microsoft YaHei"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:pPr><w:jc w:val="center"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="ListNumber"><w:name w:val="List Number"/><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr></w:pPr></w:style>
</w:styles>'''
NUMBERING = f'''{XML_HEADER}
<w:numbering xmlns:w="{NS}">
<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl></w:abstractNum>
<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
</w:numbering>'''

def para(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    safe = html.escape(text, quote=False)
    return f'<w:p xmlns:w="{NS}">{ppr}<w:r><w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'

def markdown_to_xml(text: str, title: str) -> str:
    blocks = [para(title, "Title")]
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            blocks.append(para(""))
        elif line.startswith("### "):
            blocks.append(para(line[4:], "Heading2"))
        elif line.startswith("## "):
            blocks.append(para(line[3:], "Heading1"))
        elif line.startswith("# "):
            blocks.append(para(line[2:], "Heading1"))
        elif line.startswith("- "):
            blocks.append(para(line[2:], "ListBullet"))
        elif re.match(r"^\d+[.)]\s+", line):
            blocks.append(para(re.sub(r"^\d+[.)]\s+", "", line), "ListNumber"))
        else:
            blocks.append(para(line))
    body = "".join(blocks)
    return f'''{XML_HEADER}<w:document xmlns:w="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>{body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'''

def write_docx(output: Path, title: str, markdown: str) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"拒绝覆盖已有教程文件: {output}")
    fd, temp_name = tempfile.mkstemp(prefix=".usage-guide-", suffix=".docx", dir=output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", CONTENT_TYPES)
            zf.writestr("_rels/.rels", RELS)
            zf.writestr("word/document.xml", markdown_to_xml(markdown, title))
            zf.writestr("word/styles.xml", STYLES)
            zf.writestr("word/numbering.xml", NUMBERING)
            zf.writestr("word/_rels/document.xml.rels", DOC_RELS)
        try:
            os.link(temp_path, output)
        except FileExistsError:
            raise FileExistsError(f"拒绝覆盖已有教程文件: {output}")
        except OSError as exc:
            raise RuntimeError("目标目录不支持安全的独占发布（需要同卷硬链接）") from exc
    finally:
        temp_path.unlink(missing_ok=True)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="新建 .docx 路径")
    parser.add_argument("--title", default="通用台账助手使用教程")
    parser.add_argument("--markdown", help="教程 Markdown 文件；未提供时使用内置通用教程")
    args = parser.parse_args()
    default = """## 这项技能能做什么
- 转换 CSV、TSV、XLSX、简单 DOCX 表格和可搜索 PDF
- 按确认规则整理费用、收款和欠费台账
- 保留来源、原始字段、空值、重复记录和跨行内容
- 列出待人工核实事项，不替用户作财务结论

## 怎么使用
1. 先提供文件类型、处理范围、目标格式和必须保留的字段。
2. 说明匹配键、日期范围、金额口径和是否需要图表。
3. 先用虚构样例验收，再使用脱敏真实资料。
4. 收到结果后核对来源明细、复核清单、数字候选和运行清单。

## 重要限制
- 不自动安装依赖，不覆盖原始文件或已有结果。
- OCR、数字候选、空值与零值、长编号和显示格式都必须人工复核。
- 结果是办公辅助，不等于入账、付款、开票或正式财务审核。"""
    markdown = Path(args.markdown).read_text(encoding="utf-8") if args.markdown else default
    if not markdown.strip():
        raise ValueError("教程内容不能为空")
    write_docx(Path(args.output), args.title, markdown)
    print(f"OUTPUT: {Path(args.output).resolve()}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileExistsError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
