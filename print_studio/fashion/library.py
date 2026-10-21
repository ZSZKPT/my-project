"""Each model/view owns its masks; copying a look never copies coordinates silently."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json
import shutil
import tempfile
import uuid
from PIL import Image
from print_studio.core import atomic_json, load_image, sha256, save_png
from .models import MockupTemplate, PrintRegion, SmartObjectMapping, local, identifier,finite


def now(): return datetime.now(timezone.utc).isoformat()


def assets(path, spec=None):
    s = spec or MockupTemplate.read(path)
    values = [s.original, s.base, s.occlusion['mask']]
    values += [r['mask'] for r in s.regions]
    values += [r['shade'] for r in s.regions if r.get('shade')]
    if s.psd: values.append(s.psd)
    return list(dict.fromkeys(local(Path(path).parent, p) for p in values))


def fingerprint(path):
    s = MockupTemplate.read(path).to_dict()
    s.pop('review'); s.pop('ai_suggestion')
    # PSD is an output, not an input to mask approval.
    s.pop('psd')
    result = hashlib.sha256(json.dumps(s, sort_keys=True).encode())
    spec = MockupTemplate.read(path)
    for p in assets(path):
        if spec.psd and p == local(Path(path).parent, spec.psd): continue
        result.update(p.relative_to(Path(path).resolve().parent).as_posix().encode())
        result.update(sha256(p).encode())
    return result.hexdigest()


def validate(path, approved=False):
    s = MockupTemplate.read(path); root = Path(path).parent
    base = load_image(local(root, s.base))
    if load_image(local(root, s.original)).size != base.size:
        raise ValueError('模特原图与底图像素尺寸不一致')
    for r in s.regions:
        if not isinstance(r['params'],dict):raise ValueError('分区参数须为对象')
        for key,default,low,high in [('tile_px',180,2,20000),('scale',1,.05,20),('rotation',0,-360,360),('offset_x',0,-50000,50000),('offset_y',0,-50000,50000),('shade_strength',.35,0,1)]:
            finite(r['params'].get(key,default),low,high,key)
    w,h=int(s.preset.get('width',0)),int(s.preset.get('height',0))
    if bool(w)!=bool(h) or w<0 or h<0 or w*h>36_000_000:raise ValueError('输出尺寸无效')
    finite(s.preset.get('quality',95),50,100,'JPG质量')
    crop=s.preset.get('crop',[])
    if crop and (len(crop)!=4 or not (0<=crop[0]<crop[2]<=base.width and 0<=crop[1]<crop[3]<=base.height)):
        raise ValueError('输出裁剪范围越界')
    for name in [s.occlusion['mask']] + [r['mask'] for r in s.regions] + [r['shade'] for r in s.regions if r.get('shade')]:
        with Image.open(local(root, name)) as m:
            if m.size != base.size or m.mode != 'L':
                raise ValueError('蒙版/光影须为与底图同尺寸的灰度L模式PNG：' + name)
            if approved and name in [r['mask'] for r in s.regions] and not m.getbbox():
                raise ValueError('存在空分区，请绘制、合并或删除该分区：' + name)
    if approved and s.review.get('fingerprint') != fingerprint(path):
        raise ValueError('请重新核对并批准分类、每个部件蒙版及遮挡蒙版：' + s.name)
    return s


def approve(path):
    s = validate(path)
    # Check masks before writing approval.
    for r in s.regions:
        with Image.open(local(Path(path).parent, r['mask'])) as m:
            if not m.getbbox(): raise ValueError('空分区不可批准：' + r['name'])
    s.review = {'fingerprint': fingerprint(path), 'at': now(), 'method': 'manual'}
    atomic_json(path, s.to_dict())


class TemplateLibrary:
    def __init__(self, root):
        self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True)

    def list(self, query='', garment_type=''):
        rows = []
        for p in sorted(self.root.glob('*/mockup.json')):
            try:
                s = MockupTemplate.read(p)
                if garment_type and s.garment_type != garment_type: continue
                if query.casefold() not in (s.name+' '+s.model_id+' '+s.view+' '+s.garment_type).casefold(): continue
                rows.append((p, s))
            except (ValueError, TypeError, OSError): continue
        return rows

    def owned(self, path):
        p = Path(path).resolve()
        if p.parent.parent != self.root or p.name != 'mockup.json': raise ValueError('不是本模板库模板')
        return p

    def create(self, photo, garment, name, model_id, view):
        base = load_image(photo); id = 'tpl_' + uuid.uuid4().hex
        folder = self.root / id; folder.mkdir()
        try:
            save_png(base, folder/'original.png'); save_png(base, folder/'base.png')
            save_png(Image.new('L', base.size), folder/'occlusion.png')
            regions = []; mappings = []
            for p in garment.parts:
                rid = identifier(p['id']); mask = rid+'.png'
                save_png(Image.new('L', base.size), folder/mask)
                regions.append(asdict(PrintRegion(rid, p['name'], mask, rid)))
                mappings.append(asdict(SmartObjectMapping(rid, p['smart_object'])))
            s = MockupTemplate(id, garment.id, name, model_id, view, 'original.png', 'base.png', regions, mappings, created_at=now())
            atomic_json(folder/'mockup.json', s.to_dict())
            return folder/'mockup.json'
        except Exception:
            shutil.rmtree(folder); raise

    def save(self, path, spec):
        p = self.owned(path); old = MockupTemplate.read(p)
        if spec.id != old.id: raise ValueError('编辑不能改模板ID')
        spec.version = old.version+1; spec.review = {}
        atomic_json(p, spec.to_dict())

    def duplicate(self, path):
        p = self.owned(path); s = validate(p)
        folder = self.root/('tpl_'+uuid.uuid4().hex)
        shutil.copytree(p.parent, folder)
        s.id = folder.name; s.name += '（副本）'; s.version = 1; s.created_at = now(); s.review = {}; s.psd = ''
        atomic_json(folder/'mockup.json', s.to_dict())
        return folder/'mockup.json'

    def delete(self, path):
        # Reversible delete within the library; never delete original external photos.
        p = self.owned(path); trash = self.root/'.trash'; trash.mkdir(exist_ok=True)
        dest = trash/(p.parent.name+'_'+uuid.uuid4().hex[:8]); shutil.move(str(p.parent), dest)

    def export(self, path, target):
        p = self.owned(path); s = validate(p)
        if Path(target).exists(): raise FileExistsError('导出包已存在，请换名')
        with ZipFile(target, 'x', ZIP_DEFLATED) as z:
            z.write(p, 'mockup.json')
            for f in assets(p, s): z.write(f, f.relative_to(p.parent).as_posix())

    def import_zip(self, source):
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            folder = Path(temp)
            with ZipFile(source) as z:
                if len(z.infolist()) > 300 or sum(i.file_size for i in z.infolist()) > 500_000_000:
                    raise ValueError('模板包过大（最多300文件、500MB）')
                seen = set()
                for info in z.infolist():
                    dest = local(folder, info.filename.rstrip('/'))
                    if info.filename.casefold() in seen or (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('模板包含重复文件或符号链接')
                    seen.add(info.filename.casefold())
                    if info.is_dir(): dest.mkdir(parents=True, exist_ok=True); continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, dest.open('xb') as dst: shutil.copyfileobj(src, dst)
            if not (folder/'mockup.json').is_file():
                raise ValueError('模板包根目录缺少 mockup.json，请选择完整的多版型模板包')
            s = validate(folder/'mockup.json')
            dest = self.root/('tpl_'+uuid.uuid4().hex); dest.mkdir()
            # Copy only manifest-referenced assets; never import executable payloads.
            for f in assets(folder/'mockup.json', s):
                to = dest/f.relative_to(folder); to.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(f, to)
            s.id = dest.name; s.review = {}; s.created_at = now()
            atomic_json(dest/'mockup.json', s.to_dict())
            return dest/'mockup.json'
