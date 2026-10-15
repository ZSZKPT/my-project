import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from import_tools.miaoshou import parse_price
from desktop.legacy import App

class PriceInputTest(unittest.TestCase):
    def test_common_price_formats(self):
        for value in ['29','29.90','２９．９０','29元','￥29.90','29 CNY',' 29.90 ']:
            self.assertAlmostEqual(parse_price(value),29.9 if '90' in value or '９０' in value else 29)
        for value in ['',None,'abc','29,90','-1','0','nan','inf']:
            with self.assertRaises(ValueError):parse_price(value)

    def test_empty_price_is_reported_before_processing(self):
        app=App.__new__(App);app.busy=False
        app.variables={key:SimpleNamespace(get=lambda v=value:v) for key,value in {'price':'','source':str(Path.cwd())}.items()}
        app.groups=[{'sku':'TEST'}];app.names=[SimpleNamespace(get=lambda:'字母印花')];app.scanned_source=Path.cwd()
        with patch('desktop.legacy.messagebox.showerror') as error,patch('desktop.legacy.threading.Thread') as thread:
            app.start()
            self.assertIn('统一申报价不能为空',error.call_args.args[1]);thread.assert_not_called()
