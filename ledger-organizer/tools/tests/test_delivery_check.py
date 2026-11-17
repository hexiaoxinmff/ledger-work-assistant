import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location("check_delivery",ROOT/"tools/check_delivery.py")
module=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

class DeliveryCheck(unittest.TestCase):
 def test_current_repository_versions_are_aligned(self):
  values,aligned=module.check_versions(ROOT)
  self.assertTrue(aligned,values)
  self.assertEqual(values["skill"],values["readme"])
  self.assertEqual(values["readme"],values["version_py"])

 def test_suspicious_filename_fails_without_reading_outside_root(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   (root/"ledger-organizer/tools/fcs-adapted/scripts").mkdir(parents=True)
   (root/"ledger-organizer/tools/fcs-adapted/scripts/version.py").write_text('SKILL_VERSION = "0.1"\n',encoding="utf-8")
   (root/"ledger-organizer/SKILL.md").write_text("# 费用与收款台账整理助手 v0.1\n",encoding="utf-8")
   (root/"README.md").write_text("当前技能版本：v0.1\n",encoding="utf-8")
   (root/"codex-clipboard-example.png").write_bytes(b"not read")
   report=module.scan(root)
   self.assertFalse(report["passed"])
   self.assertTrue(any(item["kind"]=="suspicious_filename" for item in report["findings"]))

 def test_sensitive_binary_extension_fails_without_opening_content(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   (root/"ledger-organizer/tools/fcs-adapted/scripts").mkdir(parents=True)
   (root/"ledger-organizer/tools/fcs-adapted/scripts/version.py").write_text('SKILL_VERSION = "0.1"\\n',encoding="utf-8")
   (root/"ledger-organizer/SKILL.md").write_text("# 费用与收款台账整理助手 v0.1\\n",encoding="utf-8")
   (root/"README.md").write_text("当前技能版本：v0.1\\n",encoding="utf-8")
   (root/"业务资料.pdf").write_bytes(b"binary content")
   report=module.scan(root)
   self.assertFalse(report["passed"])
   self.assertTrue(any(item["kind"]=="sensitive_binary_file" for item in report["findings"]))

if __name__=="__main__":
 unittest.main()
