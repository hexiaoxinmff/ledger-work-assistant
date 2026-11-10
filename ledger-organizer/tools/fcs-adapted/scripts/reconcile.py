"""fcs-reconcile 入口（薄编排层）。仅 summary 上交上层；明细留本地。

数据平面顶层：解析参数与配置 → 顺序编排各模块 → 写结果与运行清单。
仅把汇总（summary）暴露给上层/AI；原始明细、DataFrame、标准行不越界。

处理管线（见技术设计 §2.1）：
    config → io_reader(+sha256) → normalizer → matcher → classifier
           → 勾稽校验/summary → reporter → integrity(前后哈希) → manifest

本模块与兄弟模块平铺同目录（不包化，见项目结构设计 D4），故直接 `import config` 等。
运行期 sys.path[0] 为 scripts/；测试期由 tests/conftest.py 注入。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, cast

import classifier
import config as config_mod
import guard
import integrity
import io_reader
import manifest as manifest_mod
import matcher
import normalizer
import reporter
import summary as summary_mod
import version as version_mod


def run(config_obj: config_mod.ReconcileConfig, *, run_id: str, run_at: str) -> dict[str, object]:
    """执行完整对账管线，写工作簿与运行清单，只返回 summary（不含任何明细/DataFrame）。"""
    run_at_source = "调用方提供（未经核验）" if run_at else "程序自动记录（UTC）"
    if not run_at:
        run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if bool(config_obj.left.fields.date) != bool(config_obj.right.fields.date):
        raise ValueError('日期字段须两边同时提供或同时不提供')
    integrity.assert_output_not_overwrites_input(config_obj.output_path, [config_obj.left.file, config_obj.right.file])
    integrity.assert_output_not_overwrites_input(config_obj.output_path + '.manifest.json', [config_obj.left.file, config_obj.right.file])
    if os.path.lexists(config_obj.output_path) or os.path.lexists(config_obj.output_path + '.manifest.json'):
        raise FileExistsError('输出文件或运行清单已存在，请使用新路径')
    if config_obj.visualization not in ("none", "bar"):
        raise ValueError("visualization 仅支持 none 或 bar")
    guard.block_network()

    left_df, left_sha = io_reader.read_table(config_obj.left)
    right_df, right_sha = io_reader.read_table(config_obj.right)
    before = {config_obj.left.file: left_sha, config_obj.right.file: right_sha}

    left_rows = normalizer.normalize(left_df, config_obj.left.fields, config_obj.match, config_obj.left.header_row)
    right_rows = normalizer.normalize(right_df, config_obj.right.fields, config_obj.match, config_obj.right.header_row)

    outcomes = matcher.match(left_rows, right_rows, config_obj.match)
    items = classifier.classify(outcomes)
    s = summary_mod.build_summary(outcomes, len(left_rows), len(right_rows))
    errors = 0 if (s["quantity_reconciled"] and s["amount_reconciled"]) else 1

    # Exclusive creation reserves both names atomically on supported local filesystems.
    output_stream = open(config_obj.output_path, 'xb')
    try:
        try:
            manifest_stream = open(config_obj.output_path + '.manifest.json', 'xb')
        except BaseException:
            # Only remove our own still-empty reservation; never remove another file.
            own_stat = os.fstat(output_stream.fileno())
            output_stream.close()
            try:
                current = os.stat(config_obj.output_path, follow_symlinks=False)
                if own_stat.st_size == 0 and current.st_size == 0 and os.path.samestat(own_stat, current):
                    os.unlink(config_obj.output_path)
            except FileNotFoundError:
                pass
            raise
        with manifest_stream:
            reporter.write_workbook(items, s, {
                "rule_version": config_obj.rule_version,
                "contract_version": config_obj.contract_version,
                "amount_tolerance": str(config_obj.match.amount_tolerance),
                "date_tolerance_days": config_obj.match.date_tolerance_days,
            }, output_stream, left_df, config_obj.left, right_df, config_obj.right,
               left_rows, right_rows, config_obj.visualization)
            output_stream.flush()
            reporter.verify_source_rows(config_obj.output_path, [
                ("左侧读取明细", left_df, config_obj.left),
                ("右侧读取明细", right_df, config_obj.right),
            ])

            after = {config_obj.left.file: integrity.sha256_of(config_obj.left.file),
                     config_obj.right.file: integrity.sha256_of(config_obj.right.file)}
            integrity.verify_unchanged(before, after)

            output_stream.flush()
            out_sha = integrity.sha256_of(config_obj.output_path)
            m = manifest_mod.build_manifest(
                skill_version=version_mod.SKILL_VERSION, adapter_version=version_mod.ADAPTER_VERSION,
                upstream_base_version=version_mod.UPSTREAM_BASE_VERSION, rule_version=config_obj.rule_version,
                contract_version=config_obj.contract_version, run_id=run_id, run_at=run_at, run_at_source=run_at_source,
                inputs=[{"path": config_obj.left.file, "sha256": left_sha},
                        {"path": config_obj.right.file, "sha256": right_sha}],
                outputs=[{"path": config_obj.output_path, "sha256": out_sha}],
                field_mapping={"left": vars(config_obj.left.fields),
                               "right": vars(config_obj.right.fields)},
                config_dict={"amount_tolerance": str(config_obj.match.amount_tolerance),
                             "date_tolerance_days": config_obj.match.date_tolerance_days,
                             "visualization": config_obj.visualization},
                counts=cast(dict[str, Any], s["counts"]), warnings=0, errors=errors)
            manifest_stream.write(json.dumps(m, ensure_ascii=False, indent=2).encode("utf-8"))
            manifest_stream.flush()
    finally:
        output_stream.close()
    return s


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：`python scripts/reconcile.py --config <config.yaml>`。

    全程走 guard 的网络隔离与日志脱敏；仅打印 summary 的 JSON，不输出任何明细。
    """
    parser = argparse.ArgumentParser(prog="fcs-reconcile")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", default="cli")
    parser.add_argument("--run-at", default="")
    args = parser.parse_args(argv)
    conf = config_mod.load_config(args.config)
    s = run(conf, run_id=args.run_id, run_at=args.run_at)
    print(json.dumps(s, ensure_ascii=False))  # 仅 summary，无明细
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
