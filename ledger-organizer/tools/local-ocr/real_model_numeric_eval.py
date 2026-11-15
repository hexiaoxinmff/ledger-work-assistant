"""Measure pinned RapidOCR on a small deterministic synthetic numeric set.

This is a measurement, not an accuracy gate. Every recognized row remains pending
manual review. Only generated fictional images are sent to the OCR engine.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw, ImageFont

from recognize_image import run
from evaluate_accuracy import edit_distance, PENDING


CASES = [
    {"id": "amount-zero-decimals", "field_type": "amount", "expected": "0.00"},
    {"id": "amount-thousands-decimals", "field_type": "amount", "expected": "1,234.56"},
    {"id": "amount-parentheses", "field_type": "amount", "expected": "(88.00)"},
    {"id": "amount-negative", "field_type": "amount", "expected": "-1,234.56"},
    {"id": "identifier-leading-zeros", "field_type": "identifier", "expected": "00042"},
    {"id": "identifier-long", "field_type": "identifier", "expected": "1234567890123456"},
    {"id": "date-iso", "field_type": "date", "expected": "2026-11-15"},
    {"id": "digits-sequence", "field_type": "text", "expected": "9876543210"},
]


def _draw_case(text, destination):
    font = ImageFont.load_default(size=190)
    probe = Image.new("RGB", (1, 1), "white")
    draw = ImageDraw.Draw(probe)
    bounds = draw.textbbox((0, 0), text, font=font, stroke_width=2)
    width = max(1600, bounds[2] - bounds[0] + 160)
    height = max(420, bounds[3] - bounds[1] + 140)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    x = (width - (bounds[2] - bounds[0])) // 2
    y = (height - (bounds[3] - bounds[1])) // 2 - bounds[1]
    draw.text((x, y), text, fill="black", font=font, stroke_width=2)
    image.save(destination, format="PNG")


def _publish_new_file(destination, payload):
    destination = Path(destination)
    if not destination.parent.is_dir():
        raise ValueError("报告目录必须已存在；脚本不会创建目录")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".ocr-numeric-", suffix=".tmp",
            dir=destination.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def evaluate():
    rows = []
    with tempfile.TemporaryDirectory(prefix="ledger-ocr-numeric-") as temporary:
        directory = Path(temporary)
        for index, case in enumerate(CASES):
            source = directory / f"synthetic-{index:02d}.png"
            result_path = directory / f"recognition-{index:02d}.json"
            _draw_case(case["expected"], source)
            run(source, result_path)
            data = json.loads(result_path.read_text(encoding="utf-8"))
            recognized_rows = data.get("结果")
            if not isinstance(recognized_rows, list):
                raise ValueError(f"{case['id']}: OCR 结果结构无效")
            recognized = []
            for item in recognized_rows:
                if not isinstance(item, dict) or not isinstance(item.get("识别文本"), str):
                    raise ValueError(f"{case['id']}: OCR 识别行结构无效")
                if item.get("复核状态") != PENDING:
                    raise ValueError(f"{case['id']}: 结果未保留人工复核状态")
                recognized.append(item["识别文本"])
            actual = recognized[0] if len(recognized) == 1 else ""
            distance = edit_distance(case["expected"], actual)
            rows.append({
                **case,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "recognized_lines": recognized,
                "exact_match": len(recognized) == 1 and actual == case["expected"],
                "edit_distance": distance if len(recognized) == 1 else len(case["expected"]),
                "review_required": True,
            })
    total_chars = sum(len(row["expected"]) for row in rows)
    total_edits = sum(row["edit_distance"] for row in rows)
    return {
        "purpose": "仅测量固定 RapidOCR 模型对临时生成的虚构数字图像的识别表现；不代表真实资料准确率",
        "case_count": len(rows),
        "exact_matches": sum(row["exact_match"] for row in rows),
        "exact_match_rate": sum(row["exact_match"] for row in rows) / len(rows),
        "character_error_rate": total_edits / total_chars if total_chars else 0.0,
        "review_required": True,
        "accuracy_gate": False,
        "cases": rows,
        "warning": "所有识别结果仍须人工对照原图；测试不自动确认任何数字。",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="新建 JSON 报告路径，不覆盖已有文件")
    args = parser.parse_args(argv)
    destination = Path(args.output)
    if destination.exists():
        raise FileExistsError(f"输出已存在，拒绝覆盖: {destination}")
    report = evaluate()
    encoded = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _publish_new_file(args.output, encoded)
    print("## 合成数字识别测量（非准确率门禁）")
    print(f"- 完全匹配：{report['exact_matches']}/{report['case_count']}")
    print(f"- 字符错误率：{report['character_error_rate']:.4f}")
    print("- 结果状态：全部要求人工复核；分数不确认任何数字")
    print("| 类别 | 真值 | 识别结果 | 精确匹配 |")
    print("|---|---|---|---|")
    for row in report["cases"]:
        observed = " / ".join(row["recognized_lines"]) or "（无识别行）"
        print(f"| {row['field_type']} | {row['expected']} | {observed} | {'是' if row['exact_match'] else '否'} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
