"""Feasible shelf baseline + polygon-contact, multi-start strip nesting."""
import random
import time
from shapely import affinity
from shapely.strtree import STRtree
from shapely.ops import unary_union
from geometry import prepare, validate, oriented, placed, conflicts, EPS

class Interrupted(Exception):pass

def grouped_order(order,instances):
    units={}
    for key in order:
        item=instances[key];gid=('group',item.get('sourceGroup')) if item.get('verticalOnly') else ('single',key)
        units.setdefault(gid,[]).append(key)
    return list(units.values())

def geometry_orders(order,instances):
    """No import-order constraint. Sort whole source groups by geometry first."""
    units=grouped_order(order,instances)
    def metrics(unit):
        shapes=[instances[k]['occupied'] for k in unit]
        bounds=unary_union(shapes).bounds
        return sum(g.area for g in shapes),bounds[2]-bounds[0],bounds[3]-bounds[1]
    data={tuple(unit):metrics(unit) for unit in units}
    def identity(unit):return tuple(sorted((instances[k].get('filename',''),k) for k in unit))
    orders=[]
    for criterion in range(3):
        chosen=sorted(units,key=lambda unit:(-data[tuple(unit)][criterion],-data[tuple(unit)][0],identity(unit)))
        orders.append([key for unit in chosen for key in sorted(unit,key=lambda k:(-instances[k]['geom'].area,k))])
    return orders

def clear_at(g,tree,geoms,gap):
    if gap>EPS:
        # GEOS performs both the spatial filtering and exact distance in C.
        return not len(tree.query(g,predicate='dwithin',distance=max(0,gap-EPS)))
    return not any(g.intersection(geoms[int(j)]).area>EPS for j in tree.query(g,predicate='intersects'))

def layout_score(layout,instances):
    shapes=[placed(instances[p['key']],p) for p in layout]
    return (round(max((g.bounds[3] for g in shapes),default=0),6),
            round(sum(g.area*g.centroid.y for g in shapes),4),
            round(sum(g.area*g.centroid.x for g in shapes),4))

def compact_complete(layout,instances,s,deadline,stop,on_improvement,axis="y"):
    """Move individual panels only upward; every intermediate layout is complete.

    X and angle remain unchanged, including paired panels and locked siblings.
    Test free intervals from top to bottom rather than stopping at the first
    obstacle below the current position: this can fill earlier enclosed gaps.
    """
    if axis=='x':
        # Transpose the entire collision scene, including the source frame.
        swapped={}
        for key,item in instances.items():
            swapped[key]={**item,'_noCompact':bool(item.get('verticalOnly')),'width':item['height'],'height':item['width'],
                'geom':affinity.affine_transform(item['geom'],[0,1,1,0,0,0]),
                'occupied':affinity.affine_transform(item['occupied'],[0,1,1,0,0,0])}
        def transpose(items):return [{**p,'x':p['y'],'y':p['x']} for p in items]
        def report(items,phase,moves):on_improvement(transpose(items),'整组横向压紧',moves)
        result,moves=compact_complete(transpose(layout),swapped,{**s,'head':s['left']},deadline,stop,report)
        return transpose(result),moves
    current=[p.copy() for p in layout];moves=0
    for _ in range(2):
        moved_in_pass=False
        order=sorted(range(len(current)),key=lambda i:placed(instances[current[i]['key']],current[i]).bounds[3],reverse=True)
        for index in order:
            if stop.is_set() or time.monotonic()>=deadline:return current,moves
            p=current[index]
            if p.get('locked') or instances[p['key']].get('_noCompact'):continue
            local=oriented(instances[p['key']],p['angle']);a,b,c,d=local.bounds
            others=[placed(instances[q['key']],q) for j,q in enumerate(current) if j!=index]
            tree=STRtree(others)
            relevant=[g for g in others if g.bounds[2]>=p['x']+a-s['gap'] and g.bounds[0]<=p['x']+c+s['gap']]
            bottom=s['head']-b;top=p['y']
            if top<=bottom+EPS:continue
            ys={bottom,top}
            for obstacle in relevant:
                oy0,oy1=obstacle.bounds[1],obstacle.bounds[3]
                ys.update((oy0-d-s['gap'],oy1-b+s['gap']))
                for _,v in vertices(obstacle,8):
                    ys.update((v-b+s['gap'],v-d-s['gap']))
            step=max(2,min(20,(d-b)/8),(top-bottom)/160)
            for n in range(int((top-bottom)/step)+1):ys.add(bottom+n*step)
            previous=bottom;best=None
            for y in sorted(v for v in ys if bottom-EPS<=v<top-EPS):
                if stop.is_set() or time.monotonic()>=deadline:return current,moves
                candidate=affinity.translate(local,p['x'],y)
                if clear_at(candidate,tree,others,s['gap']):
                    best=y
                    # Local refinement never assumes global monotonicity.
                    low=previous;high=y
                    for _ in range(12):
                        if high-low<.01 or stop.is_set() or time.monotonic()>=deadline:break
                        middle=(low+high)/2
                        if clear_at(affinity.translate(local,p['x'],middle),tree,others,s['gap']):high=middle
                        else:low=middle
                    best=high;break
                previous=y
            if best is not None and best<top-.01:
                current[index]={**p,'y':best};moves+=1;moved_in_pass=True
                on_improvement(current,'上下压紧',moves)
        if not moved_in_pass:break
    return current,moves

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
    for unit in grouped_order(order,instances):
        first=instances[unit[0]]
        relatives=[p for p in locks if first.get('verticalOnly') and instances[p['key']].get('sourceGroup')==first.get('sourceGroup')]
        if relatives:
            for key in unit:
                angle=relatives[0]['angle'];g=oriented(instances[key],angle)
                top=max([placed(instances[p['key']],p).bounds[3] for p in result],default=s['head'])
                result.append({'key':key,'pieceId':instances[key]['id'],'x':relatives[0]['x'],'y':top+s['gap']-g.bounds[1],'angle':angle,'locked':False})
            y=max(placed(instances[p['key']],p).bounds[3] for p in result)+s['gap'];x=s['left'];rowheight=0
            continue
        joined=unary_union([instances[k]['occupied'] for k in unit]);a,b,c,d=joined.bounds;w=c-a
        if x+w>s['width']-s['right']+EPS:
            x=s['left'];y+=rowheight+s['gap'];rowheight=0
        additions=[]
        for key in unit:
            candidate={'key':key,'pieceId':instances[key]['id'],'x':x-a,'y':y-b,'angle':0,'locked':False}
            shape=placed(instances[key],candidate)
            if any(conflicts(shape,placed(instances[p['key']],p),s['gap']) for p in additions):
                candidate['y']=max(placed(instances[p['key']],p).bounds[3] for p in additions)+s['gap']-instances[key]['occupied'].bounds[1]
            additions.append(candidate)
        result.extend(additions)
        rowheight=max(rowheight,max(placed(instances[p['key']],p).bounds[3] for p in additions)-y)
        x+=w+s['gap']
    return result

def pack(order,instances,s,locks,deadline,stop,orientation_cache=None):
    if orientation_cache is None:orientation_cache={}
    result=list(locks); geoms=[placed(instances[p['key']],p) for p in result]
    for key in [k for unit in grouped_order(order,instances) for k in unit]:
        if time.monotonic()>deadline or stop.is_set():raise Interrupted()
        part=instances[key];best=None
        tree=STRtree(geoms)
        obstacle_points=[v for g in geoms for v in vertices(g,12)]
        if len(obstacle_points)>200:obstacle_points=obstacle_points[::max(1,len(obstacle_points)//200)][:200]
        top=max([g.bounds[3] for g in geoms],default=s['head'])
        relatives=[p for p in result if part.get('verticalOnly') and instances[p['key']].get('sourceGroup')==part.get('sourceGroup')]
        family=[p for p in instances.values() if part.get('verticalOnly') and p.get('sourceGroup')==part.get('sourceGroup')]
        angles=[relatives[0]['angle']] if relatives else ([0,180] if part.get('allow180',True) and all(p.get('allow180',True) for p in family) else [0])
        for angle in angles:
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
            bound_a,bound_c=a,c
            if family:
                bound_a=min(oriented(p,angle).bounds[0] for p in family);bound_c=max(oriented(p,angle).bounds[2] for p in family)
                xs.update((s['left']-bound_a,s['width']-s['right']-bound_c))
            if relatives:xs={relatives[0]['x']}
            xs=sorted(x for x in xs if x+bound_a>=s['left']-EPS and x+bound_c<=s['width']-s['right']+EPS)
            ys=sorted(y for y in ys if y+b>=s['head']-EPS)
            # Bound candidate search; shelf fallback always remains available.
            if len(xs)>100:xs=sorted(set(xs[::max(1,len(xs)//90)]+xs[:6]+xs[-6:]))
            if len(ys)>140:ys=sorted(set(ys[::max(1,len(ys)//130)]+ys[:8]))
            for y in ys:
                if best and y+d>best[0]+EPS:continue
                for x in xs:
                    if time.monotonic()>deadline or stop.is_set():raise Interrupted()
                    moved=affinity.translate(g,x,y)
                    if not clear_at(moved,tree,geoms,s['gap']):continue
                    score=(max(top,y+d),y+b,x+a,angle)
                    if best is None or score<best[0:4]:best=(*score,x,y,angle,moved)
                    break
        if best is None:raise ValueError('未找到可行位置')
        result.append({'key':key,'pieceId':part['id'],'x':best[4],'y':best[5],'angle':best[6],'locked':False})
        geoms.append(best[7])
    return result

def _solve_panels(raw,stop,progress=lambda value:None):
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
    moves=0;warm=False
    geometric_orders=geometry_orders(order,instances)
    for alternative in geometric_orders:
        placements=baseline(alternative,instances,s,locks)
        if layout_score(placements,instances)<layout_score(best['placements'],instances):
            checked=validate({**raw,'placements':placements})
            if not checked['valid']:raise ValueError('几何重排初始方案复核失败')
            best=checked
    if raw.get('placements'):
        previous=validate(raw)
        if previous['valid'] and layout_score(previous['placements'],instances)<layout_score(best['placements'],instances):
            best=previous;warm=True
    report={**best,'comparison':comparison.copy(),'iterations':0,'seconds':time.monotonic()-started,'timedOut':False,'stopped':False,'phase':'已有方案' if warm else '初始可行方案','acceptedMoves':0}
    progress(report)
    rng=random.Random(s['seed']);deadline=started+s['seconds'];best_order=geometric_orders[0] if geometric_orders else order[:];orientation_cache={}
    score=layout_score(best['placements'],instances)
    def accept(candidate,phase,unused=0):
        nonlocal best,score,report,moves
        candidate_score=layout_score(candidate,instances)
        if candidate_score>=score:return False
        checked=validate({**raw,'placements':candidate})
        if not checked['valid']:raise ValueError('压紧/回填方案独立复核失败：'+checked['errors'][0]['message'])
        best=checked;score=candidate_score;moves+=1
        report={**best,'comparison':comparison.copy(),'iterations':0,'seconds':time.monotonic()-started,'timedOut':False,'stopped':False,'phase':phase,'acceptedMoves':moves}
        progress(report)
        return True
    compact_complete(best['placements'],instances,s,deadline,stop,accept,axis='x')
    compact_complete(best['placements'],instances,s,deadline,stop,accept)
    # Reinsert a complete source group into earlier gaps, from the roll tail
    # backwards. Other panels remain fixed, so an interrupted attempt cannot
    # discard any previously validated complete layout.
    units=grouped_order(order,instances)
    current={p['key']:p for p in best['placements']}
    units.sort(key=lambda unit:max(placed(instances[k],current[k]).bounds[3] for k in unit),reverse=True)
    for unit in units:
        if stop.is_set() or time.monotonic()>=deadline:break
        selected_keys=set(unit)
        fixed=[p for p in best['placements'] if p['key'] not in selected_keys]
        trial=sorted(unit,key=lambda k:-instances[k]['geom'].area)
        try:candidate=pack(trial,instances,s,fixed,deadline,stop,orientation_cache)
        except Interrupted:break
        accept(candidate,'尾部整组回填')
    compact_complete(best['placements'],instances,s,deadline,stop,accept)
    for iteration in range(s['iterations']):
        if stop.is_set() or time.monotonic()>deadline:break
        if iteration<3:trial=geometric_orders[iteration]
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
        candidate_score=layout_score(result['placements'],instances)
        if candidate_score<score:
            best=result;score=candidate_score;best_order=trial[:];moves+=1
            compact_complete(best['placements'],instances,s,deadline,stop,accept,axis='x')
            compact_complete(best['placements'],instances,s,deadline,stop,accept)
        report={**best,'comparison':comparison.copy(),'iterations':iteration+1,'seconds':time.monotonic()-started,'timedOut':False,'stopped':False,'phase':'多起点搜索','acceptedMoves':moves}
        progress(report)
    report.update(seconds=time.monotonic()-started,timedOut=time.monotonic()>=deadline,stopped=stop.is_set(),warmStarted=warm)
    report['comparison']=comparison+[{'label':'当前找到的最佳方案','length':best['stats']['length'],'effectiveUtilization':best['stats']['effectiveUtilization'],'seconds':report['seconds']}]
    progress(report)
    return report


def solve(raw,stop,progress=lambda value:None):
    """Search rigid source-image groups as exact unions of occupied contours.

    Expand only after placement: both source panels share X, Y and angle.
    White source margins do not consume fabric. Legacy nonfixed projects remain
    readable; the UI migrates their pair constraint before reoptimization.
    """
    if not any(p.get('fixedPair') for p in raw.get('pieces',[])):
        return _solve_panels(raw,stop,progress)
    from geometry import rings
    _,catalog,instances=prepare(raw)
    units=grouped_order(list(instances),instances)
    collapsed=[];mapping={};placements=[]
    existing={p['key']:p for p in raw.get('placements',[])}
    for unit in units:
        members=[instances[k] for k in unit]
        rigid=any(p.get('fixedPair') for p in members)
        if not rigid:
            for key in unit:
                collapsed.append(instances[key]);mapping[key]=[key]
                if key in existing:placements.append(existing[key])
            continue
        first=members[0];pid=first['id'];key=pid+'::0'
        joined=unary_union([m['occupied'] for m in members])
        # Occupied geometry already contains each member's own bleed/tolerance.
        collapsed.append({**first,'contours':rings(joined),'bleed':0,'contourTolerance':0,
            'verticalOnly':False,'fixedPair':False,'allow180':all(m.get('allow180',True) for m in members)})
        mapping[key]=unit
        old=[existing[k] for k in unit if k in existing]
        locked=any(p.get('locked') for p in old)
        aligned=len(old)==len(unit) and all(abs(p['x']-old[0]['x'])<EPS and abs(p['y']-old[0]['y'])<EPS and p['angle']==old[0]['angle'] for p in old)
        if locked and not aligned:raise ValueError('旧方案左右片已错位，请解除该组锁定后重新排料')
        if aligned:placements.append({**old[0],'key':key,'pieceId':pid,'locked':locked})
    reduced={**raw,'pieces':collapsed,'placements':placements}
    def expand(report):
        output=[]
        for p in report['placements']:
            for key in mapping[p['key']]:
                output.append({**p,'key':key,'pieceId':instances[key]['id'],
                    'locked':bool(existing.get(key,{}).get('locked'))})
        checked=validate({**raw,'placements':output})
        if not checked['valid']:raise ValueError('整组排料独立复核失败：'+checked['errors'][0]['message'])
        return {**report,**checked,'phase':'整组 · '+report.get('phase','优化')}
    answer=_solve_panels(reduced,stop,lambda report:progress(expand(report)))
    return expand(answer)
