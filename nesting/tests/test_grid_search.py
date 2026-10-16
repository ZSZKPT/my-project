import copy
import threading
import time
import unittest
import numpy as np
from shapely.geometry import Polygon,box
from geometry import prepare,validate
from grid_search import cover_mask,search
from test_compaction import piece,task


class GridSearchTests(unittest.TestCase):
    def test_cell_cover_keeps_concave_void_and_disconnected_regions(self):
        g=Polygon([(0,0),(30,0),(30,10),(10,10),(10,30),(0,30)]).union(box(40,0,50,10))
        mask,x,y=cover_mask(g,5,origin=(0,0))
        self.assertEqual((x,y),(0,0));self.assertEqual(mask[4,4],0)
        self.assertEqual(mask[0,9],1);self.assertEqual(mask[4,1],1)
        for row,col in np.ndindex(mask.shape):
            cell=box(col*5,row*5,(col+1)*5,(row+1)*5)
            if g.intersection(cell).area>1e-8:self.assertEqual(mask[row,col],1)

    def test_search_rearranges_complete_layout_with_gap_and_exact_locked_position(self):
        raw=task([piece(str(i),0,0,200,200) for i in range(6)])
        raw['placements']=[{'key':f'{i}::0','pieceId':str(i),'x':10,'y':203*i,'angle':0,'locked':i==0} for i in range(6)]
        s,_,instances=prepare(raw);current=raw['placements'];snapshot=copy.deepcopy(raw);saved=current[0].copy();best=[current]
        def accept(candidate,phase):
            checked=validate({**raw,'placements':candidate})
            self.assertTrue(checked['valid'],checked['errors'])
            old=validate({**raw,'placements':best[0]})
            if checked['stats']['length']<old['stats']['length']:
                best[0]=candidate;return True
            return False
        completed=search([f'{i}::0' for i in range(1,6)],instances,s,[saved],current,time.monotonic()+10,threading.Event(),accept,rounds=8)
        self.assertGreater(completed,0);self.assertIn(saved,best[0]);self.assertEqual(len(best[0]),6)
        self.assertLessEqual(validate({**raw,'placements':best[0]})['stats']['length'],410)
        self.assertEqual(raw,snapshot)

    def test_stop_preserves_input_and_skips_incomplete_layout(self):
        raw=task([piece('a',0,0,200,200)]);s,_,instances=prepare(raw)
        stopped=threading.Event();stopped.set();accepted=[]
        self.assertEqual(search(list(instances),instances,s,[],[],time.monotonic()+10,stopped,lambda *args:accepted.append(args)),0)
        self.assertEqual(accepted,[])

if __name__=='__main__':unittest.main()
