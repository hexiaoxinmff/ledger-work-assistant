"""manifest —— 机器可读运行清单（FT-08）。不含交易明细。"""
from __future__ import annotations

import json
from typing import Any


def build_manifest(
    *,
    skill_version: str,
    adapter_version: str,
    upstream_base_version: str,
    rule_version: str,
    contract_version: str,
    run_id: str,
    run_at: str,
    run_at_source: str,
    inputs: list[dict[str, str]],
    outputs: list[dict[str, str]],
    field_mapping: dict[str, Any],
    config_dict: dict[str, Any],
    counts: dict[str, Any],
    warnings: int,
    errors: int,
) -> dict[str, Any]:
    return {
        "skill": "fcs-reconcile",
        "skill_version": skill_version,
        "adapter_version": adapter_version,
        "upstream_base_version": upstream_base_version,
        "rule_version": rule_version,
        "contract_version": contract_version,
        "run_id": run_id,
        "run_at": run_at,
        "run_at_source": run_at_source,
        "inputs": inputs,
        "outputs": outputs,
        "field_mapping": field_mapping,
        "config": config_dict,
        "permissions": {"network": "进程内尝试阻断，平台隔离待核实", "source_write": False},
        "counts": counts,
        "warnings": warnings,
        "errors": errors,
    }


def write_manifest(manifest: dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
