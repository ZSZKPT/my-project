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
            self.assertNotIn('NEVER-SAVE-THIS',job.path.read_text(encoding='utf-8'))
            self.assertNotIn('TEST-KEY',job.path.read_text(encoding='utf-8'))
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
                self.assertNotIn('PRIVATE-KEY',target.with_suffix('.request.json').read_text(encoding='utf-8'))

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


class WholeGarmentTests(unittest.TestCase):
    def sample_zip(self, root, name='YQ-TJDXTZ-67-S.jpg'):
        from PIL import ImageDraw
        from zipfile import ZipFile
        image=Image.new('RGB',(600,400),'white');draw=ImageDraw.Draw(image)
        draw.rectangle((20,20,240,300),fill='#121b41',outline='black',width=2)
        draw.rectangle((280,30,480,290),fill='white',outline='#333333',width=2)
        draw.rectangle((50,90,200,120),fill='white');draw.rectangle((320,60,350,260),fill='#131b40')
        draw.rectangle((510,320,550,340),fill='#dd2222')
        payload=io.BytesIO();image.save(payload,'JPEG',quality=98,dpi=(110,110))
        archive=root/'source.zip'
        with ZipFile(archive,'w') as z:
            z.writestr('YQ-TJDXTZ-67/'+name,payload.getvalue());z.writestr('YQ-TJDXTZ-67/Thumbs.db',b'ignored')
        return archive

    def test_cutting_zip_requires_review_and_keeps_pixel_size_dpi_and_marks(self):
        from print_studio.templates import import_zip,approve,update
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=self.sample_zip(root);before=archive.read_bytes()
            path=import_zip(archive,root/'templates','cutting')[0]
            spec=template(path,allow_draft=True);self.assertEqual(spec['source_dpi'],[110,110]);self.assertEqual(spec['size'],'S')
            self.assertEqual(len(spec['pieces']),2)
            with self.assertRaises(ValueError):template(path)
            approve(path);spec=template(path)
            original=load_image(spec['base']);rendered=mockup(Image.new('RGB',(5,5),'#12ab34'),spec,options(shade=True))
            self.assertEqual(rendered.size,original.size)
            for point in [(60,100),(330,100)]:self.assertEqual(rendered.getpixel(point),(18,171,52))
            for point in [(0,0),(530,330)]:self.assertEqual(rendered.getpixel(point),original.getpixel(point))
            target=root/'pattern.png';Image.new('RGB',(5,5),'#12ab34').save(target)
            outputs=render(target,root/'output',options(),[spec])
            cutting=next(p for p in outputs if p.name.startswith('裁片_'))
            with Image.open(cutting) as image:
                self.assertEqual(image.size,(600,400));self.assertAlmostEqual(image.info['dpi'][0],110,delta=.02)
            self.assertEqual(archive.read_bytes(),before)
            update(path,canvas_width_cm=123)
            with self.assertRaises(ValueError):template(path)

    def test_overlapping_piece_boxes_do_not_overwrite_other_component_orientation(self):
        from print_studio.templates import piece_mask
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=Image.new('RGB',(12,12),'white');base.save(root/'base.png')
            mask=Image.new('L',(12,12));draw=ImageDraw.Draw(mask)
            draw.rectangle((1,1,7,2),fill=255);draw.rectangle((1,1,2,7),fill=255);draw.rectangle((4,4,9,9),fill=255);mask.save(root/'mask.png')
            pieces=[{'box':[1,1,8,8],'seed':[1,1],'rotation':0},{'box':[4,4,10,10],'seed':[4,4],'rotation':180}]
            tile=Image.new('RGB',(2,1));tile.putdata([(255,0,0),(0,0,255)])
            spec={'base':root/'base.png','mask':root/'mask.png','canvas_width_cm':12,'kind':'cutting','pieces':pieces}
            result=mockup(tile,spec,options(tile_cm=2))
            self.assertEqual(result.getpixel((1,1)),(255,0,0));self.assertEqual(result.getpixel((4,4)),(0,0,255));self.assertEqual(result.getpixel((11,11)),(255,255,255))

    def test_mockup_import_is_a_blank_draft_and_cover_mode_removes_old_luminance(self):
        from print_studio.templates import import_zip,approve,update
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=import_zip(self.sample_zip(root),root/'templates','mockup')[0]
            spec=template(path,allow_draft=True)
            with Image.open(spec['mask']) as mask:self.assertIsNone(mask.getbbox())
            with self.assertRaises(ValueError):approve(path)
            Image.new('L',(600,400),255).save(spec['mask']);approve(path)
            image=mockup(Image.new('RGB',(1,1),'#12ab34'),template(path),options())
            self.assertEqual(image.getpixel((60,100)),image.getpixel((80,80)))

    def test_task_snapshot_preserves_cutting_fields_and_review(self):
        from print_studio.templates import import_zip,approve
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=import_zip(self.sample_zip(root),root/'templates','cutting')[0];approve(path)
            job=Job.create([ASSETS/'geometric.png'],root/'out',options(),[path]);snap=job.specs()[0]
            self.assertEqual(snap['kind'],'cutting');self.assertEqual(snap['source_dpi'],[110,110]);self.assertEqual(len(snap['pieces']),2)
            job.run();item=job.state['items'][0]
            self.assertTrue(any(Path(p).name.startswith('裁片_') for p in item['files']))
            with patch('print_studio.jobs.render',side_effect=AssertionError('must reuse outputs')):Job(job.path).run()

    def test_zip_path_traversal_is_rejected(self):
        from zipfile import ZipFile
        from print_studio.templates import import_zip
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'evil.zip'
            with ZipFile(path,'w') as z:z.writestr('../outside.png',png_bytes())
            with self.assertRaises(ValueError):import_zip(path,root/'templates')
            self.assertFalse((root/'outside.png').exists())


class BuiltinCaseTests(unittest.TestCase):
    def test_bundled_suite_has_clean_bases_matching_each_size(self):
        from print_studio.builtin import catalog
        from PIL import ImageChops
        root=ASSETS.parent/'case67';info,paths,pattern=catalog(root)
        self.assertEqual(len(paths),10);self.assertTrue(pattern.is_file())
        expected={'S':(6842,4121),'M':(6843,4371),'L':(6866,4542),'XL':(6843,5002),'2XL':(6874,5156)}
        cutting=[]
        for path in paths:
            spec=template(path)
            if spec['kind']=='cutting':
                base=load_image(spec['base']);self.assertEqual(base.size,expected[spec['size']]);self.assertEqual(spec['source_dpi'],[110,110])
                with Image.open(spec['mask']) as image:mask=image.convert('L')
                dirty=ImageChops.difference(base,Image.new('RGB',base.size,'white'))
                dirty=Image.composite(dirty,Image.new('RGB',base.size,'black'),mask)
                self.assertIsNone(dirty.getbbox(),'old artwork remains inside blank panel mask')
                self.assertEqual(len(spec['pieces']),10);cutting.append(spec['size'])
                base.close();mask.close();dirty.close()
        self.assertEqual(set(cutting),set(expected))

    def test_library_install_does_not_overwrite_user_edits(self):
        from print_studio.builtin import install,catalog
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();(source/'template.json').write_text('{}')
            (source/'pattern.png').write_bytes(png_bytes())
            (source/'catalog.json').write_text(json.dumps({'bundle_id':'test','templates':['template.json'],'pattern':'pattern.png'}))
            dest=install(source,root/'library');(dest/'my-edit.txt').write_text('keep')
            (dest/'template.json').write_text('{"custom":true}')
            install(source,dest)
            self.assertEqual((dest/'my-edit.txt').read_text(),'keep');self.assertEqual(json.loads((dest/'template.json').read_text()),{'custom':True})

    def test_openraster_has_editable_layers_and_valid_merged_image(self):
        from print_studio.layered import export_ora
        from zipfile import ZipFile
        from xml.etree.ElementTree import fromstring
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=Image.new('RGB',(10,10),'white');base.save(root/'base.png')
            mask=Image.new('L',(10,10),128);mask.save(root/'mask.png')
            effect=Image.composite(Image.new('RGB',(10,10),'blue'),base,mask)
            target=export_ora(root/'base.png',root/'mask.png',root/'layered.ora',effect)
            with ZipFile(target) as z:
                self.assertEqual(z.namelist()[0],'mimetype');self.assertEqual(z.read('mimetype'),b'image/openraster')
                stack=fromstring(z.read('stack.xml'));self.assertEqual(len(stack.find('stack').findall('layer')),3)
                self.assertEqual(load_image(root/'base.png').size,(int(stack.attrib['w']),int(stack.attrib['h'])))
                with Image.open(io.BytesIO(z.read('data/pattern.png'))) as image:
                    merged=Image.alpha_composite(base.convert('RGBA'),image.convert('RGBA')).convert('RGB')
                    from PIL import ImageChops,ImageStat
                    self.assertLessEqual(max(max(e) for e in ImageStat.Stat(ImageChops.difference(merged,effect)).extrema),1)
                with Image.open(io.BytesIO(z.read('mergedimage.png'))) as image:self.assertEqual(image.convert('RGB').tobytes(),effect.tobytes())


if __name__ == '__main__': unittest.main()
