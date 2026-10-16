import threading
import unittest
from test_compaction import piece,task
from geometry import validate
from engine import solve


def fixture():
    parts=[piece('large',0,0,600,400)]
    for i in range(4):
        common={'sourceGroup':f'g{i}','verticalOnly':True,'fixedPair':True,'sourcePartCount':2}
        parts.extend([piece(f'l{i}',0,0,140,50,sourcePart='left',**common),
                      piece(f'r{i}',160,0,140,50,sourcePart='right',**common)])
    return task(parts,seconds=8)


class RigidPairsTests(unittest.TestCase):
    def test_whole_group_backfill_shortens_strip_and_keeps_relative_position(self):
        raw=fixture();reports=[];answer=solve(raw,threading.Event(),reports.append)
        self.assertTrue(answer['valid'])
        self.assertGreater(answer['comparison'][0]['length'],450)
        self.assertLessEqual(answer['stats']['length'],400.01)
        for report in reports:
            self.assertTrue(validate({**raw,'placements':report['placements']})['valid'])
            for i in range(4):
                group=[p for p in report['placements'] if p['pieceId'] in (f'l{i}',f'r{i}')]
                self.assertEqual((group[0]['x'],group[0]['y'],group[0]['angle']),
                                 (group[1]['x'],group[1]['y'],group[1]['angle']))
        print(f"固定整组样本：顺序 {answer['comparison'][0]['length']:.2f} mm → 优化 {answer['stats']['length']:.2f} mm，{answer['seconds']:.2f}s（合成样本）")

    def test_single_panel_move_blocked_and_locked_group_preserved(self):
        raw=fixture();answer=solve(raw,threading.Event());raw['placements']=answer['placements']
        left=next(p for p in raw['placements'] if p['pieceId']=='l0')
        left['y']+=10;self.assertFalse(validate(raw)['valid']);left['y']-=10
        left['locked']=True;saved=left.copy()
        again=solve(raw,threading.Event());self.assertTrue(again['valid']);self.assertIn(saved,again['placements'])
        right=next(p for p in again['placements'] if p['pieceId']=='r0')
        self.assertEqual((right['x'],right['y'],right['angle']),(saved['x'],saved['y'],saved['angle']))

    def test_group_order_is_free_and_seed_reproducible(self):
        raw=fixture();a=solve(raw,threading.Event());b=solve(raw,threading.Event())
        self.assertEqual(a['placements'],b['placements'])
        raw['pieces'].reverse();c=solve(raw,threading.Event())
        self.assertAlmostEqual(a['stats']['length'],c['stats']['length'],places=2)

if __name__=='__main__':unittest.main()
