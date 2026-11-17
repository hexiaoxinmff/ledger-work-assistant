import tempfile
import unittest
import zipfile
from pathlib import Path
import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "usage" / "create_usage_guide.py"
spec = importlib.util.spec_from_file_location("create_usage_guide", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UsageGuideTests(unittest.TestCase):
    def test_creates_valid_docx_and_preserves_numbered_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "教程.docx"
            module.write_docx(output, "测试教程", "## 怎么用\n1. 第一步\n- 保留来源")
            self.assertTrue(output.is_file())
            with zipfile.ZipFile(output) as zf:
                document = zf.read("word/document.xml").decode("utf-8")
            self.assertIn("第一步", document)
            self.assertIn("保留来源", document)
            with self.assertRaises(FileExistsError):
                module.write_docx(output, "测试教程", "重复写入")

    def test_empty_content_rejected_by_caller_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                module.write_docx(Path(tmp) / "empty.docx", "测试教程", "")


if __name__ == "__main__":
    unittest.main()
