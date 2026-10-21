import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from PIL import Image,ImageChops
from print_studio.core import atomic_json,save_png,sha256
from print_studio.fashion.models import catalog,local
from print_studio.fashion.library import TemplateLibrary,validate,approve
from print_studio.fashion.cli import demo
from print_studio.fashion.render import render,projective
from print_studio.fashion.batch import Queue,plan,records_from_folder,records_from_table
from print_studio.fashion.photoshop import prepare,verification
from print_studio.fashion.vision import polygon_mask,apply_suggestion,suggest


class FashionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.paths,self.pattern=demo(self.root/'fixture')
        self.lib=TemplateLibrary(self.paths[0].parent.parent)
        self.records=[{'sku':'YQ001','print':str(self.pattern)}]

    def tearDown(self):self.temp.cleanup()

    def assignments(self,path):return {r['id']:{'source_id':'same','params':{}} for r in validate(path).regions}

    def test_three_garments_have_distinct_masks_and_structures(self):
        structures=[];shapes=[]
        for p in self.paths:
            s=validate(p,True);structures.append([m['name'] for m in s.smart_objects])
            union=Image.new('L',(300,420))
            for r in s.regions:
                with Image.open(local(p.parent,r['mask'])) as mask:union=ImageChops.lighter(union,mask)
            shapes.append(union.tobytes())
            image=render(p,{'same':self.pattern},self.assignments(p))
            base=Image.open(local(p.parent,s.base))
            self.assertEqual(image.getpixel((150,100)),base.getpixel((150,100)))
            self.assertEqual(image.getpixel((0,0)),base.getpixel((0,0)))
            self.assertNotEqual(image.getpixel((120,120)),base.getpixel((120,120)))
        self.assertEqual([len(s) for s in structures],[5,5,3])
        self.assertNotEqual(structures[0],structures[1]);self.assertEqual(len(set(shapes)),3)

    def test_independent_assignment_shared_source_and_transform_isolation(self):
        p=self.paths[0];s=validate(p,True)
        red=self.root/'red.png';blue=self.root/'blue.png';save_png(Image.new('RGB',(8,8),'red'),red);save_png(Image.new('RGB',(8,8),'blue'),blue)
        assignments=self.assignments(p);sources={'same':red,'blue':blue}
        a=render(p,sources,assignments)
        assignments[s.regions[0]['id']]={'source_id':'blue','params':{'rotation':18,'quad':[[.05,.05],[.95,0],[1,.95],[0,1]]}}
        b=render(p,sources,assignments)
        self.assertEqual(a.getpixel((100,250)),b.getpixel((100,250)))
        self.assertEqual(a.getpixel((150,100)),b.getpixel((150,100)))
        self.assertNotEqual(a.getpixel((120,120)),b.getpixel((120,120)))

    def test_config_extension_does_not_change_engine(self):
        config=self.root/'extra.json';atomic_json(config,{'types':[{'id':'new_apron','category':'自定义','name':'围裙','parts':[{'id':'apron','name':'围裙','smart_object':'APRON_PRINT'}]}]})
        garment=catalog(config)['new_apron'];p=self.lib.create(self.root/'fixture/technical-model.png',garment,'新类型','m2','main')
        s=validate(p);save_png(Image.new('L',(300,420),255),local(p.parent,s.regions[0]['mask']));approve(p)
        self.assertEqual(render(p,{'same':self.pattern},self.assignments(p)).size,(300,420))

    def test_approval_invalidates_after_mask_edit(self):
        p=self.paths[0];s=validate(p,True)
        save_png(Image.new('L',(300,420)),local(p.parent,s.regions[0]['mask']))
        with self.assertRaises(ValueError):validate(p,True)
        with self.assertRaises(ValueError):approve(p)

    def test_each_model_starts_with_own_empty_masks(self):
        types=catalog(Path('print_studio/assets/fashion/garments.json'))
        p=self.lib.create(self.root/'fixture/technical-model.png',types['set_tee_shorts'],'新模特','different','side')
        self.assertFalse(Image.open(local(p.parent,validate(p).regions[0]['mask'])).getbbox())
        with self.assertRaises(ValueError):validate(p,True)

    def test_modes_counts_and_case_insensitive_name_conflicts(self):
        self.assertEqual(len(plan(self.records,self.paths,'D',naming='{garment}_{view}')),3)
        self.assertEqual(len(plan(self.records,[self.paths[0]],'A')),1)
        with self.assertRaises(ValueError):plan(self.records,self.paths,'A')
        with self.assertRaises(ValueError):plan(self.records,self.paths,'B')
        with self.assertRaises(ValueError):plan(self.records,self.paths,'D')
        clone=self.lib.duplicate(self.paths[0]);approve(clone)
        with self.assertRaises(ValueError):plan(self.records,[self.paths[0],clone],'B')
        self.assertEqual(len(plan(self.records,[self.paths[0],clone],'B',naming='{index}_{view}')),2)

    def test_batch_snapshots_pause_resume_and_completed_skip(self):
        q=Queue.create(self.records,self.paths,self.root/'jobs',naming='{garment}_{view}')
        q.emit=lambda item:q.pause_event.set()
        self.assertEqual(q.run(),'paused')
        self.assertEqual(sum(i['status']=='done' for i in q.state.items),1)
        target=q.root/q.state.items[0]['output'];mtime=target.stat().st_mtime_ns
        # Source modifications after planning do not alter the immutable job snapshots.
        self.pattern.unlink();q=Queue(q.path)
        self.assertEqual(q.run(),'done');self.assertEqual(target.stat().st_mtime_ns,mtime)
        q.run();self.assertEqual(target.stat().st_mtime_ns,mtime)
        self.assertEqual(len(json.loads((q.root/'temu-images.json').read_text())['images']),3)

    def test_failed_retry_does_not_repeat_completed_jobs(self):
        from print_studio.fashion import batch
        original=batch.render;calls=[]
        def fail(path,*a,**kw):
            calls.append(path)
            if len(calls)==2:raise ValueError('temporary renderer failure')
            return original(path,*a,**kw)
        q=Queue.create(self.records,self.paths,self.root/'jobs',naming='{garment}_{view}')
        with patch.object(batch,'render',side_effect=fail):self.assertEqual(q.run(),'failed')
        done=[q.root/i['output'] for i in q.state.items if i['status']=='done'];mtimes=[p.stat().st_mtime_ns for p in done]
        q.retry_failed();self.assertEqual(q.run(),'done');self.assertEqual(mtimes,[p.stat().st_mtime_ns for p in done])

    def test_cancel_and_corrupt_snapshot_detection(self):
        q=Queue.create(self.records,self.paths,self.root/'jobs',naming='{garment}_{view}')
        q.emit=lambda item:q.cancel_event.set();self.assertEqual(q.run(),'cancelled')
        saved=next(iter(q.state.hashes));(q.root/saved).write_bytes(b'bad')
        with self.assertRaises(ValueError):q.run()

    def test_existing_unknown_output_is_never_overwritten(self):
        q=Queue.create(self.records,[self.paths[0]],self.root/'jobs')
        dest=q.root/q.state.items[0]['output'];dest.parent.mkdir(parents=True);dest.write_bytes(b'keep me')
        self.assertEqual(q.run(),'failed');self.assertEqual(dest.read_bytes(),b'keep me')

    def test_library_export_import_duplicate_search_delete(self):
        z=self.root/'template.zip';self.lib.export(self.paths[0],z)
        p=self.lib.import_zip(z);self.assertNotEqual(validate(p).id,validate(self.paths[0]).id)
        with self.assertRaises(ValueError):validate(p,True)
        clone=self.lib.duplicate(p);self.assertTrue(self.lib.list('副本'));self.lib.delete(clone);self.assertFalse(clone.exists())
        self.assertTrue(list((self.lib.root/'.trash').iterdir()))

    def test_zip_and_paths_cannot_escape_library(self):
        for entry in ['../escape','/tmp/escape','C:/escape','folder\\escape']:
            with self.assertRaises(ValueError):local(self.lib.root,entry)
            z=self.root/'bad.zip'
            with ZipFile(z,'w') as archive:archive.writestr(entry,b'bad')
            with self.assertRaises(ValueError):self.lib.import_zip(z)
        self.assertFalse((self.root/'escape').exists())

    def test_csv_excel_and_folder_sku_import(self):
        folder=self.root/'sku';(folder/'YQ001').mkdir(parents=True)
        save_png(Image.new('RGB',(5,5),'red'),folder/'YQ001/print.png')
        self.assertEqual(records_from_folder(folder)[0]['sku'],'YQ001')
        csv=self.root/'names.csv';csv.write_text('货号,印花路径\nYQ002,sku/YQ001/print.png\n',encoding='utf-8-sig')
        self.assertTrue(Path(records_from_table(csv)[0]['print']).exists())
        from openpyxl import Workbook
        w=Workbook();w.active.append(['货号','印花路径']);w.active.append(['001','sku/YQ001/print.png']);w.save(self.root/'names.xlsx')
        self.assertEqual(records_from_table(self.root/'names.xlsx')[0]['sku'],'001')

    def test_perspective_identity_and_invalid_quad(self):
        image=Image.open(self.pattern).convert('RGB')
        self.assertFalse(ImageChops.difference(projective(image,[[0,0],[1,0],[1,1],[0,1]]),image).getbbox())
        with self.assertRaises(ValueError):projective(image,[[0,0],[1,1],[1,0],[0,1]])

    def test_photoshop_package_is_not_marked_verified(self):
        p=self.paths[0];script=prepare(p,{'same':self.pattern},self.assignments(p),self.root/'photoshop')
        manifest=json.loads((script.parent/'manifest.json').read_text())
        self.assertEqual(manifest['status'],'awaiting_photoshop')
        self.assertEqual(len(manifest['regions']),5)
        self.assertFalse((script.parent/'mockup.psd').exists())
        self.assertIn('newPlacedLayer',script.read_text());self.assertIn('placedLayerEditContents',script.read_text())
        with self.assertRaises(FileNotFoundError):verification(script.parent/'photoshop-report.json')

    def test_ai_polygon_drafts_not_cross_applied_and_no_auto_retry(self):
        m=polygon_mask((100,100),[[[.1,.1],[.8,.1],[.8,.8]]]);self.assertEqual(m.getpixel((40,20)),255)
        p=self.paths[0];s=validate(p)
        data={'garment_type':s.garment_type,'parts':[],'source_sha256':'other-photo'}
        with self.assertRaises(ValueError):apply_suggestion(p,data)
        types=catalog(Path('print_studio/assets/fashion/garments.json'))
        with patch('print_studio.fashion.vision.request',side_effect=TimeoutError) as req:
            with self.assertRaises(TimeoutError):suggest(local(p.parent,s.original),types,'https://example.com/v1/chat/completions','vision-id','test-key')
            self.assertEqual(req.call_count,1)


if __name__=='__main__':unittest.main()
