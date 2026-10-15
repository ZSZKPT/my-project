import unittest
import tempfile
from pathlib import Path
from desktop.tasks import Task
from import_tools.image_rules import validate_count,validate_urls

class ImageRulesTest(unittest.TestCase):
    def test_boundaries_and_duplicates(self):
        for count in [5,10]:validate_count(count,'ABC')
        for count in [0,4,11]:
            with self.assertRaises(ValueError):validate_count(count,'ABC')
        with self.assertRaises(ValueError):validate_urls(['https://example.com/a.jpg']*5)

    def test_not_enough_images_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'output'
            with self.assertRaisesRegex(ValueError,'ABC（4张）'):
                Task.create({'output':str(output)}, {}, [{'sku':'ABC','files':[Path('x')]*4}])
            self.assertFalse(output.exists())

    def test_material_file_does_not_count_as_product_image(self):
        from PIL import Image
        from desktop.core import discover
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'ABC';root.mkdir()
            for name in ['前.jpg','后.jpg','细节1.jpg','细节2.jpg','ABC-素材图.jpg']:
                Image.new('RGB',(20,20),'red').save(root/name)
            groups=discover(root)
            self.assertEqual(len(groups[0]['files']),4)
            with self.assertRaises(ValueError):validate_count(len(groups[0]['files']))
