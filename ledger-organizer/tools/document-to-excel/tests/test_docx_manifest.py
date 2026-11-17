"""Synthetic DOCX conversion manifest tests without business data."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "document-to-excel" / "docx_tables.py"
spec = importlib.util.spec_from_file_location("docx_tables", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class DocxManifest(unittest.TestCase):
 def test_manifest_records_source_and_numeric_review(self):
  with tempfile.TemporaryDirectory() as temporary:
   directory=Path(temporary)
   source=directory/"source.docx";output=directory/"review.xlsx"
   source.write_bytes(b"synthetic docx")
   with patch.object(module,"extract",return_value=[(1,1,1,"金额 12.30")]):
    self.assertEqual(module.run(source,output),1)
   manifest=json.loads(Path(str(output)+".manifest.json").read_text(encoding="utf-8"))
   self.assertEqual(manifest["extracted_cells"],1)
   self.assertEqual(manifest["numeric_candidates"],1)
   self.assertEqual(manifest["source_sha256"],module.sha(source))
   self.assertEqual(manifest["output_sha256"],module.output_sha256(output))

 def test_manifest_failure_removes_output(self):
  with tempfile.TemporaryDirectory() as temporary:
   directory=Path(temporary)
   source=directory/"source.docx";output=directory/"review.xlsx"
   source.write_bytes(b"synthetic docx")
   real_link=module.os.link
   calls=[]
   def fail_on_manifest(src,dst):
    calls.append(dst)
    if len(calls)==2:
     raise OSError("manifest link failure")
    return real_link(src,dst)
   with patch.object(module,"extract",return_value=[(1,1,1,"12.30")]):
    with patch.object(module.os,"link",side_effect=fail_on_manifest):
     with self.assertRaisesRegex(OSError,"manifest link failure"):
      module.run(source,output)
   self.assertFalse(output.exists())
   self.assertFalse(Path(str(output)+".manifest.json").exists())

if __name__=="__main__":
 unittest.main()
