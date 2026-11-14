"""Compare synthetic OCR truth with line-level JSON results; never approves recognized data."""
import argparse
import json
from pathlib import Path
import sys

FIELD_TYPES = {"amount", "date", "identifier", "text"}
PENDING = "待人工核对原图"


def edit_distance(expected, actual):
    """Levenshtein distance over Unicode code points."""
    previous = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        current = [i]
        for j, right in enumerate(actual, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (left != right),
            ))
        previous = current
    return previous[-1]


def evaluate(expected_data, actual_data):
    cases = expected_data.get("cases")
    results = actual_data.get("结果")
    if not isinstance(cases, list) or not cases:
        raise ValueError("真值文件必须包含非空 cases 列表")
    if not isinstance(results, list):
        raise ValueError("OCR 文件必须包含 结果 列表")
    for item in results:
        if not isinstance(item, dict) or not isinstance(item.get("识别文本"), str):
            raise ValueError("OCR 结果项格式无效")
        if item.get("复核状态") != PENDING:
            raise ValueError("所有 OCR 结果必须保留待人工复核状态")

    case_ids = set()
    indexes = set()
    scored = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("每个真值案例必须为对象")
        case_id = case.get("id")
        kind = case.get("field_type")
        index = case.get("result_index")
        expected = case.get("expected")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in case_ids:
            raise ValueError("案例 id 必须为非空且唯一的字符串")
        if kind not in FIELD_TYPES:
            raise ValueError("field_type 仅支持 amount、date、identifier、text")
        if type(index) is not int or index < 0 or index in indexes:
            raise ValueError("result_index 必须为非负且唯一的整数")
        if not isinstance(expected, str) or not expected:
            raise ValueError("expected 必须为非空原文字符串")
        case_ids.add(case_id)
        indexes.add(index)

        actual = ""
        if index < len(results):
            item = results[index]
            if not isinstance(item, dict) or not isinstance(item.get("识别文本"), str):
                raise ValueError("OCR 结果项格式无效")
            if item.get("复核状态") != PENDING:
                raise ValueError("OCR 结果必须保留待人工复核状态")
            actual = item["识别文本"]
        distance = edit_distance(expected, actual)
        scored.append({
            "id": case_id,
            "field_type": kind,
            "expected": expected,
            "recognized": actual,
            "exact_match": expected == actual,
            "edit_distance": distance,
            "review_status": PENDING,
        })

    groups = {}
    for kind in sorted(FIELD_TYPES):
        selected = [item for item in scored if item["field_type"] == kind]
        if selected:
            groups[kind] = {
                "cases": len(selected),
                "exact_matches": sum(item["exact_match"] for item in selected),
                "exact_match_rate": sum(item["exact_match"] for item in selected) / len(selected),
            }
    expected_chars = sum(len(item["expected"]) for item in scored)
    total_edits = sum(item["edit_distance"] for item in scored)
    mapped_indexes = {case["result_index"] for case in cases}
    return {
        "purpose": "仅比较虚构 OCR 样例与人工真值；不用于确认真实数据",
        "source_sha256": actual_data.get("来源sha256"),
        "case_count": len(scored),
        "exact_matches": sum(item["exact_match"] for item in scored),
        "exact_match_rate": sum(item["exact_match"] for item in scored) / len(scored),
        "character_error_rate": total_edits / expected_chars if expected_chars else 0.0,
        "edit_distance": total_edits,
        "expected_character_count": expected_chars,
        "unmapped_ocr_result_count": sum(i not in mapped_indexes for i in range(len(results))),
        "by_field_type": groups,
        "cases": scored,
        "review_required": True,
        "warning": "指标不能证明真实资料正确；识别结果不得因分数或完全匹配而自动确认，须人工对照原图。",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", help="虚构样例真值 JSON")
    parser.add_argument("actual", help="recognize_image.py 生成的 OCR JSON")
    parser.add_argument("--require-exact", action="store_true", help="只用于回归门禁：有任一不匹配时返回 1")
    args = parser.parse_args(argv)
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    actual = json.loads(Path(args.actual).read_text(encoding="utf-8"))
    report = evaluate(expected, actual)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.require_exact and report["exact_matches"] != report["case_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
