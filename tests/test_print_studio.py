import base64
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from print_studio import api
from print_studio.core import load_image, mockup, pixels, proof, render, repeat, settings, template
from print_studio.jobs import Job

ASSETS = Path(__file__).resolve().parents[1] / 'print_studio/assets/demo'


def options(**kw):
    return settings({'width_cm': 10, 'height_cm': 12, 'tile_cm': 3, 'dpi': 72,
                     'offset_x_cm': 0, 'offset_y_cm': 0, **kw})


def png_bytes():
    stream = io.BytesIO(); Image.new('RGB', (24, 24), '#12ab89').save(stream, 'PNG'); return stream.getvalue()


class RepeatTests(unittest.TestCase):
    def test_repeat_offsets_match_direct_periodic_coordinates(self):
        tile = Image.new('RGB', (3, 2)); tile.putdata([(i*30, 20, 200-i*10) for i in range(6)])
        for dx, dy in [(0, 0), (1, -1), (17, 14), (-7, 3)]:
            result = repeat(tile, (10, 9), 3, (dx, dy))
            for x in range(10):
                for y in range(9): self.assertEqual(result.getpixel((x, y)), tile.getpixel(((x-dx)%3, (y-dy)%2)))

    def test_mask_protects_background_and_skin_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            Image.new('RGB', (10, 10), (200, 100, 40)).save(folder/'base.png')
            mask = Image.new('L', (10, 10), 0)
            for x in range(3, 7):
                for y in range(3, 7): mask.putpixel((x, y), 255)
            mask.save(folder/'mask.png')
            (folder/'template.json').write_text(json.dumps({'name': 'test', 'base': 'base.png', 'mask': 'mask.png', 'canvas_width_cm': 10}))
            result = mockup(Image.new('RGB', (2, 2), (1, 2, 3)), template(folder/'template.json'), options(shade=False))
            self.assertEqual(result.getpixel((0, 0)), (200, 100, 40)); self.assertEqual(result.getpixel((4, 4)), (1, 2, 3))

    def test_export_dimensions_dpi_and_originals_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = ASSETS/'geometric.png'; before = source.read_bytes()
            result = render(source, directory, options(), [template(ASSETS/'template.json')])
            with Image.open(Path(directory)/'满版印花画布.png') as image:
                self.assertEqual(image.size, (pixels(10, 72), pixels(12, 72)))
                self.assertAlmostEqual(image.info['dpi'][0], 72, delta=.1)
            self.assertEqual(before, source.read_bytes()); self.assertEqual(len(result), 5)
            with Image.open(Path(directory)/'平铺检查_2x2.png') as image: self.assertEqual(image.size, (512, 512))

    def test_invalid_numbers_limits_and_template_paths_are_rejected(self):
        for value in ('nan', 'inf', '-1', '', 'abc'):
            with self.assertRaises(ValueError): options(tile_cm=value)
        with self.assertRaises(ValueError): options(width_cm=300, height_cm=300, dpi=600)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'template.json'; path.write_text(json.dumps({'base':'../outside.png', 'mask':'mask.png'}))
            with self.assertRaises(ValueError): template(path)


class JobTests(unittest.TestCase):
    def test_resume_caches_completed_items_and_uses_snapshot_after_source_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'original.png'; source.write_bytes(png_bytes()); stop = threading.Event()
            job = Job.create([source], root/'out', options(), [ASSETS/'template.json'], stop=stop)
            source.unlink(); original = job.local(job.state['items'][0]['source']).read_bytes()
            stop.set()
            with self.assertRaises(InterruptedError): job.run()
            stop.clear(); job.run(); item = job.state['items'][0]; stamp = (job.root/item['id']/'满版印花画布.png').stat().st_mtime_ns
            with patch('print_studio.jobs.render', side_effect=AssertionError('must not render again')): Job(job.path).run()
            self.assertEqual(stamp, (job.root/item['id']/'满版印花画布.png').stat().st_mtime_ns)
            self.assertEqual(original, job.local(item['source']).read_bytes())
            (job.root/item['id']/'满版印花画布.png').write_bytes(b'changed')
            with self.assertRaises(ValueError): Job(job.path).run()

    def test_api_snapshot_has_no_key_and_job_budget_stops_before_second_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); inputs=[]
            for name in ['a.png', 'b.png']:
                p=root/name;p.write_bytes(png_bytes());inputs.append(p)
            config={'protocol':'openai_edit','endpoint':'https://example.com/v1/images/edits','model':'test-image','size':'1024x1024','prompt':'test', 'key':'NEVER-SAVE-THIS'}
            job=Job.create(inputs, root/'out', options(), api_config=config)
            raw=json.dumps({'data':[{'b64_json':base64.b64encode(png_bytes()).decode()}]}).encode()
            with patch('print_studio.api.request', return_value=raw) as request:
                with self.assertRaises(InterruptedError):job.run('TEST-KEY',max_new_requests=1)
                self.assertEqual(request.call_count,1)
                self.assertEqual(job.state['items'][0]['status'],'complete')
                Job(job.path).run('TEST-KEY',max_new_requests=1)
                self.assertEqual(request.call_count,2)
            self.assertNotIn('NEVER-SAVE-THIS',job.path.read_text())
            self.assertNotIn('TEST-KEY',job.path.read_text())
            self.assertEqual(Job(job.path).state['api_submissions'],2)

    def test_template_snapshot_modification_stops_render(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Job.create([ASSETS/'geometric.png'], directory, options(), [ASSETS/'template.json'])
            (job.root/'templates/1/base.png').write_bytes(png_bytes())
            with self.assertRaises(ValueError): job.run()


class APITests(unittest.TestCase):
    def config(self, protocol='openai_edit'):
        return {'endpoint':'https://example.com/images/edits','protocol':protocol,'model':'test-image','size':'1024x1024','prompt':'重建花型'}

    def test_protocols_send_reference_and_return_image(self):
        for protocol in ['openai_edit','dashscope']:
            with self.subTest(protocol=protocol),tempfile.TemporaryDirectory() as directory:
                target=Path(directory)/'AI.png'
                raw=json.dumps({'data':[{'b64_json':base64.b64encode(png_bytes()).decode()}]}).encode()
                with patch('print_studio.api.request',return_value=raw) as request:
                    api.generate(ASSETS/'geometric.png',target,self.config(protocol),'PRIVATE-KEY')
                    args=request.call_args.args
                    self.assertEqual(args[2],'PRIVATE-KEY');self.assertNotIn(b'PRIVATE-KEY',args[1])
                    if protocol=='dashscope':self.assertIn('data:image/png;base64,',json.loads(args[1])['input']['messages'][0]['content'][0]['image'])
                    else:self.assertIn(b'name="image"',args[1]);self.assertIn(b'name="n"',args[1])
                self.assertEqual(load_image(target).size,(24,24))
                self.assertNotIn('PRIVATE-KEY',target.with_suffix('.request.json').read_text())

    def test_download_failure_reuses_saved_result_without_resubmission(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'AI.png';raw=json.dumps({'data':[{'url':'https://example.com/signed.png?token=123'}]}).encode()
            with patch('print_studio.api.request',return_value=raw) as request,patch('print_studio.api.download_image',side_effect=api.APIError('download failed')):
                with self.assertRaises(api.APIError):api.generate(ASSETS/'geometric.png',target,self.config(),'KEY')
                self.assertEqual(request.call_count,1)
            with patch('print_studio.api.request',side_effect=AssertionError('must not resubmit')),patch('print_studio.api.download_image',return_value=png_bytes()):
                api.generate(ASSETS/'geometric.png',target,self.config(),'')
            self.assertTrue(target.is_file())

    def test_uncertain_request_requires_explicit_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'AI.png'
            with patch('print_studio.api.request',side_effect=api.APIUncertain('timeout')) as request:
                with self.assertRaises(api.APIUncertain):api.generate(ASSETS/'geometric.png',target,self.config(),'KEY')
                with self.assertRaises(api.APIUncertain):api.generate(ASSETS/'geometric.png',target,self.config(),'KEY')
                self.assertEqual(request.call_count,1)

    def test_protocol_response_formats_and_url_validation(self):
        self.assertEqual(api.extract_result({'output':{'choices':[{'message':{'content':[{'image':'https://example.com/a.png'}]}}]}}),('url','https://example.com/a.png'))
        with self.assertRaises(api.APIUncertain):api.extract_result({'output':{'task_id':'async'}})
        for url in ['http://example.com','https://user:secret@example.com','https://example.com/?key=secret']:
            with self.assertRaises(ValueError):api.secure_url(url)
        with self.assertRaises(api.APIError):api.write_result(b'<html>not an image</html>',Path('unused.png'))

    def test_model_lookup_is_a_get_and_uses_no_paid_image_endpoint(self):
        raw=json.dumps({'data':[{'id':'gpt-image-example'},{'id':'text-only'},{'id':'other-image'}]}).encode()
        with patch('print_studio.api.request',return_value=raw) as request:
            self.assertEqual(api.list_image_models('https://example.com/v1/images/edits','KEY'),['gpt-image-example','other-image'])
            request.assert_called_once_with('https://example.com/v1/models',key='KEY')


if __name__ == '__main__': unittest.main()
