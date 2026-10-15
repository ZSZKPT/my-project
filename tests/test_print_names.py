import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook
from desktop.print_names import read_names,title_for

class PrintNamesTest(unittest.TestCase):
    def test_xlsx_matches_sku_preserving_zeros(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'names.xlsx';w=Workbook();s=w.active;s.append(['货号','印花名称']);s.append(['001','爱心']);s.append(['ABC','字母印花']);w.save(p)
            self.assertEqual(read_names(p),{'001':'爱心','ABC':'字母印花'})
            self.assertEqual(title_for('女士{print_name}印花套装','字母印花','ABC'),'女士字母印花套装')

    def test_csv_and_invalid_rows(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'names.csv';p.write_text('货号,印花名称\nABC,花朵\n',encoding='utf-8-sig')
            self.assertEqual(read_names(p),{'ABC':'花朵'})
            p.write_text('货号,印花名称\nABC,花朵\nABC,爱心\n',encoding='utf-8-sig')
            with self.assertRaises(ValueError):read_names(p)
            p.write_text('货号,印花名称\nABC,\n',encoding='utf-8-sig')
            with self.assertRaises(ValueError):read_names(p)
            with self.assertRaises(ValueError):title_for('没有占位符','花朵','ABC')
