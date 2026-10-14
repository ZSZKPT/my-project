import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]

class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        data = Path(cls.temp.name)
        (data / 'images' / 'ABC').mkdir(parents=True)
        (data / 'images' / 'ABC' / 'ABC.png').write_bytes(b'fixture-image')
        (data / 'images' / 'outside.png').symlink_to('/etc/passwd')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.base = f'http://127.0.0.1:{port}'
        cls.process = subprocess.Popen(['python3', str(ROOT / 'app.py')], env=dict(os.environ, TEMU_DATA_DIR=str(data), PORT=str(port)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                cls.call('/api/health')
                return
            except OSError:
                time.sleep(.05)
        cls.process.terminate()
        cls.process.wait()
        cls.temp.cleanup()
        raise RuntimeError('server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.temp.cleanup()

    @classmethod
    def call(cls, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = Request(cls.base + path, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_full_workflow_and_idempotency(self):
        _, state = self.call('/api/state')
        self.assertEqual(state['images'], [{'sku': 'ABC', 'images': ['ABC/ABC.png'], 'print_name': ''}])
        template = {'name':'T恤','title':'印花 {print_name}', 'source_product_id':'template-123','category':'123','description':'共用详情','variants':[{'size':'S','price':39.9,'stock':100}]}
        status, saved = self.call('/api/templates', template)
        self.assertEqual(status, 201)
        payload = {'template_id':saved['id'],'skus':['ABC']}
        self.assertEqual(self.call('/api/generate', payload)[0], 400)
        self.assertEqual(self.call('/api/print-names', {'entries':[{'sku':'ABC','name':'爱心花朵'}]})[0],200)
        self.assertEqual(self.call('/api/generate', payload)[1], {'created':1,'skipped':0})
        self.assertEqual(self.call('/api/generate', payload)[1], {'created':0,'skipped':1})
        _, exported = self.call('/api/export')
        self.assertFalse(exported['official_api_payload'])
        self.assertEqual(exported['products'][0]['skc'], 'ABC')
        self.assertEqual(exported['products'][0]['source_product_id'], 'template-123')
        self.assertEqual(exported['products'][0]['title'], '印花 爱心花朵')
        self.assertEqual(exported['products'][0]['variants'][0]['seller_sku'], 'ABC-S')
        _, state = self.call('/api/state')
        status, _ = self.call('/api/submit', {'draft_id':state['drafts'][0]['id']})
        self.assertEqual(status, 409)
        _, state = self.call('/api/state')
        self.assertEqual(state['tasks'][0]['status'], 'blocked')
        self.assertEqual(state['drafts'][0]['status'], 'draft')

    def test_validation_and_path_security(self):
        self.assertEqual(self.call('/api/templates', {'name':'invalid'})[0], 400)
        self.assertEqual(self.call('/api/generate', {'template_id':'missing','skus':['ABC']})[0], 400)
        self.assertEqual(self.call('/image?path=../../etc/passwd')[0], 403)
        self.assertEqual(self.call('/image?path=outside.png')[0], 403)
        with urlopen(self.base + '/', timeout=3) as response:
            self.assertIn('Temu 印花上架工作台', response.read().decode())

if __name__ == '__main__':
    unittest.main()
