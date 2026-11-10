"""reporter —— 生成 7 张中文工作表（技术设计 §7 / 输出契约）。"""
from __future__ import annotations

from typing import Any

from models import ResultItem
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
import os
import pandas as pd

_SHEETS = ["对账总览", "待处理事项", "已匹配", "重复与冲突", "数据质量", "审计明细", "运行参数"]
_PENDING_COLS = ["优先级", "问题类型", "业务编号", "左侧金额", "右侧金额", "金额差异",
                 "判断依据", "建议动作", "来源行", "复核状态", "复核人", "复核意见"]


def _rows_for(items: list[ResultItem], sheet: str) -> list[ResultItem]:
    return [i for i in items if i.sheet == sheet]


def write_workbook(
    items: list[ResultItem], summary: dict[str, Any], run_params: dict[str, Any], path,
    left_df=None, left_spec=None, right_df=None, right_spec=None,
    left_rows=None, right_rows=None, visualization="none"
) -> None:
    wb = Workbook()
    ws = {
        name: (wb.active if idx == 0 else wb.create_sheet(name))
        for idx, name in enumerate(_SHEETS)
    }
    ws["对账总览"].title = "对账总览"

    # 对账总览 + 隐私运行摘要
    ov = ws["对账总览"]
    ov.append(["对账总览"])
    ov.append(["匹配率", summary["match_rate"]])
    ov.append(["数量勾稽", "通过" if summary["quantity_reconciled"] else "不通过"])
    amount_status = summary["amount_reconciled"]
    ov.append(["内部金额算术校验", "待核实（存在金额缺失）" if amount_status is None else ("内部算术一致（不代表对账完成）" if amount_status else "不一致")])
    ov.append(["左金额合计", summary["left_amount_total"]])
    ov.append(["右金额合计", summary["right_amount_total"]])
    for status, cnt in summary["counts"].items():
        ov.append([status, cnt])
    ov.append([])
    ov.append(["隐私运行摘要"])
    ov.append(["运行模式", "本地隔离"])
    ov.append(["原始数据进入模型", "取决于使用平台，需核实"])
    ov.append(["网络访问", "程序内尝试阻断，平台隔离另行核实"])
    ov.append(["源文件修改", "否"])

    # 待处理事项
    pend = ws["待处理事项"]
    pend.append(_PENDING_COLS)
    for i in _rows_for(items, "待处理事项"):
        pend.append([i.priority, i.status.value, i.no, _s(i.amount_left), _s(i.amount_right),
                     _s(i.amount_diff), i.basis, i.suggested_action,
                     f"L{i.left_source_row or ''}/R{i.right_source_row or ''}", "待复核", "", ""])

    # 已匹配
    matched = ws["已匹配"]
    matched.append(["业务编号", "左侧金额", "右侧金额", "匹配依据", "来源行"])
    for i in _rows_for(items, "已匹配"):
        matched.append([i.no, _s(i.amount_left), _s(i.amount_right), i.basis,
                        f"L{i.left_source_row}/R{i.right_source_row}"])

    # Identity is stable during one run; source_row is the original physical row.
    source_sides = {id(row): "左表" for row in (left_rows or [])}
    source_sides.update({id(row): "右表" for row in (right_rows or [])})

    # 重复与冲突
    conf = ws["重复与冲突"]
    conf.append(["业务编号", "状态", "候选清单", "冲突原因"])
    for i in _rows_for(items, "重复与冲突"):
        cand = "; ".join(f"{source_sides.get(id(c), '来源未确认')}第{c.source_row}行（编号 {c.no}）" for c in i.candidates)
        conf.append([i.no, i.status.value, cand, i.basis])

    # 数据质量
    dq = ws["数据质量"]
    dq.append(["问题类型", "业务编号", "来源行", "判断依据", "建议动作"])
    for i in _rows_for(items, "数据质量"):
        dq.append([i.status.value, i.no, f"L{i.left_source_row or ''}/R{i.right_source_row or ''}", i.basis, i.suggested_action])

    # 审计明细
    audit = ws["审计明细"]
    audit.append(["状态", "业务编号", "左侧金额", "右侧金额", "金额差异", "命中规则", "来源行"])
    for i in items:
        audit.append([i.status.value, i.no, _s(i.amount_left), _s(i.amount_right),
                      _s(i.amount_diff), i.basis,
                      f"L{i.left_source_row or ''}/R{i.right_source_row or ''}"])

    # 运行参数
    rp = ws["运行参数"]
    rp.append(["参数", "值"])
    for k, v in run_params.items():
        rp.append([k, str(v)])

    if left_df is not None and right_df is not None:
        for name, df, spec in (("左侧读取明细", left_df, left_spec), ("右侧读取明细", right_df, right_spec)):
            sheet = wb.create_sheet(name)
            for values in source_rows(df, spec):
                sheet.append(values)
                # All source values are data, never executable spreadsheet formulas.
                for cell in sheet[sheet.max_row]:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
    if visualization == "bar":
        chart_sheet = wb.create_sheet("结果图表")
        chart_sheet.append(["对账结果项分布（单位：结果项）"])
        chart_sheet.append(["同一编号的多条候选或质量问题可能产生多项；不代表交易笔数、独立编号数或已结清金额。"])
        chart_sheet.append(["状态", "结果项数量"])
        for state, count in summary["counts"].items():
            chart_sheet.append([state, count])
        chart_sheet.column_dimensions["A"].width = 29
        chart_sheet.column_dimensions["B"].width = 18
        chart = BarChart()
        chart.type = "bar"
        chart.title = "对账结果项分布"
        chart.x_axis.title = "结果项数量"
        chart.y_axis.title = "结果状态"
        chart.width = 23
        chart.height = 12
        chart.add_data(Reference(chart_sheet, min_col=2, min_row=3, max_row=3 + len(summary["counts"])), titles_from_data=True)
        chart.set_categories(Reference(chart_sheet, min_col=1, min_row=4, max_row=3 + len(summary["counts"])))
        chart_sheet.add_chart(chart, "D4")
    wb.save(path)


def source_rows(df, spec):
    """Return traceable text values as read; empty text maps to an empty cell."""
    name = os.path.basename(spec.file)
    sheet = str(spec.sheet) if spec.sheet is not None else ("CSV（无工作表）" if spec.file.lower().endswith(".csv") else "首个工作表")
    rows = [["来源文件", "来源工作表", "来源起始行"] + [str(x) for x in df.columns]]
    for i, values in enumerate(df.itertuples(index=False, name=None)):
        line = df.attrs['physical_rows'][i] if 'physical_rows' in df.attrs else spec.header_row + i + 2
        converted = []
        for value in values:
            if value is None or pd.isna(value) or value == "":
                converted.append(None)
            else:
                converted.append(str(value))
        rows.append([name, sheet, line] + converted)
    return rows


def verify_source_rows(path, pairs):
    """Read the actual output back; fail closed on row, value or provenance loss."""
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        for name, df, spec in pairs:
            expected = source_rows(df, spec)
            sheet = book[name]
            if sheet.max_column != len(expected[0]) or sheet.max_row != len(expected):
                raise ValueError(f"{name} 读取明细尺寸与输入不一致")
            for idx, (wanted, actual) in enumerate(zip(expected, sheet.iter_rows(values_only=True)), 1):
                if list(actual) != wanted:
                    raise ValueError(f"{name} 第 {idx} 行回读不一致，停止交付")
    finally:
        book.close()


def _s(v: object) -> str:
    return "" if v is None else str(v)
