import base64
import io
from pathlib import Path
import sys
import threading
import unittest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import solve,baseline
from geometry import prepare,validate


def piece(pid,x0,y0,w,h,frame=(1000,1000),**extra):
    image=io.BytesIO();Image.new('RGB',(20,20),'black').save(image,'JPEG')
    return {'id':pid,'name':pid,'filename':pid+'.jpg','quantity':1,'width':frame[0],'height':frame[1],
        'source':'data:image/jpeg;base64,'+base64.b64encode(image.getvalue()).decode(),
        'contours':[[[x0,y0],[x0+w,y0],[x0+w,y0+h],[x0,y0+h]]],
        'confirmed':True,'dimensionConfirmed':True,'allow180':False,'bleed':0,**extra}


def task(parts,width=1000,seconds=5):
    return {'version':1,'unit':'mm','pieces':parts,'placements':[],
        'settings':{'width':width,'left':10,'right':10,'gap':3,'seconds':seconds,'iterations':1,'seed':42}}


class CompactionTests(unittest.TestCase):
    def test_pair_large_original_vertical_void_is_removed(self):
        common={'sourceGroup':'g','verticalOnly':True,'sourcePartCount':2}
        a=piece('a',0,0,100,100,sourcePart='left',**common)
        b=piece('b',200,500,150,200,sourcePart='right',**common)
        raw=task([a,b]);reports=[];result=solve(raw,threading.Event(),lambda r:reports.append(r))
        self.assertTrue(result['valid']);self.assertLess(result['stats']['length'],201)
        self.assertAlmostEqual(result['comparison'][0]['length'],700)
        self.assertGreater(result['acceptedMoves'],0)
        p,q=result['placements'];self.assertEqual(p['x'],q['x']);self.assertEqual(p['angle'],q['angle'])
        for r in reports:self.assertTrue(validate({**raw,'placements':r['placements']})['valid'])

    def test_tail_small_panels_reinsert_above_last_row(self):
        raw=task([piece('big',0,0,600,400)]+[piece(f's{i}',0,0,300,50) for i in range(4)])
        result=solve(raw,threading.Event())
        self.assertTrue(result['valid'])
        self.assertGreater(result['comparison'][0]['length'],450)
        self.assertLessEqual(result['stats']['length'],400.01)

    def test_stop_after_first_improvement_keeps_complete_better_plan(self):
        common={'sourceGroup':'g','verticalOnly':True,'sourcePartCount':2}
        raw=task([piece('a',0,0,100,100,sourcePart='left',**common),piece('b',200,500,150,200,sourcePart='right',**common)])
        event=threading.Event()
        def stop_on_improvement(report):
            if report.get('acceptedMoves',0):event.set()
        result=solve(raw,event,stop_on_improvement)
        self.assertTrue(result['valid']);self.assertTrue(result['stopped'])
        self.assertLess(result['stats']['length'],result['comparison'][0]['length'])
        self.assertEqual(len(result['placements']),2)

    def test_previously_valid_better_plan_is_preserved_when_stopped(self):
        raw=task([piece('a',0,0,600,400)]+[piece(f's{i}',0,0,300,50) for i in range(4)])
        first=solve(raw,threading.Event());raw['placements']=first['placements']
        event=threading.Event();event.set();second=solve(raw,event)
        self.assertTrue(second['valid']);self.assertTrue(second['warmStarted'])
        self.assertLessEqual(second['stats']['length'],first['stats']['length'])

    def test_small_first_import_does_not_constrain_larger_panels(self):
        parts=[piece('small',0,0,200,40),piece('large',0,0,650,400),piece('medium',0,0,300,200)]
        raw=task(parts);result=solve(raw,threading.Event())
        other=task(list(reversed(parts)));again=solve(other,threading.Event())
        self.assertTrue(result['valid']);self.assertTrue(again['valid'])
        self.assertLessEqual(result['stats']['length'],result['comparison'][0]['length'])
        self.assertLessEqual(again['stats']['length'],again['comparison'][0]['length'])
        self.assertAlmostEqual(result['stats']['length'],again['stats']['length'],places=2)


if __name__=='__main__':unittest.main()
