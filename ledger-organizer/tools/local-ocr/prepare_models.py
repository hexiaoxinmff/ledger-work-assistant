"""Explicitly download the pinned RapidOCR ONNX models after user invocation."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile
from urllib.request import urlopen

RAPIDOCR_VERSION = "3.10.0"
MAX_MODEL_BYTES = 512 * 1024 * 1024
MODELS = {
    "PP-OCRv6_det_small.onnx": {
        "url": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/det/PP-OCRv6_det_small.onnx",
        "sha256": "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
    },
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx": {
        "url": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    },
    "PP-OCRv6_rec_small.onnx": {
        "url": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/rec/PP-OCRv6_rec_small.onnx",
        "sha256": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    },
}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_one(directory, filename, details):
    target = directory / filename
    if os.path.lexists(target):
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"模型目标不是普通文件，拒绝使用或覆盖：{filename}")
        if sha256(target) != details["sha256"]:
            raise ValueError(f"已有模型文件哈希不符，拒绝覆盖：{filename}")
        return {"file": filename, "status": "already_verified", "sha256": details["sha256"]}

    fd, temporary = tempfile.mkstemp(prefix=".ledger-model-", suffix=".tmp", dir=directory)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as output, urlopen(details["url"], timeout=60) as response:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > MAX_MODEL_BYTES:
                    raise ValueError(f"模型下载超过单文件上限：{filename}")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if size == 0:
            raise ValueError(f"模型下载内容为空：{filename}")
        if digest.hexdigest() != details["sha256"]:
            raise ValueError(f"模型 SHA-256 不符，拒绝发布：{filename}")
        os.link(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"file": filename, "status": "downloaded_and_verified", "sha256": details["sha256"]}


def prepare(model_dir):
    if importlib.metadata.version("rapidocr") != RAPIDOCR_VERSION:
        raise ValueError(f"仅支持 rapidocr=={RAPIDOCR_VERSION} 的固定模型包")
    directory = Path(model_dir).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"模型目录必须已存在，不自动创建：{directory}")
    return [_download_one(directory, name, details) for name, details in MODELS.items()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, help="RapidOCR 安装包的 models 目录；必须已存在")
    args = parser.parse_args(argv)
    results = prepare(args.model_dir)
    print(json.dumps({
        "purpose": "显式下载固定版本本地 OCR 模型；仅供虚构数据试用",
        "rapidocr_version": RAPIDOCR_VERSION,
        "model_dir": str(Path(args.model_dir).expanduser().resolve()),
        "results": results,
        "network": "只访问代码内固定的 ModelScope v3.10.0 文件地址；每个文件经 SHA-256 校验后原子发布",
        "note": "此脚本不安装依赖；只有用户显式运行时才发起网络请求",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
