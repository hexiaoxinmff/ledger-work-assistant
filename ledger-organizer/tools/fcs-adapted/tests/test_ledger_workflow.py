"""Synthetic reconciliation of missing amounts, duplicates, dates and provenance."""
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from openpyxl import load_workbook

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import config
import reconcile
import version

class LedgerWorkflow(unittest.TestCase):
    def test_quality_links_candidates_dates_and_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);left=directory/'left.csv';right=directory/'right.csv';output=directory/'result.xlsx'
            left_rows=[['B101','120.00','2026-10-01','ok'],['B102','200.00','2026-10-02','first\nsecond'],['B103','','2026-10-03','pending'],['B104','50.00','2026-10-04','check date'],['B105','30.00','2026-10-05','left only']]
            right_rows=[['B101','120.00','2026-10-01','ok'],['B102','80.00','2026-10-02','part one'],['B102','120.00','2026-10-02','part two'],['B103','0.00','2026-10-03','zero'],['B104','50.00','2026-10-05','next day'],['B106','20.00','2026-10-06','right only']]
            for path,rows in ((left,left_rows),(right,right_rows)):
                with path.open('w',encoding='utf-8-sig',newline='') as stream:csv.writer(stream).writerows([['ID','amount','date','note'],*rows])
            hashes={path:hashlib.sha256(path.read_bytes()).hexdigest() for path in (left,right)}
            fields=config.FieldMap('ID','amount','date',None,None)
            settings=config.ReconcileConfig(config.TableSpec(str(left),None,0,fields),config.TableSpec(str(right),None,0,fields),config.MatchConfig(direction_rule='none'),str(output),'synthetic','synthetic')
            summary=reconcile.run(settings,run_id='synthetic',run_at='')
            self.assertTrue(summary['quantity_reconciled'])
            self.assertIsNone(summary['amount_reconciled'])
            self.assertEqual(summary['missing_amount_count'],1)
            self.assertEqual(summary['counts']['多候选冲突'],3)
            workbook=load_workbook(output,read_only=True,data_only=False)
            try:
                audit=list(workbook['审计明细'].values)[1:]
                linked=[row for row in audit if row[1]=='B103']
                self.assertEqual({row[0] for row in linked},{'数据质量问题','疑似匹配'})
                self.assertTrue(all('L5' in row[5] and 'R5' in row[5] for row in linked))
                pending=list(workbook['待处理事项'].values)[1:]
                self.assertTrue(any(row[2]=='B104' and '日期超出容差' in row[6] for row in pending))
                for title,expected in [('左侧读取明细',left_rows),('右侧读取明细',right_rows)]:
                    actual=list(workbook[title].values)[1:]
                    self.assertEqual(len(actual),len(expected))
                    for row,original in zip(actual,expected):
                        self.assertEqual(['' if value is None else value for value in row[-4:]],original)
            finally:workbook.close()
            manifest=json.loads(Path(str(output)+'.manifest.json').read_text(encoding='utf8'))
            self.assertEqual(manifest['skill_version'],version.SKILL_VERSION)
            self.assertTrue(manifest['run_at'])
            self.assertEqual(manifest['outputs'][0]['sha256'],hashlib.sha256(output.read_bytes()).hexdigest())
            saved=hashlib.sha256(output.read_bytes()).hexdigest()
            with self.assertRaises(FileExistsError):reconcile.run(settings,run_id='repeat',run_at='')
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(),saved)
            self.assertEqual({path:hashlib.sha256(path.read_bytes()).hexdigest() for path in (left,right)},hashes)


    def test_large_decimal_differences_and_totals_are_not_rounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            left, right, output = directory/'left.csv', directory/'right.csv', directory/'result.xlsx'
            amount = '9' * 26 + '.99'
            amount_cents = int(amount.replace('.', ''))

            def format_cents(value):
                sign = '-' if value < 0 else ''
                absolute = abs(value)
                return f"{sign}{absolute // 100}.{absolute % 100:02d}"

            ids = ['B201', 'B202']
            left_rows = [[key, amount, '2026-11-01', 'large positive'] for key in ids]
            right_rows = [[key, '-' + amount, '2026-11-01', 'large negative'] for key in ids]
            for path, rows in ((left, left_rows), (right, right_rows)):
                with path.open('w', encoding='utf-8-sig', newline='') as stream:
                    csv.writer(stream).writerows([['ID', 'amount', 'date', 'note'], *rows])

            fields = config.FieldMap('ID', 'amount', 'date', None, None)
            settings = config.ReconcileConfig(
                config.TableSpec(str(left), None, 0, fields),
                config.TableSpec(str(right), None, 0, fields),
                config.MatchConfig(direction_rule='none'), str(output), 'synthetic', 'synthetic'
            )
            summary = reconcile.run(settings, run_id='large-decimal', run_at='')

            expected_side_total = format_cents(amount_cents * len(ids))
            expected_diff = format_cents(amount_cents * len(ids) * 2)
            expected_pair_diff = format_cents(amount_cents * 2)
            self.assertEqual(summary['left_amount_total'], expected_side_total)
            self.assertEqual(summary['right_amount_total'], '-' + expected_side_total)
            self.assertEqual(summary['sum_amount_diff'], expected_diff)
            self.assertTrue(summary['amount_reconciled'])

            workbook = load_workbook(output, read_only=True, data_only=False)
            try:
                audit = list(workbook['审计明细'].values)
                pair_diffs = {row[1]: row[4] for row in audit[1:]}
                self.assertEqual(pair_diffs, {key: expected_pair_diff for key in ids})
                overview = list(workbook['对账总览'].values)
                self.assertEqual(overview[4][1], expected_side_total)
                self.assertEqual(overview[5][1], '-' + expected_side_total)
            finally:
                workbook.close()


    def test_failed_publish_removes_only_our_reservations(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            left, right, output = directory/'left.csv', directory/'right.csv', directory/'result.xlsx'
            rows = [['B301', '10.00', '2026-11-01', 'ok']]
            for path in (left, right):
                with path.open('w', encoding='utf-8', newline='') as stream:
                    csv.writer(stream).writerows([['ID', 'amount', 'date', 'note'], *rows])
            fields = config.FieldMap('ID', 'amount', 'date', None, None)
            settings = config.ReconcileConfig(
                config.TableSpec(str(left), None, 0, fields),
                config.TableSpec(str(right), None, 0, fields),
                config.MatchConfig(direction_rule='none'),
                str(output), 'synthetic', 'synthetic'
            )
            with mock.patch.object(
                reconcile.reporter, 'write_workbook',
                side_effect=RuntimeError('synthetic write failure')
            ):
                with self.assertRaisesRegex(RuntimeError, 'synthetic write failure'):
                    reconcile.run(settings, run_id='publish-failure', run_at='')
            self.assertFalse(output.exists())
            self.assertFalse(Path(str(output) + '.manifest.json').exists())

if __name__=='__main__':unittest.main()
