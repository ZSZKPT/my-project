import base64
import io
import math
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageChops
from shapely.geometry import box, Polygon
from shapely.ops import unary_union
from svgelements import SVG, Shape, Path as SVGPath, Move, Close, Line
from geometry import number, rings

MAX_BYTES=24*1024*1024
Image.MAX_IMAGE_PIXELS=20_000_000

def data_url(raw,mime):return f'data:{mime};base64,'+base64.b64encode(raw).decode()

def decode_data(url):
    if not isinstance(url,str) or not re.fullmatch(r'data:image/(?:png|jpeg|svg\+xml);base64,[A-Za-z0-9+/=\s]+',url):raise ValueError('仅支持内嵌PNG/JPEG/SVG素材')
    raw=base64.b64decode(url.split(',',1)[1],validate=True)
    if len(raw)>MAX_BYTES:raise ValueError('单素材不能超过24MB')
    return raw

def safe_svg(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('不允许SVG外部实体')
    root=ET.fromstring(raw)
    if root.tag.split('}')[-1]!='svg':raise ValueError('不是有效SVG')
    for e in root.iter():
        tag=e.tag.split('}')[-1]
        if tag in ('script','foreignObject','use','animate','animateTransform','set','filter','mask','clipPath'):
            raise ValueError(f'首版不支持SVG中的{tag}，请先展开/转换')
        if tag=='style' or 'style' in e.attrib:raise ValueError('请将SVG样式展开为元素属性，避免轮廓与显示不一致')
        for k,v in e.attrib.items():
            name=k.split('}')[-1].lower()
            if name.startswith('on') or 'url(' in v.lower() or '@import' in v.lower():raise ValueError('SVG包含不支持的活动内容或外部引用')
            if name=='href' and not re.fullmatch(r'data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=\s]+',v):raise ValueError('SVG仅允许内嵌PNG/JPEG，不允许外部素材')
    return root

def physical(value):
    m=re.fullmatch(r'\s*([\d.]+)\s*(mm|cm|in|pt)\s*',value or '')
    if not m:return None
    return float(m[1])*{'mm':1,'cm':10,'in':25.4,'pt':25.4/72}[m[2]]

def raster_contour(image,mode,threshold,bg,min_area):
    if mode=='rectangle':return box(0,0,*image.size),True
    if mode=='alpha':
        if 'A' not in image.getbands() or image.getchannel('A').getextrema()[0]==255:
            raise ValueError('图片没有有效透明背景，请选择背景识别、配套SVG或明确使用矩形')
        mask=image.getchannel('A').point(lambda a:255 if a>=threshold else 0)
    elif mode=='background':
        rgb=image.convert('RGB');back=Image.new('RGB',rgb.size,bg)
        delta=ImageChops.difference(rgb,back);r,g,b=delta.split()
        mask=ImageChops.lighter(ImageChops.lighter(r,g),b).point(lambda a:255 if a>threshold else 0)
    else:raise ValueError('请选择轮廓提取方式')
    w,h=image.size;pixels=mask.tobytes();rects=[]
    # Exact occupied pixel-cell union. Holes filled below, never used for nesting.
    for y in range(h):
        row=pixels[y*w:(y+1)*w];x=0
        while x<w:
            a=row.find(b'\xff',x)
            if a<0:break
            b=row.find(b'\x00',a)
            if b<0:b=w
            rects.append(box(a,y,b,y+1));x=b
            if len(rects)>150000:raise ValueError('轮廓噪点过多，请提高背景阈值、清理原图或使用SVG切割线')
    if not rects:raise ValueError('未识别到裁片，请调整阈值')
    g=unary_union(rects);polys=[g] if g.geom_type=='Polygon' else list(g.geoms)
    polys=[Polygon(p.exterior) for p in polys if p.area>=min_area]
    if not polys:raise ValueError('去噪后轮廓为空')
    if len(polys)>100:raise ValueError('独立轮廓超过100个，请调整阈值或去噪')
    return unary_union(polys),False

def import_asset(request):
    raw=decode_data(request.get('data',''));filename=Path(request.get('filename','裁片')).name
    pid=uuid.uuid4().hex[:12]
    base={'id':pid,'name':filename,'filename':filename,'style':'','size':'','quantity':1,'allow180':True,'bleed':0,
        'confirmed':False,'dimensionConfirmed':False,'contourTolerance':0,'source':request['data']}
    if raw.lstrip().startswith(b'<'):
        root=safe_svg(raw)
        w=physical(root.get('width'));h=physical(root.get('height'))
        doc=SVG.parse(io.BytesIO(raw),reify=True,ppi=96)
        dw=float(doc.width);dh=float(doc.height)
        if dw<=0 or dh<=0:raise ValueError('SVG必须提供有效width、height或viewBox')
        w=number(request.get('width') or w or dw,'宽度',.01,10000)
        h=number(request.get('height') or h or dh,'高度',.01,100000)
        selectors=[e for e in doc.elements() if isinstance(e,Shape)]
        ids=[{'id':e.id or '', 'type':type(e).__name__} for e in selectors]
        selector=request.get('cutId','')
        if selector:selectors=[e for e in selectors if e.id==selector]
        elif len(selectors)!=1:
            return {'needsSelection':True,'svgElements':ids,'suggestedWidth':w,'suggestedHeight':h}
        if len(selectors)!=1:raise ValueError('请指定唯一的SVG切割轮廓ID')
        path=SVGPath(selectors[0]);contours=[];tolerance=.1
        for sub in path.as_subpaths():
            segments=list(sub)
            if not segments or not isinstance(segments[-1],Close):raise ValueError('切割轮廓必须闭合')
            points=[]
            for seg in segments:
                if isinstance(seg,Move):continue
                scale=max(w/dw,h/dh)
                count=1 if isinstance(seg,(Line,Close)) else max(1,math.ceil(seg.length(error=1e-6)*scale/(2*tolerance)))
                if count>50000:raise ValueError('SVG曲线过于复杂')
                for i in range(count):
                    p=seg.point(i/count);points.append([p.x*w/dw,p.y*h/dh])
            if len(points)>50000:raise ValueError('轮廓采样点超过50000')
            contours.append(points)
        base.update(width=w,height=h,contours=contours,contourTolerance=tolerance,
            dimensionConfirmed=bool((physical(root.get('width')) and physical(root.get('height'))) or (request.get('width') and request.get('height'))),
            contourSource=f'SVG #{selector or selectors[0].id or "唯一轮廓"}；曲线采样，保守余量0.1mm',svgElements=ids,mime='image/svg+xml')
        return base
    image=Image.open(io.BytesIO(raw));image.load()
    if image.format not in ('PNG','JPEG'):raise ValueError('首版仅支持JPG/JPEG、PNG、SVG')
    if image.width*image.height>20_000_000:raise ValueError('单图最多2000万像素，请分片或提供矢量轮廓')
    orientation=image.getexif().get(274,1)
    if orientation!=1:raise ValueError('JPG含EXIF旋转，请先将方向实际应用并另存，避免尺寸方向歧义')
    dpi=image.info.get('dpi')
    if dpi and not all(10<=float(v)<=2400 for v in dpi[:2]):dpi=None
    supplied=bool(request.get('width') and request.get('height'))
    explicit_dpi=request.get('dpi')
    if explicit_dpi:
        n=number(explicit_dpi,'DPI',10,2400);dpi=(n,n)
    w=number(request.get('width') or (image.width*25.4/dpi[0] if dpi else image.width),'宽度',.01,10000)
    h=number(request.get('height') or (image.height*25.4/dpi[1] if dpi else image.height),'高度',.01,100000)
    mode=request.get('mode','alpha' if image.format=='PNG' else 'background')
    threshold=int(number(request.get('threshold',128 if mode=='alpha' else 20),'阈值',0,255))
    min_area=number(request.get('minArea',0),'去噪面积',0,100000)
    g,rectangle=raster_contour(image,mode,threshold,request.get('background','#ffffff'),min_area)
    from shapely import affinity
    g=affinity.scale(g,xfact=w/image.width,yfact=h/image.height,origin=(0,0))
    base.update(width=w,height=h,contours=rings(g),pixelWidth=image.width,pixelHeight=image.height,dpi=list(dpi) if dpi else None,
        dimensionConfirmed=bool(supplied or dpi),mime='image/jpeg' if image.format=='JPEG' else 'image/png',
        contourSource='明确选择的矩形' if rectangle else ('透明通道像素外轮廓' if mode=='alpha' else '背景颜色识别候选（必须人工核对）'),
        hasICC=bool(image.info.get('icc_profile')),mode=mode,threshold=threshold)
    return base
