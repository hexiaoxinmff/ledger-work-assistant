"""Synthetic regression for dangerous CSV formula prefixes."""
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

HERE = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("convert_table", HERE / "convert_table.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FormulaPrefixGuard(unittest.TestCase):
    def test_rejects_ascii_control_and_fullwidth_formula_prefixes(self):
        prefixes = ("=", "+", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠")
        for prefix in prefixes:
            with self.subTest(prefix=repr(prefix)), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                source = directory / "source.xlsx"
                output = directory / "result.csv"
                workbook = Workbook()
                cell = workbook.active["A1"]
                cell.value = prefix + "1+1"
                cell.data_type = "s"
                workbook.save(source)
                workbook.close()

                with self.assertRaisesRegex(ValueError, "可能被电子表格执行的文本"):
                    MODULE.run(str(source), str(output), allow_display_loss=True)
                self.assertFalse(output.exists())
                self.assertEqual(list(directory.glob(".ledger-conversion-*")), [])

    def test_plain_negative_amount_remains_exportable(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "source.xlsx"
            output = directory / "result.csv"
            workbook = Workbook()
            cell = workbook.active["A1"]
            cell.value = "-12.00"
            cell.data_type = "s"
            workbook.save(source)
            workbook.close()

            self.assertEqual(MODULE.run(str(source), str(output)), 1)
            with output.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(list(csv.reader(stream)), [["-12.00"]])


if __name__ == "__main__":
    unittest.main()
