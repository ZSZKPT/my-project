import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_bridge import NativeBridge
from test_pair_jpg import paired_project
from engine import solve


class FakeWindow:
    def __init__(self,path=None,url='http://127.0.0.1:1234/'):
        self.path=path;self.url=url;self.dialog_calls=0
    def get_current_url(self):return self.url
    def create_file_dialog(self,*args,**kwargs):
        self.dialog_calls+=1
        return (str(self.path),) if self.path is not None else None


class NativeSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.bridge=NativeBridge('http://127.0.0.1:1234')
        self.fake=FakeWindow(self.root/'output.jpg');self.bridge._window=self.fake
        module=SimpleNamespace(FileDialog=SimpleNamespace(SAVE=30))
        patcher=patch.dict(sys.modules,{'webview':module});patcher.start();self.addCleanup(patcher.stop)

    def test_native_jpg_save_renders_actual_110dpi_file(self):
        raw=paired_project();raw['placements']=solve(raw,threading.Event())['placements']
        reply=self.bridge.export_file('/api/export/jpg',{'project':raw},'生产.jpg')
        self.assertTrue(reply['saved']);self.assertEqual(self.fake.dialog_calls,1)
        with Image.open(self.fake.path) as image:self.assertEqual(image.info['dpi'],(110,110))
        self.assertFalse(list(self.root.glob('.buxu-*')))

    def test_cancel_native_save_does_not_write_or_overwrite(self):
        target=self.fake.path;target.write_bytes(b'keep-existing')
        self.fake.path=None
        reply=self.bridge.save_data(base64.b64encode(b'new').decode(),'preview.jpg')
        self.assertTrue(reply['cancelled']);self.assertEqual(target.read_bytes(),b'keep-existing')

    def test_external_navigation_cannot_use_file_bridge(self):
        self.fake.url='https://untrusted.example/'
        reply=self.bridge.save_data(base64.b64encode(b'abc').decode(),'project.json')
        self.assertIn('error',reply);self.assertEqual(self.fake.dialog_calls,0)
        self.assertFalse(self.fake.path.exists())

    def test_invalid_geometry_is_blocked_before_save_dialog(self):
        raw=paired_project()
        reply=self.bridge.export_file('/api/export/jpg',{'project':raw},'print.jpg')
        self.assertIn('error',reply);self.assertEqual(self.fake.dialog_calls,0)

    def test_project_save_uses_selected_path_and_atomic_write(self):
        self.fake.path=self.root/'原始项目.json'
        payload=json.dumps({'name':'裁片项目','dpi':110},ensure_ascii=False).encode()
        reply=self.bridge.save_data(base64.b64encode(payload).decode(),'project.json')
        self.assertTrue(reply['saved']);self.assertEqual(self.fake.path.read_bytes(),payload)
        self.assertTrue(self.bridge.info()['embedded'])


if __name__=='__main__':unittest.main()
