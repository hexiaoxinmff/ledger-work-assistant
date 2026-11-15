"""Synthetic tests for OCR output publication; no OCR runtime or network is used."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import types
import unittest
import zlib
from unittest import mock
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("recognize_image", HERE / "recognize_image.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


MODEL_PATHS = {
    "PP-OCRv6_det_small.onnx": "/synthetic/models/det.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx": "/synthetic/models/cls.onnx",
    "PP-OCRv6_rec_small.onnx": "/synthetic/models/rec.onnx",
}
EXPECTED_PARAMS = {
    "Det.engine_type": "onnxruntime",
    "Det.model_path": MODEL_PATHS["PP-OCRv6_det_small.onnx"],
    "Cls.engine_type": "onnxruntime",
    "Cls.model_path": MODEL_PATHS["ch_ppocr_mobile_v2.0_cls_mobile.onnx"],
    "Rec.engine_type": "onnxruntime",
    "Rec.model_path": MODEL_PATHS["PP-OCRv6_rec_small.onnx"],
}


class ImageOutputSafety(unittest.TestCase):
    def png_bytes(self, width=1, height=1):
        def chunk(kind, payload):
            crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        pixels = zlib.compress(b"\x00\x00\x00\x00\x00")
        return b"\x89PNG\\r\\n\x1a\\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")

    def fixture(self, directory):
        source = directory / "synthetic.png"
        source.write_bytes(self.png_bytes())
        output = directory / "recognition.json"
        return source, output

    def test_header_preflight_accepts_png_and_jpeg_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            png = directory / "sample.png"
            png.write_bytes(self.png_bytes(400, 300))
            self.assertEqual(MODULE._preflight_image(png), {"width": 400, "height": 300})

            jpeg = directory / "sample.jpg"
            frame = bytes([8]) + struct.pack(">HH", 240, 320) + bytes([3, 1, 0x11, 0, 2, 0x11, 0, 3, 0x11, 0])
            jpeg.write_bytes(b"\xff\xd8\xff\xc0" + struct.pack(">H", len(frame) + 2) + frame)
            self.assertEqual(MODULE._preflight_image(jpeg), {"width": 320, "height": 240})

    def test_file_size_limit_is_enforced(self):
        MODULE._check_image_size(MODULE.MAX_IMAGE_BYTES)
        with self.assertRaisesRegex(ValueError, "100 MiB"):
            MODULE._check_image_size(MODULE.MAX_IMAGE_BYTES + 1)

    def test_oversized_pixel_dimensions_are_rejected_before_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "oversized.png"
            source.write_bytes(self.png_bytes(5001, 5000))
            output = directory / "recognition.json"
            with (
                mock.patch.object(MODULE, "check_runtime") as runtime,
                mock.patch.object(MODULE, "_recognize_without_python_socket_access") as recognize,
            ):
                with self.assertRaisesRegex(ValueError, "2500 万像素"):
                    MODULE.run(source, output)
            runtime.assert_not_called()
            recognize.assert_not_called()
            self.assertFalse(output.exists())

    def test_invalid_or_mismatched_image_header_is_rejected_before_runtime(self):
        jpeg_header = b"\xff\xd8\xff\xc0\x00\x11" + bytes([8]) + struct.pack(">HH", 1, 1) + bytes([3, 1, 0x11, 0, 2, 0x11, 0, 3, 0x11, 0])
        cases = (("fake.png", b"not an image"), ("jpeg.png", jpeg_header))
        for name, content in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                source = directory / name
                source.write_bytes(content)
                output = directory / "recognition.json"
                with mock.patch.object(MODULE, "check_runtime") as runtime:
                    with self.assertRaises(ValueError):
                        MODULE.run(source, output)
                runtime.assert_not_called()
                self.assertFalse(output.exists())

    def fake_ocr(self, *, observed_socket_methods=None, observed_params=None):
        package = types.ModuleType("rapidocr")

        class FakeRapidOCR:
            def __init__(self, params=None):
                if observed_params is not None:
                    observed_params.append(params)

            def __call__(self, source):
                if observed_socket_methods is not None:
                    observed_socket_methods.append(
                        (socket.socket.connect, socket.socket.connect_ex)
                    )
                return SimpleNamespace(
                    txts=["00042"],
                    boxes=[[[0, 0], [1, 0], [1, 1], [0, 1]]],
                    scores=[0.99],
                )

        package.RapidOCR = FakeRapidOCR
        return package

    def run_fake(self, source, output, observed_socket_methods=None, observed_params=None):
        runtime = {"model_paths": MODEL_PATHS}
        with mock.patch.object(MODULE, "check_runtime", return_value=runtime), mock.patch.dict(
            sys.modules, {"rapidocr": self.fake_ocr(
                observed_socket_methods=observed_socket_methods,
                observed_params=observed_params,
            )}
        ):
            return MODULE.run(source, output)

    def test_success_restores_socket_methods_and_marks_result_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = self.fixture(directory)
            original_connect = socket.socket.connect
            original_connect_ex = socket.socket.connect_ex
            seen = []
            params_seen = []
            self.assertEqual(self.run_fake(source, output, seen, params_seen), 1)
            self.assertEqual(params_seen, [EXPECTED_PARAMS])
            self.assertEqual(len(seen), 1)
            self.assertIsNot(seen[0][0], original_connect)
            self.assertIsNot(seen[0][1], original_connect_ex)
            self.assertIs(socket.socket.connect, original_connect)
            self.assertIs(socket.socket.connect_ex, original_connect_ex)
            data = json.loads(output.read_text(encoding="utf8"))
            self.assertEqual(data["来源sha256"], digest(source))
            self.assertEqual(data["结果"][0]["识别文本"], "00042")
            self.assertEqual(data["识别状态"], "已检出候选，全部待人工复核")
            self.assertEqual(data["识别条数"], 1)
            self.assertEqual(data["结果"][0]["复核状态"], "待人工核对原图")
            self.assertEqual(list(directory.glob(".ledger-ocr-*")), [])

    def test_invalid_scores_and_boxes_are_rejected_before_publication(self):
        valid_box = [[0, 0], [1, 0], [1, 1], [0, 1]]
        cases = [
            ("nan score", valid_box, float("nan"), "模型分数必须为 0 至 1 的有限数"),
            ("infinite score", valid_box, float("inf"), "模型分数必须为 0 至 1 的有限数"),
            ("out of range score", valid_box, 1.01, "模型分数必须为 0 至 1 的有限数"),
            ("boolean score", valid_box, True, "模型分数必须为 0 至 1 的有限数"),
            ("non-finite coordinate", [[0, 0], [1, 0], [1, float("nan")], [0, 1]], 0.99, "边界框坐标必须为有限数"),
            ("wrong corner count", [[0, 0], [1, 0], [1, 1]], 0.99, "必须包含四个角点"),
        ]
        for label, box, score, message in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                source, output = self.fixture(Path(temporary))
                result = SimpleNamespace(txts=["00042"], boxes=[box], scores=[score])
                with (
                    mock.patch.object(MODULE, "check_runtime", return_value={"model_paths": MODEL_PATHS}),
                    mock.patch.object(MODULE, "_recognize_without_python_socket_access", return_value=result),
                ):
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.run(source, output)
                self.assertFalse(output.exists())
                self.assertEqual(list(Path(temporary).glob(".ledger-ocr-*")), [])

    def test_no_detection_is_explicit_and_partial_result_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = self.fixture(directory)
            empty_result = SimpleNamespace(txts=None, boxes=None, scores=None)
            with (
                mock.patch.object(MODULE, "check_runtime", return_value={"model_paths": MODEL_PATHS}),
                mock.patch.object(MODULE, "_recognize_without_python_socket_access", return_value=empty_result),
            ):
                self.assertEqual(MODULE.run(source, output), 0)
            data = json.loads(output.read_text(encoding="utf8"))
            self.assertEqual(data["结果"], [])
            self.assertEqual(data["识别条数"], 0)
            self.assertIn("不能据此判断原图空白", data["识别状态"])
            self.assertIn("人工查看", data["识别状态"])

        with tempfile.TemporaryDirectory() as temporary:
            source, output = self.fixture(Path(temporary))
            partial_result = SimpleNamespace(txts=None, boxes=[], scores=[])
            with (
                mock.patch.object(MODULE, "check_runtime", return_value={"model_paths": MODEL_PATHS}),
                mock.patch.object(MODULE, "_recognize_without_python_socket_access", return_value=partial_result),
            ):
                with self.assertRaisesRegex(ValueError, "识别字段不完整"):
                    MODULE.run(source, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temporary).glob(".ledger-ocr-*")), [])

    def test_write_and_readback_failures_leave_no_final_or_temporary_file(self):
        for failure in ("write", "readback"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                source, output = self.fixture(directory)
                with mock.patch.object(MODULE, "check_runtime", return_value={"model_paths": MODEL_PATHS}), mock.patch.dict(
                    sys.modules, {"rapidocr": self.fake_ocr()}
                ):
                    if failure == "write":
                        context = mock.patch.object(
                            MODULE.json, "dump", side_effect=OSError("synthetic write failure")
                        )
                        expected = "synthetic write failure"
                        exception = OSError
                    else:
                        context = mock.patch.object(
                            MODULE.json, "load", side_effect=ValueError("synthetic readback failure")
                        )
                        expected = "synthetic readback failure"
                        exception = ValueError
                    with context, self.assertRaisesRegex(exception, expected):
                        MODULE.run(source, output)
                self.assertFalse(output.exists())
                self.assertEqual(list(directory.glob(".ledger-ocr-*")), [])

    def test_source_change_after_staging_prevents_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = self.fixture(directory)
            original_sha = MODULE.sha
            hashes = []

            def changed_on_final_check(path):
                if Path(path).resolve() == source.resolve():
                    hashes.append(True)
                    if len(hashes) == 3:
                        return "changed"
                return original_sha(path)

            with mock.patch.object(MODULE, "check_runtime", return_value={"model_paths": MODEL_PATHS}), mock.patch.dict(
                sys.modules, {"rapidocr": self.fake_ocr()}
            ), mock.patch.object(MODULE, "sha", side_effect=changed_on_final_check):
                with self.assertRaisesRegex(ValueError, "原图在识别期间变化"):
                    MODULE.run(source, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(directory.glob(".ledger-ocr-*")), [])

    def test_existing_destination_is_preserved_without_running_ocr(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = self.fixture(directory)
            output.write_bytes(b"existing output")
            with mock.patch.object(MODULE, "check_runtime", return_value={"model_paths": MODEL_PATHS}) as check:
                with self.assertRaises(FileExistsError):
                    MODULE.run(source, output)
            check.assert_not_called()
            self.assertEqual(output.read_bytes(), b"existing output")

    def test_concurrent_destination_creation_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, output = self.fixture(directory)
            real_link = MODULE.os.link

            def competing_writer(staged, destination):
                Path(destination).write_bytes(b"other writer")
                return real_link(staged, destination)

            with mock.patch.object(MODULE, "check_runtime", return_value={"model_paths": MODEL_PATHS}), mock.patch.dict(
                sys.modules, {"rapidocr": self.fake_ocr()}
            ), mock.patch.object(MODULE.os, "link", side_effect=competing_writer):
                with self.assertRaises(FileExistsError):
                    MODULE.run(source, output)
            self.assertEqual(output.read_bytes(), b"other writer")
            self.assertEqual(list(directory.glob(".ledger-ocr-*")), [])


if __name__ == "__main__":
    unittest.main()
