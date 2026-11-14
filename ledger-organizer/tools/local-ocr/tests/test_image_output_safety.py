"""Synthetic tests for OCR output publication; no OCR runtime or network is used."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
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
    def fixture(self, directory):
        source = directory / "synthetic.png"
        source.write_bytes(b"synthetic image bytes")
        output = directory / "recognition.json"
        return source, output

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
            self.assertEqual(data["结果"][0]["复核状态"], "待人工核对原图")
            self.assertEqual(list(directory.glob(".ledger-ocr-*")), [])

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
