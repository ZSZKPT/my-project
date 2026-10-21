"""OpenAI-compatible vision suggestions, always review-required polygon drafts."""
import base64
import json
import hashlib
import urllib.parse
from pathlib import Path
from PIL import Image,ImageDraw
from print_studio.api import request, reference_bytes
from print_studio.core import atomic_json,save_png,load_image
from .library import validate
from .models import local,finite


def image_digest(photo):
    image=load_image(photo)
    return hashlib.sha256(str(image.size).encode()+image.tobytes()).hexdigest()


def list_models(endpoint,key):
    from print_studio.api import secure_url
    endpoint=secure_url(endpoint)
    if '/chat/completions' not in endpoint:raise ValueError('请填写兼容chat/completions的完整地址')
    url=endpoint.rsplit('/chat/completions',1)[0]+'/models'
    data=json.loads(request(url,key=key))
    return sorted(str(v['id']) for v in data.get('data',[]) if isinstance(v,dict) and v.get('id'))


def suggest(photo,types,endpoint,model,key):
    if not model.strip() or not key:raise ValueError('请在软件内填写视觉模型ID和API Key')
    listing=[{'id':g.id,'name':g.name,'parts':g.parts} for g in types.values()]
    schema={'garment_type':'catalog id','confidence':0.0,'parts':[{'id':'catalog part id','name':'部件名','polygons':[[[0.1,0.2],[0.3,0.2],[0.3,0.5]]]}],
            'occlusion_polygons':[],'notes':'structures, folds, perspective, uncertain areas'}
    prompt=('Identify garment type and independent printable parts in the photo. Return JSON only using this structure: '+json.dumps(schema)+
            '. Polygon coordinates are normalized image coordinates, NOT bounding boxes. Use multiple polygons for disconnected areas. '
            'Exclude hair/skin/jewelry/background; mark their foreground overlap with occlusion_polygons. '
            'Describe collar/cuffs/pockets/cords/folds/seams/perspective in notes. If unsure use low confidence and empty polygons. '
            'Catalog: '+json.dumps(listing,ensure_ascii=False))
    payload={'model':model,'messages':[{'role':'user','content':[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(reference_bytes(photo)).decode()}}]}],
             'response_format':{'type':'json_object'},'max_tokens':4000}
    # Exactly one call. No retry on ambiguous paid request.
    response=json.loads(request(endpoint,json.dumps(payload).encode(),key,'application/json'))
    data=json.loads(response['choices'][0]['message']['content'])
    if data.get('garment_type') not in types:raise ValueError('视觉模型未返回可识别版型，请人工选择')
    finite(data.get('confidence',0),0,1,'置信度')
    data['status']='unreviewed_suggestion';data['source_sha256']=image_digest(photo);return data


def polygon_mask(size,polygons):
    mask=Image.new('L',size);draw=ImageDraw.Draw(mask)
    if not isinstance(polygons,list) or len(polygons)>100:raise ValueError('AI多边形数量无效')
    for polygon in polygons:
        if len(polygon)<3 or len(polygon)>1000:raise ValueError('AI多边形顶点数量无效')
        points=[(finite(p[0],0,1,'X')*(size[0]-1),finite(p[1],0,1,'Y')*(size[1]-1)) for p in polygon]
        draw.polygon(points,fill=255)
    return mask


def apply_suggestion(path,data):
    s=validate(path);root=Path(path).parent
    if s.garment_type!=data['garment_type']:raise ValueError('请先按AI建议的版型新建模板，再导入建议')
    if data.get('source_sha256')!=image_digest(local(root,s.original)):
        raise ValueError('AI建议不属于当前模特原图，不能借用其他模特坐标')
    with Image.open(local(root,s.base)) as base:size=base.size
    byid={r['id']:r for r in s.regions}
    # Validate every polygon before changing any file.
    masks={p['id']:polygon_mask(size,p.get('polygons',[])) for p in data.get('parts',[]) if p['id'] in byid}
    occ=polygon_mask(size,data.get('occlusion_polygons',[]))
    for rid,m in masks.items():save_png(m,local(root,byid[rid]['mask']))
    save_png(occ,local(root,s.occlusion['mask']))
    s.ai_suggestion=data;s.review={};s.version+=1
    atomic_json(path,s.to_dict())
