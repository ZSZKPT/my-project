"""Feasible shelf baseline + polygon-contact, multi-start strip nesting."""
import random
import time
from shapely import affinity
from shapely.strtree import STRtree
from geometry import prepare, validate, oriented, placed, conflicts, EPS

class Interrupted(Exception):pass

def vertices(g,limit=24):
    polys=[g] if g.geom_type=='Polygon' else g.geoms
    points=[p for poly in polys for p in list(poly.exterior.coords)[:-1]]
    if len(points)>limit:
        points=points[::max(1,len(points)//limit)][:limit]+[(g.bounds[0],g.bounds[1]),(g.bounds[2],g.bounds[3])]
    return points

def baseline(order,instances,s,locks):
    result=list(locks)
    y=max([placed(instances[p['key']],p).bounds[3]+s['gap'] for p in locks],default=s['head'])
    x=s['left']; rowheight=0
    for key in order:
        g=instances[key]['occupied'];a,b,c,d=g.bounds;w=c-a;h=d-b
        if x+w>s['width']-s['right']+EPS:
            x=s['left'];y+=rowheight+s['gap'];rowheight=0
        result.append({'key':key,'pieceId':instances[key]['id'],'x':x-a,'y':y-b,'angle':0,'locked':False})
        x+=w+s['gap'];rowheight=max(rowheight,h)
    return result

def pack(order,instances,s,locks,deadline,stop,orientation_cache=None):
    if orientation_cache is None:orientation_cache={}
    result=list(locks); geoms=[placed(instances[p['key']],p) for p in result]
    for key in order:
        if time.monotonic()>deadline or stop.is_set():raise Interrupted()
        part=instances[key];best=None
        tree=STRtree(geoms)
        obstacle_points=[v for g in geoms for v in vertices(g,12)]
        if len(obstacle_points)>200:obstacle_points=obstacle_points[::max(1,len(obstacle_points)//200)][:200]
        top=max([g.bounds[3] for g in geoms],default=s['head'])
        for angle in ([0,180] if part.get('allow180',True) else [0]):
            cache_key=(key,angle)
            if cache_key not in orientation_cache:
                g=oriented(part,angle);orientation_cache[cache_key]=(g,g.bounds,vertices(g,12))
            g,(a,b,c,d),points=orientation_cache[cache_key]
            xs={s['left']-a,s['width']-s['right']-c}
            ys={s['head']-b,top+s['gap']-b}
            for v in obstacle_points:
                for q in points:
                    xs.update((v[0]-q[0]-s['gap'],v[0]-q[0]+s['gap']))
                    ys.update((v[1]-q[1]-s['gap'],v[1]-q[1]+s['gap']))
            # Regular horizontal candidates improve placements between vertex contacts.
            for i in range(25):xs.add(s['left']-a+(s['width']-s['right']-s['left']-(c-a))*i/24)
            xs=sorted(x for x in xs if x+a>=s['left']-EPS and x+c<=s['width']-s['right']+EPS)
            ys=sorted(y for y in ys if y+b>=s['head']-EPS)
            # Bound candidate search; shelf fallback always remains available.
            if len(xs)>100:xs=sorted(set(xs[::max(1,len(xs)//90)]+xs[:6]+xs[-6:]))
            if len(ys)>140:ys=sorted(set(ys[::max(1,len(ys)//130)]+ys[:8]))
            for y in ys:
                if best and y+d>best[0]+EPS:continue
                for x in xs:
                    if time.monotonic()>deadline or stop.is_set():raise Interrupted()
                    moved=affinity.translate(g,x,y)
                    if any(conflicts(moved,geoms[int(j)],s['gap']) for j in tree.query(moved.buffer(s['gap']+EPS))):continue
                    score=(max(top,y+d),y+b,x+a,angle)
                    if best is None or score<best[0:4]:best=(*score,x,y,angle,moved)
                    break
        if best is None:raise ValueError('未找到可行位置')
        result.append({'key':key,'pieceId':part['id'],'x':best[4],'y':best[5],'angle':best[6],'locked':False})
        geoms.append(best[7])
    return result

def solve(raw,stop,progress=lambda value:None):
    started=time.monotonic();s,catalog,instances=prepare(raw)
    locks=[p for p in raw.get('placements',[]) if p.get('locked')]
    check=validate({**raw,'placements':locks},partial=True)
    if not check['valid']:raise ValueError('锁定裁片冲突：'+check['errors'][0]['message'])
    locks=check['placements'];locked={p['key'] for p in locks}
    order=[k for k in instances if k not in locked]
    base=baseline(order,instances,s,locks)
    best=validate({**raw,'placements':base})
    if not best['valid']:raise ValueError('初始方案复核失败')
    comparison=[{'label':'外接矩形顺序排料','length':best['stats']['length'],'effectiveUtilization':best['stats']['effectiveUtilization'],'seconds':time.monotonic()-started}]
    report={**best,'comparison':comparison.copy(),'iterations':0,'seconds':time.monotonic()-started,'timedOut':False,'stopped':False}
    progress(report)
    rng=random.Random(s['seed']);deadline=started+s['seconds'];best_order=order[:];orientation_cache={}
    for iteration in range(s['iterations']):
        if stop.is_set() or time.monotonic()>deadline:break
        if iteration==0:trial=sorted(order,key=lambda k:-instances[k]['geom'].area)
        elif iteration==1:trial=sorted(order,key=lambda k:-(instances[k]['occupied'].bounds[3]-instances[k]['occupied'].bounds[1]))
        elif iteration==2:trial=sorted(order,key=lambda k:-(instances[k]['occupied'].bounds[2]-instances[k]['occupied'].bounds[0]))
        else:
            trial=best_order[:]
            if len(trial)>1:
                if iteration%3==0:rng.shuffle(trial)
                else:
                    i,j=rng.sample(range(len(trial)),2);trial[i],trial[j]=trial[j],trial[i]
        try: candidate=pack(trial,instances,s,locks,deadline,stop,orientation_cache)
        except Interrupted:break
        result=validate({**raw,'placements':candidate})
        if not result['valid']:raise ValueError('候选方案独立复核失败')
        if iteration==0:comparison.append({'label':'真实轮廓初始方案','length':result['stats']['length'],'effectiveUtilization':result['stats']['effectiveUtilization'],'seconds':time.monotonic()-started})
        if result['stats']['length']<best['stats']['length']-EPS:best=result;best_order=trial[:]
        report={**best,'comparison':comparison.copy(),'iterations':iteration+1,'seconds':time.monotonic()-started,'timedOut':False,'stopped':False}
        progress(report)
    report.update(seconds=time.monotonic()-started,timedOut=time.monotonic()>=deadline,stopped=stop.is_set())
    report['comparison']=comparison+[{'label':'当前找到的最佳方案','length':best['stats']['length'],'effectiveUtilization':best['stats']['effectiveUtilization'],'seconds':report['seconds']}]
    progress(report)
    return report
