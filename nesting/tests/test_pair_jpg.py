import base64
import io
import json
from pathlib import Path
import sys
import threading
import unittest
import zipfile
from unittest.mock import patch
from PIL import Image,ImageDraw
from shapely.geometry import Point
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from assets import import_asset,data_url
from geometry import prepare,validate,polygon
from engine import solve
from exporting import production_jpg,jpg_zip


def pair_fixture():
    im=Image.new('RGB',(880,700),'white');d=ImageDraw.Draw(im)
    # Closed outer bodies, a connected QR stand, and a connected size tab.
    d.polygon([(15,220),(260,220),(260,300),(210,360),(210,480),(275,500),(275,680),(10,680),(10,500),(75,480),(75,360),(15,300)],fill='#142a78')
    d.rectangle((90,20,175,105),outline='black',width=7);d.rectangle((120,100,145,225),fill='black')
    d.rectangle((105,35,125,55),fill='black');d.rectangle((140,65,160,85),fill='black')
    d.rectangle((270,580,325,590),fill='black');d.rectangle((320,560,365,610),outline='black',width=4)
    d.text((330,575),'XS',fill='red')
    d.polygon([(420,10),(480,10),(480,110),(770,110),(770,10),(860,10),(860,290),(810,330),(810,420),(870,450),(870,620),(800,685),(440,685),(400,620),(400,450),(450,420),(450,330),(420,290)],fill='#b51c25')
    out=io.BytesIO();im.save(out,'JPEG',quality=100,subsampling=0)
    return out.getvalue()


def paired_project():
    parts=import_asset({'filename':'synthetic-XS.jpg','data':data_url(pair_fixture(),'image/jpeg'),'mode':'garment-pair'})['splitPieces']
    return {'version':1,'unit':'mm','pieces':parts,'placements':[],
        'settings':{'width':1580,'left':10,'right':10,'gap':3,'head':0,'tail':0,'seconds':5,'iterations':2}}


class PairJpgTests(unittest.TestCase):
    def test_auto_pair_110dpi_keeps_qr_tab_and_neck_concavity(self):
        raw=paired_project();a,b=raw['pieces'];scale=25.4/110
        self.assertTrue(a['confirmed']);self.assertTrue(b['confirmed'])
        self.assertAlmostEqual(a['width'],880*scale);self.assertEqual(a['dpi'],[110,110])
        self.assertEqual(a['sourceGroup'],b['sourceGroup'])
        left=polygon(a['contours']);right=polygon(b['contours'])
        for x,y in [(110,40),(125,150),(325,565),(330,580)]:self.assertTrue(left.covers(Point(x*scale,y*scale)))
        self.assertFalse(right.covers(Point(600*scale,50*scale)))
        self.assertFalse(left.covers(Point(30*scale,420*scale)))
    def test_group_vertical_only_and_complete_membership(self):
        raw=paired_project();report=solve(raw,threading.Event());self.assertTrue(report['valid']);raw['placements']=report['placements']
        a,b=raw['placements'];self.assertAlmostEqual(a['x'],b['x']);self.assertEqual(a['angle'],b['angle'])
        self.assertAlmostEqual(a['y'],b['y'])
        b['y']+=500;self.assertFalse(validate(raw)['valid']);b['y']-=500
        b['x']+=1;self.assertFalse(validate(raw)['valid']);b['x']-=1
        b['angle']=180-a['angle'];self.assertFalse(validate(raw)['valid'])
        raw['pieces']=raw['pieces'][:1]
        with self.assertRaisesRegex(ValueError,'两片必须同时保留'):prepare(raw)
    def test_locked_sibling_keeps_group_x_and_angle(self):
        raw=paired_project();r=solve(raw,threading.Event());raw['placements']=r['placements'];raw['placements'][0]['locked']=True
        saved=raw['placements'][0].copy();r=solve(raw,threading.Event())
        self.assertTrue(r['valid']);self.assertIn(saved,r['placements'])
        self.assertTrue(all(p['x']==saved['x'] and p['angle']==saved['angle'] for p in r['placements']))
    def test_jpg_110dpi_white_background_and_preserved_source_marks(self):
        raw=paired_project();raw['placements']=solve(raw,threading.Event())['placements']
        jpeg=production_jpg(raw);im=Image.open(io.BytesIO(jpeg))
        self.assertEqual(im.format,'JPEG');self.assertEqual(im.info['dpi'],(110,110))
        self.assertEqual(im.width,round(1580/25.4*110));self.assertGreater(min(im.getpixel((0,0))),245)
        left=next(p for p in raw['placements'] if p['pieceId'].endswith('-left'))
        source_x,source_y=(110,40) if left['angle']==0 else (880-110,700-40)
        x=round(left['x']*110/25.4)+source_x;y=round(left['y']*110/25.4)+source_y
        self.assertLess(max(im.getpixel((x,y))),70)  # QR black cell survives mask and rotation.
        with zipfile.ZipFile(io.BytesIO(jpg_zip(raw,100))) as z:
            m=json.loads(z.read('manifest.json'));self.assertTrue(all(s['dpi']==110 for s in m['segments']))
            for a,b in zip(m['segments'],m['segments'][1:]):self.assertEqual(a['endPixel'],b['startPixel'])
    def test_long_single_jpg_uses_disk_backed_strips(self):
        raw=paired_project();raw['settings']['width']=300
        raw['placements']=solve(raw,threading.Event())['placements'];raw['settings']['tail']=6500
        # >24M pixels forces RGBX mmap strips, still one JPEG and 110 DPI.
        data=production_jpg(raw);im=Image.open(io.BytesIO(data))
        self.assertEqual(im.info['dpi'],(110,110));self.assertGreater(im.width*im.height,24_000_000)
        self.assertGreater(im.height,27000)


if __name__=='__main__':unittest.main()
