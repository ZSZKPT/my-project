"""Snapshot-based many-to-many planning. No fashion-specific branches."""
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
import csv
import json
import re
import shutil
import threading
import uuid
from print_studio.core import atomic_json, sha256, load_image, EXTENSIONS
from print_studio.jobs import task_lock
from .models import local
from .library import validate, assets, fingerprint
from .render import render, export_image


def slug(value):
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_',str(value)).strip(' .')[:90]
    if not value or value in ('.','..'):raise ValueError('货号/文件名不能为空')
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:value='_'+value
    return value


def records_from_folder(folder):
    rows=[]; root=Path(folder)
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        files=sorted(p for p in directory.iterdir() if p.suffix.lower() in EXTENSIONS)
        preferred=[p for p in files if p.stem.casefold()=='print']
        if len(preferred)==1:files=preferred
        if len(files)>1:raise ValueError('货号目录有多张印花，请用表格明确指定：'+directory.name)
        if files:rows.append({'sku':directory.name,'print':str(files[0].resolve())})
    if not rows:raise ValueError('未找到“货号/print.png”目录')
    return rows


def records_from_table(path):
    path=Path(path)
    if path.suffix.lower()=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    elif path.suffix.lower()=='.xlsx':
        from openpyxl import load_workbook
        w=load_workbook(path,read_only=True,data_only=True)
        try:
            it=iter(w.active.values); headers=next(it); rows=[dict(zip(headers,r)) for r in it]
        finally:w.close()
    else:raise ValueError('支持UTF-8 CSV或XLSX')
    aliases={'货号':'sku','印花路径':'print','模板ID':'templates'}
    result=[]
    for row in rows:
        d={aliases.get(k,k):v for k,v in row.items() if k is not None}
        if all(v is None or v=='' for v in d.values()):continue
        if not d.get('sku') or not d.get('print'):raise ValueError('表格须有货号和印花路径列')
        p=Path(str(d['print']))
        d['print']=str((path.parent/p).resolve() if not p.is_absolute() else p.resolve())
        d['sku']=str(d['sku']);result.append(d)
    if not result:raise ValueError('表格无有效货号')
    return result


@dataclass
class BatchJob:
    app: str = 'fashion-mockup-batch'
    schema_version: int = 1
    mode: str = 'D'
    status: str = 'pending'
    items: list = field(default_factory=list)
    templates: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    hashes: dict = field(default_factory=dict)
    backend: str = 'local'


def plan(records, templates, mode='D', naming='{view}', overrides=None):
    if mode not in ('A','B','C','D'):raise ValueError('未知批量模式')
    specs=[validate(p,approved=True) for p in templates]
    if not records or not specs:raise ValueError('请导入货号印花并选择模板')
    if mode=='A' and len(specs)!=1:raise ValueError('模式A须选择一个模特视角模板')
    if mode=='B' and len({s.garment_type for s in specs})!=1:raise ValueError('模式B须选择同一版型的多模特/视角')
    if mode in ('B','C') and len({str(r['print']) for r in records})!=1:raise ValueError('模式B/C须使用同一印花')
    if len(records)*len(specs)>100000:raise ValueError('单任务最多10万张')
    result=[];names=set();overrides=overrides or {}
    for record in records:
        sku=slug(record['sku'])
        allowed=str(record.get('templates') or '').split(';')
        for index,s in enumerate(specs,1):
            if allowed!=[''] and s.id not in allowed:continue
            context={'sku':sku,'view':s.view,'model':s.model_id,'template':s.id,'garment':s.garment_type,'index':f'{index:02d}','print':Path(record['print']).stem}
            try:name=slug(naming.format(**context))
            except (KeyError,ValueError,IndexError):raise ValueError('命名规则仅支持sku/view/model/template/garment/index/print') from None
            output=f'output/{sku}/{name}.jpg'
            if output.casefold() in names:raise ValueError('输出文件名冲突：'+output+'；请在规则中加入{model}或{index}')
            names.add(output.casefold())
            assignments={r['id']:{'source_id':str(Path(record['print']).resolve()),'params':{}} for r in s.regions}
            for rid,a in overrides.get(s.id,{}).items():
                if rid not in assignments:raise ValueError('未知分区印花指定：'+rid)
                assignments[rid]={'source_id':str(Path(a.get('source',record['print'])).resolve()),'params':a.get('params',{})}
            result.append({'id':uuid.uuid4().hex,'sku':sku,'template_id':s.id,'output':output,'assignments':assignments,'status':'pending','error':'','sha256':''})
    if not result:raise ValueError('表格模板ID筛选后无任务')
    return result


class Queue:
    def __init__(self,path,emit=None):
        self.path=Path(path).resolve();self.root=self.path.parent
        d=json.loads(self.path.read_text(encoding='utf-8'))
        if d.get('app')!='fashion-mockup-batch' or d.get('schema_version')!=1:raise ValueError('不是多版型任务记录')
        self.state=BatchJob(**d);self.emit=emit or (lambda v:None)
        self.pause_event=threading.Event();self.cancel_event=threading.Event()

    def save(self):atomic_json(self.path,asdict(self.state))

    @classmethod
    def create(cls,records,templates,output,mode='D',naming='{view}',overrides=None,backend='local'):
        if backend not in ('local','photoshop'):raise ValueError('未知渲染后端')
        items=plan(records,templates,mode,naming,overrides)
        # Validate every source before creating a task folder.
        srcs={a['source_id'] for it in items for a in it['assignments'].values()}
        for p in srcs:load_image(p)
        root=Path(output)/('多版型任务_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]);root.mkdir(parents=True)
        try:
            state=BatchJob(mode=mode,items=items,backend=backend)
            for i,p in enumerate(sorted(srcs)):
                dest=root/'sources'/f'{i:05d}.png';dest.parent.mkdir(exist_ok=True)
                load_image(p).save(dest);state.sources[p]=dest.relative_to(root).as_posix()
            for path in templates:
                s=validate(path,True);folder=root/'templates'/s.id;folder.mkdir(parents=True)
                shutil.copyfile(path,folder/'mockup.json')
                for f in assets(path,s):
                    dest=folder/f.relative_to(Path(path).resolve().parent);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
                state.templates[s.id]=(folder/'mockup.json').relative_to(root).as_posix()
            for f in root.rglob('*'):
                if f.is_file():state.hashes[f.relative_to(root).as_posix()]=sha256(f)
            atomic_json(root/'batch.json',asdict(state));return cls(root/'batch.json')
        except Exception:shutil.rmtree(root);raise

    def check(self):
        for rel,digest in self.state.hashes.items():
            if sha256(local(self.root,rel))!=digest:raise ValueError('任务输入快照已修改：'+rel)

    def retry_failed(self):
        for i in self.state.items:
            if i['status']=='failed':i['status']='pending';i['error']=''
        self.state.status='pending';self.save()

    def manifest(self):
        # Explicit downstream interface; no browser publishing or automatic uploads.
        files=[{'sku':i['sku'],'template_id':i['template_id'],'file':i['output'],'sha256':i['sha256']} for i in self.state.items if i['status']=='done']
        atomic_json(self.root/'temu-images.json',{'schema_version':1,'images':files})

    def run(self):
        with task_lock(self.root):
            self.check();self.pause_event.clear();self.cancel_event.clear()
            self.state.status='running';self.save()
            for item in self.state.items:
                if self.pause_event.is_set() or self.cancel_event.is_set():break
                target=local(self.root,item['output'])
                if item['status']=='done':
                    if target.exists() and sha256(target)==item['sha256']:continue
                    item['status']='failed';item['error']='已完成输出被移动或修改；请核对后重试';self.save();continue
                if item['status']=='failed':continue
                item['status']='running';self.save()
                try:
                    # Unknown existing files are never overwritten.
                    if target.exists():raise FileExistsError('输出已存在且不属于已完成记录，请移走后重试：'+item['output'])
                    path=local(self.root,self.state.templates[item['template_id']])
                    sources={k:local(self.root,v) for k,v in self.state.sources.items()}
                    spec=validate(path,True)
                    if self.state.backend=='local':
                        export_image(render(path,sources,item['assignments']),target,spec.preset)
                    else:
                        from .photoshop import render_in_photoshop
                        render_in_photoshop(path,sources,item['assignments'],target,self.root/'photoshop'/item['id'])
                    item['sha256']=sha256(target);item['status']='done';item['error']=''
                except Exception as e:
                    item['status']='failed';item['error']=str(e)
                self.save();self.manifest();self.emit(item.copy())
            self.state.status=('cancelled' if self.cancel_event.is_set() else 'paused' if self.pause_event.is_set() else 'failed' if any(i['status']=='failed' for i in self.state.items) else 'done')
            self.save();self.manifest()
            return self.state.status
