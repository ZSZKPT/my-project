"""Deterministic independent-region rendering, shared sources and projective mapping."""
from pathlib import Path
import math
from PIL import Image, ImageChops, ImageEnhance, ImageOps
from print_studio.core import load_image, repeat
from .library import validate
from .models import local, finite


def solve(matrix, vector):
    a = [list(row)+[b] for row,b in zip(matrix, vector)]
    for col in range(len(vector)):
        pivot = max(range(col, len(a)), key=lambda r: abs(a[r][col]))
        a[col],a[pivot] = a[pivot],a[col]
        if abs(a[col][col]) < 1e-10: raise ValueError('透视四边形退化')
        v = a[col][col]; a[col] = [x/v for x in a[col]]
        for r in range(len(a)):
            if r == col: continue
            v = a[r][col]; a[r] = [x-v*y for x,y in zip(a[r],a[col])]
    return [row[-1] for row in a]


def projective(image, quad):
    if not isinstance(quad, list) or len(quad) != 4 or any(len(p) != 2 for p in quad):
        raise ValueError('透视需按左上、右上、右下、左下填写4个归一化坐标')
    w,h = image.size
    target = [(finite(p[0], -2, 3, '透视X')*w, finite(p[1], -2, 3, '透视Y')*h) for p in quad]
    signs = []
    for i in range(4):
        a,b,c=target[i],target[(i+1)%4],target[(i+2)%4]
        signs.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
    if not (all(v > 0 for v in signs) or all(v < 0 for v in signs)):
        raise ValueError('透视四边形必须凸且不交叉')
    matrix=[]; values=[]
    for (x,y),(u,v) in zip(target, [(0,0),(w,0),(w,h),(0,h)]):
        matrix += [[x,y,1,0,0,0,-u*x,-u*y], [0,0,0,x,y,1,-v*x,-v*y]]
        values += [u,v]
    coeff = solve(matrix, values)
    return image.transform(image.size, Image.Transform.PERSPECTIVE, coeff, Image.Resampling.BICUBIC)


def region_layer(tile, base, spec, params, root):
    p = dict(spec['params']); p.update(params)
    scale = finite(p.get('scale',1), .05, 20, '缩放')
    tile_px = finite(p.get('tile_px',180), 2, 20000, '循环宽度')*scale
    if tile_px*tile_px*tile.height/tile.width > 36_000_000:
        raise ValueError('循环单元放大后超过3600万像素')
    width = max(1,round(tile_px)); height=max(1,round(width*tile.height/tile.width))
    tile = tile.resize((width,height), Image.Resampling.LANCZOS)
    angle = finite(p.get('rotation',0), -360, 360, '旋转')
    x = finite(p.get('offset_x',0), -50000, 50000, '水平偏移')
    y = finite(p.get('offset_y',0), -50000, 50000, '垂直偏移')
    if angle % 360:
        # Render a larger repeated plane then rotate the whole plane; no gaps between rotated tiles.
        diagonal = math.ceil(math.hypot(*base.size))
        if diagonal*diagonal > 50_000_000: raise ValueError('旋转画布过大，请缩小底图')
        plane = repeat(tile,(diagonal,diagonal),width,(round(x),round(y)))
        plane = plane.rotate(angle,Image.Resampling.BICUBIC)
        left=(diagonal-base.width)//2; top=(diagonal-base.height)//2
        plane=plane.crop((left,top,left+base.width,top+base.height))
    else: plane=repeat(tile,base.size,width,(round(x),round(y)))
    if p.get('quad') is not None: plane=projective(plane,p['quad'])
    strength = finite(p.get('shade_strength',0),0,1,'光影强度')
    if strength:
        shade = Image.open(local(root,spec['shade'])).convert('L') if spec.get('shade') else ImageOps.grayscale(base)
        # White base recommended: old printed albedo would also multiply through.
        shade=Image.blend(Image.new('L',base.size,255),shade,strength)
        plane=ImageChops.multiply(plane,Image.merge('RGB',(shade,shade,shade)))
    return plane


def render(path, sources, assignments, approved=True, return_layers=False):
    s=validate(path,approved=approved); root=Path(path).parent
    base=load_image(local(root,s.base)); result=base.copy(); layers=[]
    with Image.open(local(root,s.occlusion['mask'])) as m: occlusion=m.copy()
    region_ids={r['id'] for r in s.regions}
    if set(assignments)-region_ids: raise ValueError('印花指定了不存在的分区')
    for r in s.regions:
        a=assignments.get(r['id'])
        if not a: raise ValueError('分区未指定印花：'+r['name'])
        if a['source_id'] not in sources: raise ValueError('找不到印花来源：'+a['source_id'])
        layer=region_layer(load_image(sources[a['source_id']]),base,r,a.get('params',{}),root)
        with Image.open(local(root,r['mask'])) as m: mask=ImageChops.multiply(m,ImageOps.invert(occlusion))
        result=Image.composite(layer,result,mask)
        layers.append((r['id'],layer,mask))
    if return_layers:return result,layers
    return result


def export_image(image, target, preset):
    import os,uuid
    target=Path(target); target.parent.mkdir(parents=True,exist_ok=True)
    crop=preset.get('crop',[])
    if crop:
        if len(crop)!=4: raise ValueError('裁剪须为left,top,right,bottom')
        l,t,r,b=map(int,crop)
        if not (0<=l<r<=image.width and 0<=t<b<=image.height):raise ValueError('裁剪范围越界')
        image=image.crop((l,t,r,b))
    w,h=int(preset.get('width',0)),int(preset.get('height',0))
    if bool(w)!=bool(h) or w<0 or h<0 or w*h>36_000_000:raise ValueError('输出宽高须同时填写且不超过3600万像素')
    if w and h:image=ImageOps.fit(image,(w,h),method=Image.Resampling.LANCZOS)
    q=int(finite(preset.get('quality',95),50,100,'JPG质量'))
    temp=target.with_name('.'+uuid.uuid4().hex+'.jpg')
    try:image.convert('RGB').save(temp,'JPEG',quality=q,subsampling=0);os.replace(temp,target)
    finally:temp.unlink(missing_ok=True)
