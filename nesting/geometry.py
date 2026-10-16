"""Millimetre geometry. Artwork coordinates are never normalized independently."""
import math
from collections import Counter
from shapely import affinity
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

EPS = 1e-6

def number(v, name, low=0, high=1e6):
    if isinstance(v, bool):
        raise ValueError(f'{name}必须是数字')
    try:
        n = float(v)
    except (ValueError, TypeError):
        raise ValueError(f'{name}必须是数字')
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError(f'{name}应在{low}至{high}之间')
    return n

def settings(raw):
    s = {k: number(raw.get(k, v), k, *limits) for k, v, limits in [
        ('width',1580,(1,10000)),('left',10,(0,1000)),('right',10,(0,1000)),
        ('gap',3,(0,100)),('head',0,(0,10000)),('tail',0,(0,10000)),
        ('seconds',10,(1,120)),('seed',42,(0,2**32-1)),('iterations',12,(1,200))]}
    if s['width'] - s['left'] - s['right'] <= 0:
        raise ValueError('布边预留后有效门幅必须大于零')
    s['iterations'] = int(s['iterations'])
    return s

def polygon(contours):
    if not isinstance(contours, list) or not contours or len(contours) > 100:
        raise ValueError('缺少有效外轮廓（最多100个独立区域）')
    polys=[]
    for ring in contours:
        if not isinstance(ring,list) or not 3 <= len(ring) <= 50000:
            raise ValueError('轮廓点数应为3至50000')
        points=[(number(p[0],'轮廓X',-100000,100000),number(p[1],'轮廓Y',-100000,100000)) for p in ring]
        poly=Polygon(points)
        if not poly.is_valid or poly.area <= EPS:
            raise ValueError('轮廓自相交、退化或无效，请重新确认切割轮廓')
        polys.append(poly)
    g=unary_union(polys)
    if g.is_empty or not g.is_valid:
        raise ValueError('无效轮廓')
    return g

def rings(g):
    return [[[float(x),float(y)] for x,y in p.exterior.coords] for p in ([g] if g.geom_type=='Polygon' else g.geoms)]

def prepare(raw):
    s=settings(raw.get('settings',{})); pieces=raw.get('pieces',[])
    if not isinstance(pieces,list) or not pieces:
        raise ValueError('请先导入裁片')
    catalog={}; instances={}
    for p in pieces:
        pid=p.get('id')
        if not isinstance(pid,str) or not pid or pid in catalog or len(pid)>100:
            raise ValueError('裁片ID为空或重复')
        if p.get('confirmed') is not True or p.get('dimensionConfirmed') is not True:
            raise ValueError(f'{p.get("name",pid)}：请确认实际尺寸和轮廓')
        w=number(p.get('width'),'实际宽度',.01,10000);h=number(p.get('height'),'实际高度',.01,100000)
        q=number(p.get('quantity',1),'数量',1,1000)
        if q!=1:raise ValueError('本应用按一文件一裁片处理，每个文件数量必须为1')
        g=polygon(p.get('contours'))
        if not box(0,0,w,h).buffer(EPS).covers(g):raise ValueError('轮廓超出原图坐标范围')
        bleed=number(p.get('bleed',0),'出血',0,100)
        tolerance=number(p.get('contourTolerance',0),'轮廓保守余量',0,1)
        occupied=g.buffer(bleed+tolerance,quad_segs=12) if bleed+tolerance else g
        a,b,c,d=occupied.bounds
        if c-a > s['width']-s['left']-s['right']+EPS:
            raise ValueError(f'{p.get("name",pid)}：含出血宽度{c-a:.2f}mm超过有效门幅，0°/180°均无法放入')
        item={**p,'width':w,'height':h,'quantity':int(q),'geom':g,'occupied':occupied}
        catalog[pid]=item
        for i in range(int(q)):instances[f'{pid}::{i}']=item
    if len(instances)>500:raise ValueError('首版单任务最多500片，请分批排料')
    return s,catalog,instances

def oriented(piece,angle,occupied=True):
    g=piece['occupied'] if occupied else piece['geom']
    return g if angle==0 else affinity.rotate(g,180,origin=(piece['width']/2,piece['height']/2))

def placed(piece,p,occupied=True):
    return affinity.translate(oriented(piece,p['angle'],occupied),p['x'],p['y'])

def placement_fields(p,instances):
    key=p.get('key')
    if key not in instances:raise ValueError('排料实例ID无效')
    part=instances[key]; angle=p.get('angle')
    if angle not in (0,180) or isinstance(angle,bool):raise ValueError('仅允许0°或180°，禁止镜像及其他角度')
    if angle==180 and not part.get('allow180',True):raise ValueError('该裁片禁用180°旋转')
    return { 'key':key,'pieceId':part['id'],'x':number(p.get('x'),'X',-100000,1e6),
        'y':number(p.get('y'),'Y',-100000,1e6),'angle':angle,'locked':bool(p.get('locked',False)) }

def conflicts(a,b,gap):
    # Area intersection detects coincident boundaries correctly when gap=0.
    return a.intersection(b).area > EPS or (gap>0 and a.distance(b)<gap-EPS)

def validate(raw, partial=False):
    s,catalog,instances=prepare(raw); errors=[]; checked=[]; geoms=[]; seen=set()
    for source in raw.get('placements',[]):
        try:
            p=placement_fields(source,instances)
            if p['key'] in seen:raise ValueError('同一裁片实例出现多次')
            seen.add(p['key']);g=placed(instances[p['key']],p)
            x0,y0,x1,y1=g.bounds
            if x0<s['left']-EPS or x1>s['width']-s['right']+EPS or y0<s['head']-EPS:
                errors.append({'keys':[p['key']],'message':'裁片（含出血）超出门幅、布边或布头'})
            checked.append(p);geoms.append(g)
        except (ValueError,KeyError,TypeError) as exc:errors.append({'keys':[source.get('key','?')],'message':str(exc)})
    tree=STRtree(geoms)
    for i,g in enumerate(geoms):
        for j in tree.query(g.buffer(s['gap']+EPS)):
            j=int(j)
            if j>i and conflicts(g,geoms[j],s['gap']):
                errors.append({'keys':[checked[i]['key'],checked[j]['key']],'message':'裁片重叠或净间距不足'})
    missing=sorted(set(instances)-seen)
    if missing and not partial:errors.append({'keys':missing,'message':f'缺少{len(missing)}片裁片'})
    length=max([g.bounds[3] for g in geoms],default=s['head'])+s['tail']
    net=sum(instances[p['key']]['geom'].area for p in checked)
    occ=sum(instances[p['key']]['occupied'].area for p in checked)
    effective=s['width']-s['left']-s['right']
    counts=Counter(p['pieceId'] for p in checked)
    stats={'length':length,'bodyLength':length-s['head']-s['tail'],'netArea':net,'occupiedArea':occ,
        'bleedArea':occ-net,'effectiveWidth':effective,'effectiveUtilization':net/(effective*length) if length else 0,
        'fullUtilization':net/(s['width']*length) if length else 0,'areaLowerBound':sum(p['occupied'].area for p in instances.values())/effective+s['head']+s['tail'],
        'counts':[{'id':pid,'name':p.get('name',pid),'required':p['quantity'],'placed':counts[pid],'missing':max(0,p['quantity']-counts[pid])} for pid,p in catalog.items()]}
    return {'valid':not errors,'errors':errors,'missing':missing,'stats':stats,'placements':checked}
