"""Offline tests for explicit pinned OCR model preparation."""
import hashlib
import importlib.util
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "prepare_models.py"
SPEC = importlib.util.spec_from_file_location("prepare_models", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareModelTests(unittest.TestCase):
    def setUp(self):
        self.payload = b"fictional-model-bytes"
        self.details = {
            "sample.onnx": {
                "url": "https://models.example.invalid/sample.onnx",
                "sha256": hashlib.sha256(self.payload).hexdigest(),
            }
        }

    def prepared(self, directory, payload=None):
        response = BytesIO(self.payload if payload is None else payload)
        with (
            mock.patch.object(MODULE.importlib.metadata, "version", return_value="3.10.0"),
            mock.patch.object(MODULE, "MODELS", self.details),
            mock.patch.object(MODULE, "package_model_dir", return_value=directory),
            mock.patch.object(MODULE, "urlopen", return_value=response) as opener,
        ):
            result = MODULE.prepare()
        return result, opener

    def test_download_publishes_only_hash_verified_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, opener = self.prepared(Path(temporary))
            target = Path(temporary) / "sample.onnx"
            self.assertEqual(target.read_bytes(), self.payload)
            self.assertEqual(result[0]["status"], "downloaded_and_verified")
            opener.assert_called_once_with(self.details["sample.onnx"]["url"], timeout=60)
            self.assertEqual(list(Path(temporary).glob(".ledger-model-*")), [])

    def test_bad_hash_does_not_publish_or_leave_temp_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            with (
                mock.patch.object(MODULE.importlib.metadata, "version", return_value="3.10.0"),
                mock.patch.object(MODULE, "MODELS", self.details),
                mock.patch.object(MODULE, "package_model_dir", return_value=Path(temporary)),
                mock.patch.object(MODULE, "urlopen", return_value=BytesIO(b"tampered")),
            ):
                with self.assertRaisesRegex(ValueError, "SHA-256 不符"):
                    MODULE.prepare()
            self.assertFalse((Path(temporary) / "sample.onnx").exists())
            self.assertEqual(list(Path(temporary).glob(".ledger-model-*")), [])

    def test_existing_matching_model_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "sample.onnx"
            target.write_bytes(self.payload)
            with (
                mock.patch.object(MODULE.importlib.metadata, "version", return_value="3.10.0"),
                mock.patch.object(MODULE, "MODELS", self.details),
                mock.patch.object(MODULE, "package_model_dir", return_value=Path(temporary)),
                mock.patch.object(MODULE, "urlopen") as opener,
            ):
                result = MODULE.prepare()
            opener.assert_not_called()
            self.assertEqual(result[0]["status"], "already_verified")

    def test_existing_mismatched_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "sample.onnx"
            target.write_bytes(b"keep existing")
            with (
                mock.patch.object(MODULE.importlib.metadata, "version", return_value="3.10.0"),
                mock.patch.object(MODULE, "MODELS", self.details),
                mock.patch.object(MODULE, "urlopen") as opener,
            ):
                with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
                    MODULE.prepare()
            opener.assert_not_called()
            self.assertEqual(target.read_bytes(), b"keep existing")

    def test_size_limit_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            with (
                mock.patch.object(MODULE.importlib.metadata, "version", return_value="3.10.0"),
                mock.patch.object(MODULE, "MODELS", self.details),
                mock.patch.object(MODULE, "package_model_dir", return_value=Path(temporary)),
                mock.patch.object(MODULE, "MAX_MODEL_BYTES", 4),
                mock.patch.object(MODULE, "urlopen", return_value=BytesIO(self.payload)),
            ):
                with self.assertRaisesRegex(ValueError, "单文件上限"):
                    MODULE.prepare()
            self.assertEqual(list(Path(temporary).glob(".ledger-model-*")), [])

    def test_wrong_runtime_version_stops_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            with (
                mock.patch.object(MODULE.importlib.metadata, "version", return_value="unsupported"),
                mock.patch.object(MODULE, "urlopen") as opener,
            ):
                with self.assertRaisesRegex(ValueError, "仅支持 rapidocr"):
                    MODULE.prepare()
            opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
