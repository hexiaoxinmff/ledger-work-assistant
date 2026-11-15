"""Run one deterministic synthetic OCR smoke check with the pinned real model."""
import json
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw, ImageFont

from recognize_image import run


EXPECTED = "00042"


def main():
    with tempfile.TemporaryDirectory(prefix="ledger-ocr-smoke-") as temporary:
        directory = Path(temporary)
        source = directory / "synthetic-number.png"
        output = directory / "recognition.json"

        image = Image.new("RGB", (1600, 420), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=190)
        bounds = draw.textbbox((0, 0), EXPECTED, font=font, stroke_width=2)
        x = (image.width - (bounds[2] - bounds[0])) // 2
        y = (image.height - (bounds[3] - bounds[1])) // 2 - bounds[1]
        draw.text((x, y), EXPECTED, fill="black", font=font, stroke_width=2)
        image.save(source)

        run(source, output)
        data = json.loads(output.read_text(encoding="utf-8"))
        recognized = [item["识别文本"] for item in data["结果"]]
        if recognized != [EXPECTED]:
            raise SystemExit(
                "真实模型合成冒烟测试不匹配；expected="
                + repr([EXPECTED])
                + ", actual="
                + repr(recognized)
            )
        if any(item.get("复核状态") != "待人工核对原图" for item in data["结果"]):
            raise SystemExit("识别结果未保持人工复核状态")
        print(
            "PASS: pinned RapidOCR model recognized synthetic "
            + repr(EXPECTED)
            + " exactly; result remains pending manual review."
        )


if __name__ == "__main__":
    main()
