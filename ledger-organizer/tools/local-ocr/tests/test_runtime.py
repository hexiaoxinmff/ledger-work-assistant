import hashlib
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('recognizer',Path(__file__).resolve().parents[1]/'recognize_image.py')
recognizer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(recognizer)

class RuntimeChecks(unittest.TestCase):
    def test_wrong_version(self):
        with patch.object(recognizer.metadata,'version',return_value='unsupported'):
            with self.assertRaisesRegex(ValueError,'仅测试'):recognizer.check_runtime()

    def test_missing_corrupt_and_matching_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            models=directory/'models';models.mkdir()
            expected=hashlib.sha256(b'synthetic model').hexdigest()
            versions={'rapidocr':'3.10.0','onnxruntime':'1.20.1'}
            with patch.object(recognizer.metadata,'version',side_effect=versions.__getitem__),patch.object(recognizer.importlib.util,'find_spec',return_value=SimpleNamespace(origin=str(directory/'__init__.py'))),patch.object(recognizer,'EXPECTED_MODELS',{'synthetic.onnx':expected}):
                with self.assertRaisesRegex(ValueError,'缺失或哈希不符'):recognizer.check_runtime()
                (models/'synthetic.onnx').write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError,'缺失或哈希不符'):recognizer.check_runtime()
                (models/'synthetic.onnx').write_bytes(b'synthetic model')
                self.assertEqual(recognizer.check_runtime()['models_verified'],['synthetic.onnx'])

if __name__=='__main__':unittest.main()
