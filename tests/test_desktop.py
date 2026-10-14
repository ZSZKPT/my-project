import tempfile
import unittest
from pathlib import Path
from PIL import Image
from desktop.core import discover, prepare

class DesktopTest(unittest.TestCase):
    def test_order_crop_and_preservation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source'/'ABC';source.mkdir(parents=True)
            for name in ['ABC-细节10.jpg','ABC-后.jpg','ABC-前1.jpg','ABC-前.jpg','ABC-细节2.jpg']:
                Image.new('RGB',(1350,1800),'red').save(source/name)
            before={p.name:p.read_bytes() for p in source.iterdir()}
            groups=discover(root/'source')
            self.assertEqual([p.name for p in groups[0]['files']],['ABC-前.jpg','ABC-前1.jpg','ABC-后.jpg','ABC-细节2.jpg','ABC-细节10.jpg'])
            ready=prepare(groups[0],root/'out',1000)
            with Image.open(ready['material']) as im:self.assertEqual(im.size,(1000,1000))
            self.assertEqual(before,{p.name:p.read_bytes() for p in source.iterdir()})
            self.assertEqual(len(ready['carousel']),5)
            with self.assertRaises(FileExistsError):prepare(groups[0],root/'out')
