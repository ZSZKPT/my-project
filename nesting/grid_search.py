"""Conservative raster search for complete whole-piece layouts.

Grid cells cover occupied polygons expanded by half the gap. FFT correlation
checks ALL grid translations, instead of a sampled list of polygon vertices.
Only the independent millimetre polygon validator may accept a final result.
No artwork or production dimensions are rasterized/resampled by this search.
"""
import math
import random
import time
from collections import OrderedDict
import numpy as np
from shapely import affinity
from shapely.geometry import box
from geometry import oriented,placed,EPS


class SearchStopped(Exception):pass


def cover_mask(g,cell,origin=None,check=lambda:None):
    a,b,c,d=g.bounds
    ox,oy=origin if origin is not None else (a,b)
    col=math.floor((a-ox)/cell+1e-10);row=math.floor((b-oy)/cell+1e-10)
    width=max(1,math.ceil((c-ox)/cell-1e-10)-col)
    height=max(1,math.ceil((d-oy)/cell-1e-10)-row)
    mask=np.zeros((height,width),dtype=np.uint8)
    # Each intersected cell is occupied, including concave and disjoint parts.
    def fill(part,r):
        if part.is_empty:return
        if hasattr(part,'geoms'):
            for child in part.geoms:fill(child,r)
        else:
            x0,_,x1,_=part.bounds
            left=max(0,math.floor((x0-ox)/cell+1e-10)-col)
            right=min(width,math.ceil((x1-ox)/cell-1e-10)-col)
            if right>left:mask[r,left:right]=1
    for r in range(height):
        check()
        y=oy+(row+r)*cell
        fill(g.intersection(box(a-cell,y,c+cell,y+cell)),r)
    return mask,col,row


def search(order,instances,s,locks,current,deadline,stop,accept,rounds=None):
    if not order or any(p.get('verticalOnly') for p in instances.values()):return 0
    # Keep grid/FFT memory bounded even for unusually wide/high inputs.
    cell=max(5.0,(s['width']-s['left']-s['right'])/320,
             max(instances[k]['height'] for k in order)/300)
    padding=(s['gap']/2+EPS)/math.cos(math.pi/32)
    origin=(s['left']-padding,s['head']-padding)
    width=math.floor((s['width']-s['left']-s['right']+2*padding)/cell)
    rng=random.Random(s['seed']);cache={};fixed_cache={};fft_cache=OrderedDict();cache_bytes=0
    def check():
        if stop.is_set() or time.monotonic()>=deadline:raise SearchStopped()
    def shape(key,angle):
        ident=(key,angle)
        if ident not in cache:
            check();original=oriented(instances[key],angle);g=original.buffer(padding,quad_segs=8)
            a,b,_,_=original.bounds;local_origin=(a-padding,b-padding)
            mask,_,_=cover_mask(g,cell,local_origin,check)
            cache[ident]=(mask,local_origin)
        return cache[ident]
    def place_sequence(sequence,fixed,right_first=False,explore=False):
        nonlocal cache_bytes
        check();board=np.zeros((1,width),dtype=np.uint8);top=0;layout=[p.copy() for p in fixed]
        def add(mask,x,y):
            nonlocal board,top
            h,w=mask.shape
            if y<0 or x<0 or x+w>width:raise SearchStopped()
            if y+h>board.shape[0]:board=np.pad(board,((0,y+h-board.shape[0]),(0,0)))
            board[y:y+h,x:x+w]|=mask;top=max(top,y+h)
        for p in fixed:
            check();ident=(p['key'],p['angle'],p['x'],p['y'])
            if ident not in fixed_cache:
                mask,local_origin=shape(p['key'],p['angle'])
                col=(p['x']+local_origin[0]-origin[0])/cell
                row=(p['y']+local_origin[1]-origin[1])/cell
                if abs(col-round(col))<1e-8 and abs(row-round(row))<1e-8:
                    x,y=round(col),round(row)
                else:
                    g=placed(instances[p['key']],p).buffer(padding,quad_segs=8)
                    mask,x,y=cover_mask(g,cell,origin,check)
                fixed_cache[ident]=(mask,x,y)
                if len(fixed_cache)>500:fixed_cache.pop(next(iter(fixed_cache)))
            mask,x,y=fixed_cache[ident]
            # Valid exact locks may extend into the last partial grid cell.
            if x<0:mask=mask[:,-x:];x=0
            if y<0:mask=mask[-y:];y=0
            mask=mask[:,:max(0,width-x)]
            if mask.size:add(mask,x,y)
        for key in sequence:
            check();part=instances[key];angles=[0,180] if part.get('allow180',True) else [0]
            shapes=[(angle,*shape(key,angle)) for angle in angles]
            shapes=[v for v in shapes if v[1].shape[1]<=width]
            if not shapes:return None
            max_h=max(v[1].shape[0] for v in shapes);max_w=max(v[1].shape[1] for v in shapes)
            fh=1<<max(1,(top+2*max_h).bit_length());fw=1<<max(1,(width+max_w).bit_length())
            # Avoid an unbounded FFT for jobs outside this accelerator's range.
            if fh*fw>4_194_304:return None
            board_fft=np.fft.rfft2(board[:max(1,top)],s=(fh,fw));best=None;options=[]
            for angle,mask,bounds in shapes:
                check();h,w=mask.shape;ident=(key,angle,fh,fw)
                spectrum=fft_cache.get(ident)
                if spectrum is None:
                    spectrum=np.fft.rfft2(mask[::-1,::-1],s=(fh,fw))
                    while fft_cache and cache_bytes+spectrum.nbytes>48*1024*1024:
                        _,removed=fft_cache.popitem(last=False);cache_bytes-=removed.nbytes
                    if spectrum.nbytes<=48*1024*1024:
                        fft_cache[ident]=spectrum;cache_bytes+=spectrum.nbytes
                else:fft_cache.move_to_end(ident)
                overlap=np.fft.irfft2(board_fft*spectrum,s=(fh,fw))
                possible=overlap[h-1:h+top,w-1:width]<.5
                if right_first:possible=possible[:,::-1]
                indices=np.flatnonzero(possible)
                if not len(indices):continue
                y,x=divmod(int(indices[0]),possible.shape[1])
                if right_first:x=width-w-x
                score=(max(top,y+h),y,-x if right_first else x,angle)
                option=(score,angle,mask,bounds,x,y);options.append(option)
                if best is None or score<best[0]:best=option
            if best is None:return None
            if explore and len(options)>1 and rng.random()<.25:
                close=[v for v in options if v[0][0]<=best[0][0]+3]
                best=rng.choice(close)
            _,angle,mask,bounds,x,y=best;add(mask,x,y)
            layout.append({'key':key,'pieceId':part['id'],'x':origin[0]+x*cell-bounds[0],
                           'y':origin[1]+y*cell-bounds[1],'angle':angle,'locked':False})
        return layout
    rounds=rounds if rounds is not None else min(200,max(8,s['iterations']*3))
    best=[p.copy() for p in current];completed=0
    try:
        # Alternating full restarts and several-group removal allows pieces to
        # exchange places, escaping the old single-piece compaction trap.
        for iteration in range(rounds):
            check();fixed=locks
            if iteration>=4 and iteration%2:
                movable=[p for p in best if not p.get('locked')]
                if not movable:break
                count=min(len(movable),3+iteration%5)
                tail=sorted(movable,key=lambda p:placed(instances[p['key']],p).bounds[3],reverse=True)
                selected={p['key'] for p in tail[:max(1,count//2)]}
                candidates=[p['key'] for p in movable if p['key'] not in selected]
                selected.update(rng.sample(candidates,min(count-len(selected),len(candidates))))
                sequence=[k for k in order if k in selected];rng.shuffle(sequence)
                fixed=[p for p in best if p['key'] not in selected]
            else:
                sequence=order[:]
                if iteration==0:sequence.sort(key=lambda k:-instances[k]['occupied'].area)
                elif iteration==1:sequence.sort(key=lambda k:-(instances[k]['occupied'].bounds[3]-instances[k]['occupied'].bounds[1]))
                elif iteration==2:sequence.sort(key=lambda k:-(instances[k]['occupied'].bounds[2]-instances[k]['occupied'].bounds[0]))
                elif iteration%8==0:rng.shuffle(sequence)
                else:
                    positions={p['key']:p for p in best}
                    sequence.sort(key=lambda k:(positions[k]['y'],positions[k]['x']))
                    for _ in range(2+iteration%4):
                        if len(sequence)>1:
                            i,j=rng.sample(range(len(sequence)),2)
                            sequence.insert(j,sequence.pop(i))
            candidate=place_sequence(sequence,fixed,right_first=iteration%4==3,explore=iteration>=3)
            if candidate is not None:
                if accept(candidate,'多组换位与全域空隙搜索'):best=[p.copy() for p in candidate]
                completed+=1
    except SearchStopped:pass
    return completed
