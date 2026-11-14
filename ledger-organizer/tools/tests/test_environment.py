import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('environment',Path(__file__).resolve().parents[1]/'check_environment.py')
environment=importlib.util.module_from_spec(spec)
spec.loader.exec_module(environment)

class EnvironmentChecks(unittest.TestCase):
    def test_import_and_missing_module(self):
        self.assertEqual(environment.probe('json')['status'],'imported')
        self.assertEqual(environment.probe('ledger_synthetic_missing_dependency')['status'],'import_failed')

    def test_pdf_text_task_checks_dependencies_and_entrypoint(self):
        self.assertEqual(environment.requirements['pdf_text'],('pypdfium2','openpyxl'))
        self.assertTrue(environment.tools['pdf_text'])
        self.assertEqual(environment.paths['pdf_text'],'document-to-excel/pdf_text_to_excel.py')

    def test_timeout_crash_and_bad_output(self):
        with patch.object(environment.subprocess,'run',side_effect=subprocess.TimeoutExpired('probe',15)):
            self.assertEqual(environment.probe('json')['status'],'timeout')
        with patch.object(environment.subprocess,'run',return_value=subprocess.CompletedProcess([],17,'','simulated crash')):
            self.assertEqual(environment.probe('json')['exit_code'],17)
        with patch.object(environment.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'unexpected','')):
            self.assertEqual(environment.probe('json')['status'],'invalid_probe_output')

if __name__=='__main__':unittest.main()
