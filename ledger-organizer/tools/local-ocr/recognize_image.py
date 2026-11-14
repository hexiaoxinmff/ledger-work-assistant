"""Experimental local OCR for a single image. All results require human verification."""
import argparse
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
import socket
import tempfile
from pathlib import Path

EXPECTED_MODELS = {
    "PP-OCRv6_det_small.onnx": "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    "PP-OCRv6_rec_small.onnx": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
}


def sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_runtime():
    if metadata.version("rapidocr") != "3.10.0" or metadata.version("onnxruntime") != "1.20.1":
        raise ValueError("当前试用版仅测试 rapidocr 3.10.0 与 onnxruntime 1.20.1")
    spec = importlib.util.find_spec("rapidocr")
    if spec is None or spec.origin is None:
        raise ValueError("未发现 rapidocr")
    model_dir = Path(spec.origin).parent / "models"
    model_paths = {}
    for filename, expected in EXPECTED_MODELS.items():
        model = (model_dir / filename).resolve()
        if not model.is_file() or sha(model) != expected:
            raise ValueError("本地模型缺失或哈希不符：" + filename)
        model_paths[filename] = str(model)
    return {
        "versions": {"rapidocr": "3.10.0", "onnxruntime": "1.20.1"},
        "models_verified": list(EXPECTED_MODELS),
        "model_paths": model_paths,
        "note": "已校验版本与模型文件哈希并返回显式路径；尚未初始化引擎或验证识别效果",
    }


def _recognize_without_python_socket_access(source, model_paths):
    """Limit Python socket access during inference and restore process globals afterward."""
    def deny(*args, **kwargs):
        raise OSError("OCR test: network access disabled")

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    try:
        socket.socket.connect = deny
        socket.socket.connect_ex = deny
        from rapidocr import RapidOCR

        params = {
            "Det.engine_type": "onnxruntime",
            "Det.model_path": model_paths["PP-OCRv6_det_small.onnx"],
            "Cls.engine_type": "onnxruntime",
            "Cls.model_path": model_paths["ch_ppocr_mobile_v2.0_cls_mobile.onnx"],
            "Rec.engine_type": "onnxruntime",
            "Rec.model_path": model_paths["PP-OCRv6_rec_small.onnx"],
        }
        result = RapidOCR(params=params)(str(source))
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
    return result


def run(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    if source == output:
        raise ValueError("输出不能覆盖源文件")
    if output.suffix.lower() != ".json":
        raise ValueError("输出必须是 JSON 文件")
    if source.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise ValueError("仅支持本地 PNG/JPEG 图片，不支持 PDF")
    if not source.is_file():
        raise FileNotFoundError(source)
    if not output.parent.is_dir():
        raise FileNotFoundError(f"输出目录不存在：{output.parent}")
    if os.path.lexists(output):
        raise FileExistsError(output)

    runtime = check_runtime()
    before = sha(source)
    result = _recognize_without_python_socket_access(source, runtime["model_paths"])
    records = []
    if result is not None and result.txts is not None:
        texts = list(result.txts)
        boxes = list(result.boxes)
        scores = list(result.scores)
        if not len(texts) == len(boxes) == len(scores):
            raise ValueError("识别字段数量不一致")
        for text, box, score in zip(texts, boxes, scores):
            records.append({
                "识别文本": str(text),
                "位置_像素": [[round(float(x), 2), round(float(y), 2)] for x, y in box],
                "模型分数": round(float(score), 4),
                "复核状态": "待人工核对原图",
            })
    if sha(source) != before:
        raise ValueError("原图在识别期间变化，结果不可交付")

    data = {
        "用途": "虚构图片试用，识别数字须逐字符人工核对；不自动入账或配对",
        "来源文件名": source.name,
        "来源sha256": before,
        "识别引擎": "RapidOCR 3.10.0 / ONNX Runtime 1.20.1",
        "网络": "本进程在推理期间拦截 Python socket 连接，不代表操作系统级隔离",
        "结果": records,
    }

    fd, temporary = tempfile.mkstemp(
        prefix=".ledger-ocr-", suffix=".json.tmp", dir=output.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        with open(temporary, encoding="utf8") as stream:
            if json.load(stream) != data:
                raise ValueError("OCR JSON 暂存结果回读不一致")
        if sha(source) != before:
            raise ValueError("原图在识别期间变化，结果不可交付")
        # Same-directory hard link publishes atomically and refuses overwrite.
        os.link(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return len(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?")
    parser.add_argument("output", nargs="?")
    parser.add_argument("--check-runtime", action="store_true")
    args = parser.parse_args()
    if args.check_runtime:
        if args.source or args.output:
            parser.error("--check-runtime 不接收输入或输出文件")
        print(json.dumps(check_runtime(), ensure_ascii=False))
    else:
        if not args.source or not args.output:
            parser.error("识别需要 source 和 output 文件")
        print("识别行数（均需人工复核）：", run(args.source, args.output))
