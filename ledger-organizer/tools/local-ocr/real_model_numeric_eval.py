"""Measure pinned RapidOCR on deterministic synthetic numeric images.

This is an observational measurement, not an accuracy gate. Every recognized
fragment remains pending manual review. Only generated fictional images are used.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from recognize_image import run
from evaluate_accuracy import edit_distance, PENDING


CASES = [
    {"id": "amount-zero-decimals", "suite": "baseline", "condition": "large high-contrast", "field_type": "amount", "expected": "0.00"},
    {"id": "amount-thousands-decimals", "suite": "baseline", "condition": "large high-contrast", "field_type": "amount", "expected": "1,234.56"},
    {"id": "amount-parentheses", "suite": "baseline", "condition": "large high-contrast", "field_type": "amount", "expected": "(88.00)"},
    {"id": "amount-negative", "suite": "baseline", "condition": "large high-contrast", "field_type": "amount", "expected": "-1,234.56"},
    {"id": "identifier-leading-zeros", "suite": "baseline", "condition": "large high-contrast", "field_type": "identifier", "expected": "00042"},
    {"id": "identifier-long", "suite": "baseline", "condition": "large high-contrast", "field_type": "identifier", "expected": "1234567890123456"},
    {"id": "date-iso", "suite": "baseline", "condition": "large high-contrast", "field_type": "date", "expected": "2026-11-15"},
    {"id": "digits-sequence", "suite": "baseline", "condition": "large high-contrast", "field_type": "text", "expected": "9876543210"},
    {"id": "negative-small-font", "suite": "image-variation", "condition": "font size 80 px", "field_type": "amount", "expected": "-1,234.56", "render": {"font_size": 80}},
    {"id": "negative-low-contrast", "suite": "image-variation", "condition": "gray text 150 on gray background 245", "field_type": "amount", "expected": "-1,234.56", "render": {"foreground_level": 150, "background_level": 245}},
    {"id": "negative-rotation-2deg", "suite": "image-variation", "condition": "rotated 2 degrees", "field_type": "amount", "expected": "-1,234.56", "render": {"rotation_degrees": 2}},
    {"id": "negative-jpeg-q40", "suite": "image-variation", "condition": "JPEG quality 40", "field_type": "amount", "expected": "-1,234.56", "render": {"format": "JPEG", "jpeg_quality": 40}},
    {"id": "negative-downsample-half", "suite": "image-variation", "condition": "downsampled to half dimensions", "field_type": "amount", "expected": "-1,234.56", "render": {"downsample_factor": 0.5}},
    {"id": "negative-light-blur", "suite": "image-variation", "condition": "Gaussian blur radius 0.8 px", "field_type": "amount", "expected": "-1,234.56", "render": {"blur_radius": 0.8}},
    {"id": "positive-small-control", "suite": "image-variation", "condition": "positive amount at font size 80 px", "field_type": "amount", "expected": "1,234.56", "render": {"font_size": 80}},
]


def _gray(level):
    if type(level) is not int or not 0 <= level <= 255:
        raise ValueError("合成图片灰度值必须为 0–255 的整数")
    return (level, level, level)


def _draw_case(case, destination):
    render = case.get("render", {})
    font_size = render.get("font_size", 190)
    if type(font_size) is not int or not 24 <= font_size <= 512:
        raise ValueError("合成图片字号超出范围")
    background = _gray(render.get("background_level", 255))
    foreground = _gray(render.get("foreground_level", 0))
    stroke_width = render.get("stroke_width", 2)
    if type(stroke_width) is not int or not 0 <= stroke_width <= 12:
        raise ValueError("合成图片笔画宽度无效")

    font = ImageFont.load_default(size=font_size)
    probe = Image.new("RGB", (1, 1), background)
    draw = ImageDraw.Draw(probe)
    text = case["expected"]
    bounds = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    width = max(1600, bounds[2] - bounds[0] + 160)
    height = max(420, bounds[3] - bounds[1] + 140)
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    x = (width - (bounds[2] - bounds[0])) // 2
    y = (height - (bounds[3] - bounds[1])) // 2 - bounds[1]
    draw.text((x, y), text, fill=foreground, font=font, stroke_width=stroke_width)

    angle = render.get("rotation_degrees", 0)
    if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle) or abs(angle) > 10:
        raise ValueError("合成图片旋转角度无效")
    if angle:
        image = image.rotate(
            angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=background
        )

    blur_radius = render.get("blur_radius", 0)
    if isinstance(blur_radius, bool) or not isinstance(blur_radius, (int, float)) or not math.isfinite(blur_radius) or not 0 <= blur_radius <= 5:
        raise ValueError("合成图片模糊半径无效")
    if blur_radius:
        image = image.filter(ImageFilter.GaussianBlur(blur_radius))

    scale = render.get("downsample_factor", 1.0)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or not 0.1 <= scale <= 1:
        raise ValueError("合成图片缩放比例无效")
    if scale != 1:
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )

    image_format = render.get("format", "PNG")
    if image_format not in ("PNG", "JPEG"):
        raise ValueError("合成图片格式仅支持 PNG/JPEG")
    if image_format == "JPEG":
        quality = render.get("jpeg_quality", 40)
        if type(quality) is not int or not 1 <= quality <= 95:
            raise ValueError("JPEG 合成质量必须为 1–95")
        image.save(destination, format="JPEG", quality=quality, subsampling=2, optimize=False)
    else:
        image.save(destination, format="PNG")


def _bbox_envelope_overlaps(fragments):
    """Report axis-aligned envelope intersections; they do not prove glyph overlap."""
    overlaps = []
    for left_index, left in enumerate(fragments):
        left_box = left["bbox_pixels"]
        left_x = [point[0] for point in left_box]
        left_y = [point[1] for point in left_box]
        for right in fragments[left_index + 1:]:
            right_box = right["bbox_pixels"]
            right_x = [point[0] for point in right_box]
            right_y = [point[1] for point in right_box]
            x1 = max(min(left_x), min(right_x))
            y1 = max(min(left_y), min(right_y))
            x2 = min(max(left_x), max(right_x))
            y2 = min(max(left_y), max(right_y))
            if x1 < x2 and y1 < y2:
                overlaps.append({
                    "first_result_index": left["ocr_result_index"],
                    "second_result_index": right["ocr_result_index"],
                    "intersection_envelope_pixels": [x1, y1, x2, y2],
                    "intersection_envelope_area_pixels": (x2 - x1) * (y2 - y1),
                })
    return overlaps


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


def _suffix(case):
    return ".jpg" if case.get("render", {}).get("format") == "JPEG" else ".png"


def evaluate():
    rows = []
    with tempfile.TemporaryDirectory(prefix="ledger-ocr-numeric-") as temporary:
        directory = Path(temporary)
        for index, case in enumerate(CASES):
            source = directory / f"synthetic-{index:02d}{_suffix(case)}"
            result_path = directory / f"recognition-{index:02d}.json"
            _draw_case(case, source)
            run(source, result_path)
            data = json.loads(result_path.read_text(encoding="utf-8"))
            recognized_rows = data.get("结果")
            if not isinstance(recognized_rows, list):
                raise ValueError(f"{case['id']}: OCR 结果结构无效")
            recognized = []
            fragments = []
            for result_index, item in enumerate(recognized_rows, 1):
                if not isinstance(item, dict) or not isinstance(item.get("识别文本"), str):
                    raise ValueError(f"{case['id']}: OCR 识别行结构无效")
                if item.get("复核状态") != PENDING:
                    raise ValueError(f"{case['id']}: 结果未保留人工复核状态")
                box = item.get("位置_像素")
                score = item.get("模型分数")
                if not isinstance(box, list) or len(box) != 4:
                    raise ValueError(f"{case['id']}: OCR 边界框结构无效")
                if any(
                    not isinstance(point, list) or len(point) != 2
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not math.isfinite(value) for value in point)
                    for point in box
                ):
                    raise ValueError(f"{case['id']}: OCR 边界框坐标无效")
                if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError(f"{case['id']}: OCR 模型分数无效")
                recognized.append(item["识别文本"])
                fragments.append({
                    "ocr_result_index": result_index,
                    "recognized_text": item["识别文本"],
                    "model_score_reference_only": float(score),
                    "bbox_pixels": box,
                    "review_status": PENDING,
                })
            joined = "".join(recognized)
            distance = edit_distance(case["expected"], joined)
            rows.append({
                **case,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "recognized_lines": recognized,
                "recognized_fragments": fragments,
                "fragment_count": len(fragments),
                "axis_aligned_bbox_overlaps": _bbox_envelope_overlaps(fragments),
                "recognized_joined_for_cer": joined,
                "exact_match": len(recognized) == 1 and joined == case["expected"],
                "edit_distance": distance,
                "review_required": True,
            })

    total_chars = sum(len(row["expected"]) for row in rows)
    total_edits = sum(row["edit_distance"] for row in rows)
    suites = {}
    for suite in sorted({row["suite"] for row in rows}):
        selected = [row for row in rows if row["suite"] == suite]
        expected_chars = sum(len(row["expected"]) for row in selected)
        suites[suite] = {
            "case_count": len(selected),
            "exact_matches": sum(row["exact_match"] for row in selected),
            "multi_box_case_count": sum(row["fragment_count"] > 1 for row in selected),
            "exact_match_rate": sum(row["exact_match"] for row in selected) / len(selected),
            "character_error_rate": sum(row["edit_distance"] for row in selected) / expected_chars if expected_chars else 0.0,
        }
    return {
        "purpose": "仅测量固定 RapidOCR 模型对临时生成的虚构数字图像的识别表现；不代表真实资料准确率",
        "case_count": len(rows),
        "exact_matches": sum(row["exact_match"] for row in rows),
        "multi_box_case_count": sum(row["fragment_count"] > 1 for row in rows),
        "exact_match_rate": sum(row["exact_match"] for row in rows) / len(rows),
        "character_error_rate": total_edits / total_chars if total_chars else 0.0,
        "by_suite": suites,
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
    print("## 合成数字 OCR 测量（仅观察）")
    for suite, stats in report["by_suite"].items():
        print(f"- {suite}: 单框完全匹配 {stats['exact_matches']}/{stats['case_count']}；多框案例 {stats['multi_box_case_count']}；CER {stats['character_error_rate']:.4f}")
    print(f"- 合计：单框完全匹配 {report['exact_matches']}/{report['case_count']}；多框案例 {report['multi_box_case_count']}；CER {report['character_error_rate']:.4f}")
    print("- 结果状态：所有识别结果仍须人工复核；测量不是准确率门禁")
    print("| 测试集 | 案例 | 条件 | 真值 | 识别片段 | 单框完全匹配 |")
    print("|---|---|---|---|---|---|")
    for row in report["cases"]:
        observed = " / ".join(row["recognized_lines"]) or "（无识别行）"
        print(f"| {row['suite']} | {row['id']} | {row['condition']} | {row['expected']} | {observed} | {'是' if row['exact_match'] else '否'} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
