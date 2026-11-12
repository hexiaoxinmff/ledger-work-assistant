import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('pipeline',Path(__file__).resolve().parents[1]/'pipeline_pdf.py')
pipeline=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

class PipelinePreflight(unittest.TestCase):
    def test_failed_preflight_does_not_render_or_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'new_output'
            failed=subprocess.CompletedProcess([],1,'','synthetic missing model')
            with patch.object(pipeline.subprocess,'run',return_value=failed) as runner:
                with self.assertRaisesRegex(RuntimeError,'OCR版本与模型预检.*synthetic missing model'):
                    pipeline.run(Path(temporary)/'synthetic.pdf',output)
            self.assertEqual(runner.call_count,1)
            self.assertEqual(runner.call_args.args[0][-1],'--check-runtime')
            self.assertFalse(output.exists())

    def test_successful_preflight_proceeds_to_render(self):
        responses=[subprocess.CompletedProcess([],0,'{}',''),subprocess.CompletedProcess([],1,'','synthetic renderer failure')]
        with tempfile.TemporaryDirectory() as temporary,patch.object(pipeline.subprocess,'run',side_effect=responses) as runner:
            with self.assertRaisesRegex(RuntimeError,'PDF逐页渲染.*synthetic renderer failure'):
                pipeline.run(Path(temporary)/'synthetic.pdf',Path(temporary)/'output')
            self.assertEqual(runner.call_count,2)
            self.assertTrue(runner.call_args.args[0][1].endswith('render_pdf.py'))

if __name__=='__main__':unittest.main()
