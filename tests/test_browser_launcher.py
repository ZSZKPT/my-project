import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('browser_launcher', Path(__file__).resolve().parents[1] / 'windows' / 'browser.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class BrowserLauncherTest(unittest.TestCase):
    def test_url_restriction(self):
        valid = 'https://agentseller.temu.com/goods/edit?productDraftId=9091908599'
        self.assertEqual(module.validate_url(valid), valid)
        for bad in ['http://agentseller.temu.com/', 'https://evil.com/', 'https://agentseller.temu.com.evil.com/', 'https://u:p@agentseller.temu.com/', 'https://agentseller.temu.com:9222/']:
            with self.assertRaises(ValueError):
                module.validate_url(bad)

    def test_source_and_draft_distinction(self):
        self.assertEqual(module.page_kind('https://agentseller.temu.com/goods/edit?productId=3902709609'), 'existing-product')
        self.assertEqual(module.page_kind('https://agentseller.temu.com/goods/edit?productDraftId=9091908599'), 'draft')
