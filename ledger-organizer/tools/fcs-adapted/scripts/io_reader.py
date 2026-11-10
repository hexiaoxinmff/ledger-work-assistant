"""io_reader —— 读取 xlsx/csv，金额列以字符串载入，计算源文件哈希（技术设计 §4.1）。"""
from __future__ import annotations

import os
import csv
import codecs

import integrity
import pandas as pd
from config import TableSpec


def read_table(spec: TableSpec) -> tuple[pd.DataFrame, str]:
    sha = integrity.sha256_of(spec.file)
    # 金额列强制 str，隔离 float64 精度风险。
    str_cols = {c: str for c in [spec.fields.no, spec.fields.amount] if c}
    ext = os.path.splitext(spec.file)[1].lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(spec.file, sheet_name=spec.sheet or 0,
                           header=spec.header_row, dtype=str_cols)
    elif ext == '.csv':
        # Track physical starting lines of logical CSV records, including quoted newlines.
        encoding = spec.encoding
        allowed = {'utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'gb18030', 'gbk'}
        if encoding is not None:
            if not isinstance(encoding, str) or encoding.lower().replace('_', '-') not in allowed:
                raise ValueError('不支持的 CSV 编码；可用 utf-8、utf-8-sig、utf-16、utf-16-le、utf-16-be、gb18030、gbk')
            encoding = encoding.lower().replace('_', '-')
        else:
            with open(spec.file, 'rb') as probe:
                bom = probe.read(4)
            if bom.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
                raise ValueError('暂不支持 UTF-32 CSV，请转换为 UTF-8')
            encoding = 'utf-16' if bom.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else 'utf-8-sig'
        try:
            with open(spec.file, encoding=encoding, newline='') as stream:
                return _read_csv(stream, spec, sha)
        except UnicodeError as exc:
            raise ValueError('CSV 编码读取失败：请确认实际编码，并在该表配置 encoding，例如 gb18030；不要猜测编码') from exc
    else:
        raise ValueError('仅支持 XLSX、XLS 或 CSV')
    return _check_columns(df, spec, sha)


def _read_csv(stream, spec, sha):
    reader = csv.reader(stream, strict=True)
    records = []
    while True:
        start = reader.line_num + 1
        try:
            row = next(reader)
        except StopIteration:
            break
        if row:
            records.append((start, row))
    if spec.header_row < 0 or spec.header_row >= len(records):
        raise ValueError('CSV 表头行不存在')
    header = records[spec.header_row][1]
    if not all(header) or len(set(header)) != len(header):
        raise ValueError('CSV 表头为空或重复，请先处理表头')
    data = records[spec.header_row + 1:]
    if any(len(row) != len(header) for _, row in data):
        raise ValueError('CSV 记录列数不一致，无法安全定位来源行')
    df = pd.DataFrame([row for _, row in data], columns=header)
    df.attrs['physical_rows'] = [start for start, _ in data]
    return _check_columns(df, spec, sha)


def _check_columns(df, spec, sha):
    # 若配置的列名与表头不一致，pandas 会静默忽略 dtype 并以 float 载入金额，
    # 绕过"金额永不入 float"。这里显式校验必需列存在，不一致则明确报错。
    missing = {spec.fields.no, spec.fields.amount} - set(df.columns)
    if missing:
        raise ValueError(f"表中缺少配置的列：{sorted(missing)}（表头与字段映射不一致）")
    return df, sha
