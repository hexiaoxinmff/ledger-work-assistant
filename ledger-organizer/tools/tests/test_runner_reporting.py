"""Ensure suite selection and not-run reporting stay truthful."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS))
import run_checks

class RunnerReporting(unittest.TestCase):
    def test_suite_selection_and_unrun_groups(self):
        expected={
            'core':{'tools/fcs-adapted/tests','tools/pdf-text/tests','tools/local-ocr/tests'},
            'ledger':{'tools/tests','tools/format-conversion/tests','tools/document-to-excel/tests','tools/pdf-text/tests','tools/local-ocr/tests'},
            'pdf-text':{'tools/tests','tools/format-conversion/tests','tools/document-to-excel/tests','tools/fcs-adapted/tests','tools/local-ocr/tests'},
            'ocr':{'tools/tests','tools/format-conversion/tests','tools/document-to-excel/tests','tools/fcs-adapted/tests','tools/pdf-text/tests'},
            'all':set(),
        }
        for suite,not_run in expected.items():
            with self.subTest(suite=suite):
                output=io.StringIO()
                with patch.object(sys,'argv',['run_checks.py','--suite',suite]), \
                     patch.object(run_checks,'run_suite',return_value={'status':'passed'}), \
                     contextlib.redirect_stdout(output):
                    self.assertEqual(run_checks.main(),0)
                report=json.loads(output.getvalue())
                self.assertEqual(set(report['not_run']),not_run)
                self.assertEqual(len(report['results']),len(run_checks.SUITES[suite]))

if __name__=='__main__':unittest.main()
