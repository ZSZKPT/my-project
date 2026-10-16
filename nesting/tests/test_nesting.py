import base64
import io
import json
import math
import sys
import threading
import time
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from geometry import prepare,validate,placed,polygon
from engine import solve
from assets import import_asset,data_url,safe_svg,raster_contour,FragmentedContour
from exporting import svg_document,production_zip
from examples.make_demo import create

def rect(pid,w=100,h=100,**kw):
    raw=io.BytesIO();Image.new('RGB',(10,10),'red').save(raw,'JPEG')
    return {'id':pid,'name':pid,'filename':pid+'.jpg','width':w,'height':h,'quantity':1,'contours':[[[0,0],[w,0],[w,h],[0,h]]],
        'source':data_url(raw.getvalue(),'image/jpeg'),'confirmed':True,'dimensionConfirmed':True,'allow180':True,'bleed':0,**kw}

def project(pieces,**settings):
    return {'version':1,'unit':'mm','pieces':pieces,'placements':[],'settings':{'width':1580,'left':10,'right':10,'gap':3,'seconds':10,'iterations':3,'seed':42,**settings}}

def pos(pid,x=10,y=0,angle=0,locked=False):return {'key':pid+'::0','pieceId':pid,'x':x,'y':y,'angle':angle,'locked':locked}

class GeometryTests(unittest.TestCase):
    def test_1580_edges_gap_and_adjustment(self):
        p=project([rect('a'),rect('b')]);p['placements']=[pos('a'),pos('b',113)]
        self.assertTrue(validate(p)['valid'])
        p['placements'][1]['x']=112.9;self.assertFalse(validate(p)['valid'])
        p['settings']['gap']=2.9;self.assertTrue(validate(p)['valid'])
        p['placements'][0]['x']=9.9;self.assertFalse(validate(p)['valid'])
    def test_no_other_angles_no_mirror_and_per_piece_flag(self):
        p=project([rect('a')]);p['placements']=[pos('a',angle=90)];self.assertFalse(validate(p)['valid'])
        p['placements'][0]['angle']=180;self.assertTrue(validate(p)['valid'])
        p['pieces'][0]['allow180']=False;self.assertFalse(validate(p)['valid'])
    def test_count_duplicate_missing(self):
        p=project([rect('a'),rect('b')]);p['placements']=[pos('a')];self.assertFalse(validate(p)['valid'])
        p['placements'].append(pos('a',113));self.assertFalse(validate(p)['valid'])
        p['pieces'][0]['quantity']=2
        with self.assertRaisesRegex(ValueError,'一文件一裁片'):prepare(p)
    def test_oversized_and_invalid_polygons(self):
        with self.assertRaisesRegex(ValueError,'超过有效门幅'):prepare(project([rect('a',1561)]))
        with self.assertRaises(ValueError):polygon([[[0,0],[100,100],[0,100],[100,0]]])
        with self.assertRaises(ValueError):prepare(project([rect('a')],gap=-1))
    def test_bleed_head_tail_and_interior_overlap(self):
        p=project([rect('a',bleed=2),rect('b',bleed=2)],head=5,tail=7)
        p['placements']=[pos('a',12,7),pos('b',119,7)]
        v=validate(p);self.assertTrue(v['valid']);self.assertAlmostEqual(v['stats']['length'],116)
        p['placements'][1]['x']=118.9;self.assertFalse(validate(p)['valid'])
        p['placements'][1]=pos('b',12,7);self.assertFalse(validate(p)['valid'])
    def test_concave_not_bounding_boxes(self):
        a=rect('a',100,100,contours=[[[0,0],[100,0],[100,30],[30,30],[30,100],[0,100]]])
        p=project([a,rect('b',60,60)]);p['placements']=[pos('a'),pos('b',43,33)]
        self.assertTrue(validate(p)['valid'])
    def test_rotation_source_coordinates(self):
        p=project([rect('a',100,80,contours=[[[10,5],[80,5],[10,60]]])]);s,c,inst=prepare(p)
        self.assertEqual(tuple(round(v,5) for v in placed(inst['a::0'],pos('a',0,0,180)).bounds),(20,20,90,75))

class ImportTests(unittest.TestCase):
    def fragmented(self):
        im=Image.new('RGB',(500,500),'white');d=ImageDraw.Draw(im)
        d.rectangle((10,10,160,160),fill='blue')
        for x in range(220,440,20):
            for y in range(220,440,20):d.point((x,y),fill='black')
        return im
    def test_fragmentation_reports_measured_denoise_threshold(self):
        im=self.fragmented()
        with self.assertRaises(FragmentedContour) as raised:raster_contour(im,'background',20,'#ffffff',0)
        info=raised.exception.details
        self.assertEqual(info['components'],122);self.assertEqual(info['suggestedMinArea'],2)
        self.assertEqual(info['keptComponents'],1)
        clean,_=raster_contour(im,'background',20,'#ffffff',info['suggestedMinArea'])
        self.assertAlmostEqual(clean.area,151*151)
    def test_explicit_hull_preserves_all_foreground_without_discard(self):
        im=self.fragmented();hull,_=raster_contour(im,'background-hull',20,'#ffffff',99999)
        from shapely.geometry import Point
        self.assertEqual(hull.geom_type,'Polygon')
        for x in range(220,440,20):
            for y in range(220,440,20):self.assertTrue(hull.covers(Point(x+.5,y+.5)))
        self.assertTrue(hull.covers(Point(10,10)))
    def encode(self,image,fmt,**kw):
        raw=io.BytesIO();image.save(raw,fmt,**kw);return data_url(raw.getvalue(),'image/jpeg' if fmt=='JPEG' else 'image/png')
    def test_jpg_background_and_missing_dpi(self):
        im=Image.new('RGB',(120,100),'white');ImageDraw.Draw(im).rectangle((10,10,109,89),fill='blue')
        asset=import_asset({'filename':'a.jpg','data':self.encode(im,'JPEG'),'mode':'background','threshold':30})
        self.assertFalse(asset['dimensionConfirmed']);self.assertFalse(asset['confirmed'])
        asset=import_asset({'filename':'a.jpg','data':self.encode(im,'JPEG'),'mode':'background','threshold':30,'width':240,'height':200})
        self.assertTrue(asset['dimensionConfirmed']);self.assertLess(polygon(asset['contours']).area,240*200)
    def test_png_holes_filled(self):
        im=Image.new('RGBA',(100,100),(0,0,0,0));d=ImageDraw.Draw(im);d.rectangle((10,10,89,89),fill='red');d.rectangle((30,30,69,69),fill=(0,0,0,0))
        asset=import_asset({'data':self.encode(im,'PNG'),'mode':'alpha','width':100,'height':100})
        self.assertAlmostEqual(polygon(asset['contours']).area,6400)
    def test_dpi_and_rectangle_explicit(self):
        im=Image.new('RGB',(300,600),'white');data=self.encode(im,'JPEG',dpi=(300,300))
        a=import_asset({'data':data,'mode':'rectangle'});self.assertAlmostEqual(a['width'],25.4);self.assertAlmostEqual(a['height'],50.8)
        self.assertTrue(a['dimensionConfirmed'])
    def test_svg_units_transforms_selection_curves(self):
        svg=b'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="200mm" viewBox="0 0 100 200"><g transform="translate(10 20)"><path id="cut" d="M0 0 L20 0 L20 30 Z"/></g></svg>'
        a=import_asset({'data':data_url(svg,'image/svg+xml'),'cutId':'cut'})
        self.assertEqual((a['width'],a['height']),(100,200));self.assertAlmostEqual(polygon(a['contours']).bounds[0],10,places=4)
        self.assertAlmostEqual(polygon(a['contours']).bounds[1],20,places=4)
        curve=b'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100"><path id="c" d="M10 10 Q90 10 90 90 L10 90 Z"/></svg>'
        a=import_asset({'data':data_url(curve,'image/svg+xml')});self.assertGreater(len(a['contours'][0]),10)
    def test_unsafe_svg_rejected(self):
        for content in [b'<svg><script>alert(1)</script></svg>',b'<svg><image href="https://evil.test/a.png"/></svg>',b'<!DOCTYPE svg><svg/>']:
            with self.assertRaises(ValueError):safe_svg(content)

class EngineExportTests(unittest.TestCase):
    def test_180_complementary_improves_real_length(self):
        p=create();p['pieces']=p['pieces'][:2];p['settings'].update(seconds=20,iterations=3)
        r=solve(p,threading.Event());self.assertTrue(r['valid']);self.assertLess(r['stats']['length'],r['comparison'][0]['length']*.7)
        self.assertIn(180,[q['angle'] for q in r['placements']]);self.assertEqual(len(r['placements']),2)
    def test_seed_reproducible_and_stopping_preserves_baseline(self):
        p=project([rect('a',200,150),rect('b',400,110),rect('c',230,200)],iterations=5)
        a=solve(p,threading.Event());b=solve(p,threading.Event());self.assertFalse(a['timedOut']);self.assertEqual(a['placements'],b['placements'])
        stop=threading.Event();stop.set();c=solve(p,stop);self.assertTrue(c['valid']);self.assertTrue(c['stopped'])
    def test_locks_are_preserved_and_conflicts_rejected(self):
        p=project([rect('a'),rect('b')]);p['placements']=[pos('a',200,300,180,True)]
        r=solve(p,threading.Event());self.assertIn(p['placements'][0],r['placements']);self.assertTrue(r['valid'])
        p['placements'].append(pos('b',200,300,0,True))
        with self.assertRaisesRegex(ValueError,'锁定裁片冲突'):solve(p,threading.Event())
    def test_export_mm_rotation_original_bytes_segments_and_roundtrip(self):
        p=project([rect('a',100,100)]);p['placements']=[pos('a',10,0,180)]
        svg=svg_document(p);root=ET.fromstring(svg)
        self.assertEqual(root.get('width'),'1580.000000000mm');self.assertIn('rotate(180)',svg)
        self.assertIn(p['pieces'][0]['source'],svg)
        archive=production_zip(p,100)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            restored=json.loads(z.read('project.nest.json'));self.assertTrue(validate(restored)['valid'])
            manifest=json.loads(z.read('manifest.json'));self.assertEqual(manifest['segments'][0]['endMm'],100)
            self.assertEqual(manifest['segments'][0]['overlapMm'],0)
        p['placements'][0]['angle']=90
        with self.assertRaisesRegex(ValueError,'导出被阻止'):svg_document(p)
    def test_many_files_and_memory_budget(self):
        import tracemalloc
        p=project([rect(f'f{i}',30+(i%7),40+(i%5)) for i in range(100)],seconds=1,iterations=1)
        tracemalloc.start();started=time.monotonic();r=solve(p,threading.Event());_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        self.assertTrue(r['valid']);self.assertEqual(len(r['placements']),100)
        self.assertLess(time.monotonic()-started,8);self.assertLess(peak,128*1024*1024)
        print(f'\n100文件测试：{time.monotonic()-started:.3f}s，Python峰值分配{peak/1024/1024:.2f}MiB（不含GEOS原生内存）')
    def test_long_piece_segments_are_contiguous(self):
        p=project([rect('a',100,250)]);p['placements']=[pos('a',10,0,180)]
        with zipfile.ZipFile(io.BytesIO(production_zip(p,100))) as z:
            m=json.loads(z.read('manifest.json'));segments=m['segments']
            self.assertEqual([(s['startMm'],s['endMm']) for s in segments],[(0,100),(100,200),(200,250)])
            for seg in segments:
                root=ET.fromstring(z.read(seg['file']))
                self.assertEqual(float(root.get('viewBox').split()[1]),seg['startMm'])
                self.assertEqual(float(root.get('height').removesuffix('mm')),seg['lengthMm'])
                self.assertIn('rotate(180)',z.read(seg['file']).decode())

if __name__=='__main__':unittest.main(verbosity=2)
