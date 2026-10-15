"""Durable image/upload checkpoints. No credentials are serialized."""
import csv
import hashlib
import json
import os
import shutil
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PureWindowsPath
from desktop.core import prepare
from desktop.profiles import products_to_rows, storage_dir
from import_tools.miaoshou import export
from import_tools.image_rules import validate_groups


def atomic_json(path,value):
    path=Path(path);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('w',encoding='utf-8') as file:
            json.dump(value,file,ensure_ascii=False,indent=2);file.flush();os.fsync(file.fileno())
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()


@contextmanager
def task_lock(directory):
    file=(Path(directory)/'.task.lock').open('a+b');locked=False
    try:
        file.seek(0,2)
        if not file.tell():file.write(b'0');file.flush()
        file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError:raise ValueError('此任务已在其他窗口运行，请先暂停并退出那个窗口') from None
        yield
    finally:
        if locked:
            file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_UN)
        file.close()


class Task:
    def __init__(self,path,emit=None,gate=None):
        self.path=Path(path).resolve();self.root=self.path.parent
        self.state=json.loads(self.path.read_text(encoding='utf-8'))
        if self.state.get('version')!=1:raise ValueError('任务记录版本不支持')
        for group in self.state.get('groups',[]):
            sku=group['sku']
            if not sku or sku in ('.','..') or '/' in sku or '\\' in sku:raise ValueError('任务中的货号路径无效')
        self.emit=emit or (lambda *args:None)
        self.gate=gate or threading.Event()
        if gate is None:self.gate.set()

    @classmethod
    def create(cls,values,config,groups,emit=None,gate=None):
        validate_groups(groups)
        root=Path(values['output'])/('妙手_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));root.mkdir(parents=True,exist_ok=False)
        shutil.copy2(values['template'],root/'导入模板.xlsx')
        atomic_json(root/'模板配置.json',config)
        state={'version':1,'status':'pending','config':config,'settings':{key:values.get(key,'') for key in ('source','mode','size','links','main_suffix')},
               'groups':[{'sku':g['sku'],'print_name':g['print_name'],'sources':[str(Path(p).resolve()) for p in g['files']],'prepared':None,'urls':{}} for g in groups]}
        atomic_json(root/'任务进度.json',state)
        return cls(root/'任务进度.json',emit,gate)

    @classmethod
    def adopt_legacy(cls,directory,values,config,groups,emit=None):
        validate_groups(groups)
        root=Path(directory).resolve()
        if (root/'任务进度.json').is_file():return cls(root/'任务进度.json',emit)
        if (root/'妙手导入.xlsx').exists():raise ValueError('该目录已有妙手导入.xlsx，可直接使用，不需要重新生成')
        links=root/'图片链接.csv'
        if not links.is_file():raise ValueError('请选择旧版输出目录，目录中应有图片链接.csv')
        with task_lock(root):
            with links.open(encoding='utf-8-sig',newline='') as file:records={row['sku']:row for row in csv.DictReader(file)}
            if set(records)-{g['sku'] for g in groups}:raise ValueError('请先扫描完整原始图片目录；旧输出中的部分货号未在当前列表中')
            state={'version':1,'status':'interrupted','config':config,'settings':{key:values.get(key,'') for key in ('source','mode','size','links','main_suffix')},'groups':[],'config_file':'续作模板配置.json'}
            for group in groups:
                sku=group['sku'];target=root/sku
                if target.resolve().parent!=root:raise ValueError('货号路径无效')
                data={'sku':sku,'print_name':records.get(sku,{}).get('print_name') or group['print_name'],'sources':[str(Path(p).resolve()) for p in group['files']],'prepared':None,'urls':{}}
                if target.is_dir():
                    paths=sorted((p for p in target.glob('*.jpg') if p.name[:2].isdigit() and p.name[2:3]=='_'),key=lambda p:p.name)
                    materials=list(target.glob('素材图_*.jpg'))
                    if len(paths)!=len(group['files']) or len(materials)!=1:raise ValueError(f'{sku}旧版处理图片数量不一致，无法安全接续')
                    material=materials[0]
                    data['prepared']={'carousel':[p.relative_to(root).as_posix() for p in paths],'material':material.relative_to(root).as_posix(),
                                      'files':[{'path':p.relative_to(root).as_posix(),'sha256':digest(p)} for p in paths+[material]]}
                    row=records.get(sku)
                    if row:
                        urls=row.get('carousel_urls','').split('|')
                        if len(urls)!=len(paths):raise ValueError(f'{sku}已保存链接数量与图片数量不一致')
                        data['urls'].update({p:u for p,u in zip(data['prepared']['carousel'],urls) if u})
                        if row.get('material_url'):data['urls'][data['prepared']['material']]=row['material_url']
                elif sku in records:raise ValueError(f'{sku}有旧链接但已处理文件缺失，请恢复文件后继续')
                state['groups'].append(data)
            if not (root/'导入模板.xlsx').exists():shutil.copy2(values['template'],root/'导入模板.xlsx')
            if not (root/'图片链接_续作前.csv').exists():shutil.copy2(links,root/'图片链接_续作前.csv')
            atomic_json(root/'续作模板配置.json',config);atomic_json(root/'任务进度.json',state)
        return cls(root/'任务进度.json',emit)

    def save(self):atomic_json(self.path,self.state)

    def local(self,relative):
        path=(self.root/relative).resolve()
        try:path.relative_to(self.root)
        except ValueError:raise ValueError('任务记录包含非法文件路径') from None
        return path

    def relink_sources(self,directory):
        directory=Path(directory).resolve()
        if not directory.is_dir():raise ValueError('请选择有效的原图目录')
        with task_lock(self.root):
            self.state=json.loads(self.path.read_text(encoding='utf-8'))
            changes=[];missing=[]
            for group in self.state['groups']:
                if group['prepared']:continue
                replacement=[]
                for old in group['sources']:
                    if Path(old).is_file():replacement.append(old);continue
                    name=PureWindowsPath(old).name if '\\' in old else Path(old).name
                    candidates=[directory/group['sku']/name]
                    if directory.name==group['sku']:candidates.append(directory/name)
                    match=next((p for p in candidates if p.is_file()),None)
                    if match is None:missing.append(group['sku']+'/'+name)
                    else:replacement.append(str(match))
                changes.append((group,replacement))
            if missing:raise ValueError('未找到以下原图，未更改任务：'+ '、'.join(missing[:10]))
            for group,replacement in changes:group['sources']=replacement
            self.state['settings']['source']=str(directory);self.save()
            return len(changes)

    def boundary(self):
        if not self.gate.is_set():
            self.state['status']='paused';self.save();self.emit('status','已暂停 · 进度已保存')
            self.gate.wait()
            self.state['status']='running';self.save();self.emit('status','正在继续任务')

    def prepare_group(self,g):
        if g['prepared']:
            for item in g['prepared']['files']:
                path=self.local(item['path'])
                if not path.is_file() or digest(path)!=item['sha256']:raise ValueError(f'{g["sku"]}已处理图片缺失或被修改，请恢复任务输出文件后继续')
            return
        target=self.local(g['sku'])
        manifest=target/'.prepared-manifest.json'
        if manifest.is_file():
            record=json.loads(manifest.read_text(encoding='utf-8'))
            if len(record['carousel'])!=len(g['sources']):raise ValueError('已处理图片数量与任务不一致')
            for item in record['files']:
                if digest(self.local(item['path']))!=item['sha256']:raise ValueError('已处理图片校验失败，请恢复文件')
            g['prepared']=record;self.save();self.emit('log',g['sku']+'已恢复处理图片记录，无需重新生成');return
        missing=[p for p in g['sources'] if not Path(p).is_file()]
        if missing:raise ValueError(g['sku']+'找不到原图：'+str(missing[0])+'；请点击“重新定位原图目录”，不要删除任务或输出文件')
        self.boundary()
        stage=self.root/('.prepare-'+uuid.uuid4().hex);stage.mkdir()
        try:
            ready=prepare({'sku':g['sku'],'files':[Path(p) for p in g['sources']]},stage,int(self.state['settings']['size']))
            target=self.local(g['sku'])
            if target.exists():target.rename(self.root/('.preserved-'+uuid.uuid4().hex))
            paths=ready['carousel'];material=ready['material']
            record={'carousel':[(Path(g['sku'])/p.name).as_posix() for p in paths],'material':(Path(g['sku'])/material.name).as_posix(),
                    'files':[{'path':(Path(g['sku'])/p.name).as_posix(),'sha256':digest(p)} for p in paths+[material]]}
            atomic_json(stage/g['sku']/'.prepared-manifest.json',record)
            shutil.move(str(stage/g['sku']),str(target))
            g['prepared']=record
            self.save();self.emit('log',g['sku']+' 图片已处理并保存')
        finally:shutil.rmtree(stage,ignore_errors=True)

    def write_links(self):
        target=self.root/'图片链接.csv';temp=target.with_suffix('.csv.tmp')
        with temp.open('w',encoding='utf-8-sig',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=['sku','print_name','carousel_urls','material_url','preview_url']);writer.writeheader()
            for g in self.state['groups']:
                prepared=g['prepared']
                if not prepared:continue
                urls=[g['urls'].get(p,'') for p in prepared['carousel']]
                writer.writerow({'sku':g['sku'],'print_name':g['print_name'],'carousel_urls':'|'.join(urls),'material_url':g['urls'].get(prepared['material'],''),'preview_url':urls[0] if urls else ''})
        os.replace(temp,target)

    def needs_upload(self):
        if self.state['status']=='complete' or self.state['settings']['mode']!='ImgBB 自动上传':return False
        return any(not group['prepared'] or any(path not in group['urls'] for path in group['prepared']['carousel']+[group['prepared']['material']]) for group in self.state['groups'])

    def recover_export(self):
        pending=self.state.get('pending_export')
        if not pending or not pending.get('sha256'):return None
        target=self.local(pending['target']);temp=self.local(pending['temp'])
        if target.exists():
            if digest(target)!=pending['sha256']:raise ValueError('待恢复表格已被修改，请恢复原文件后继续，不会覆盖现有表格')
        elif temp.is_file() and digest(temp)==pending['sha256']:os.replace(temp,target)
        else:return None
        self.state.update(status='complete',workbook=target.name,workbook_sha256=pending['sha256']);self.save()
        self.emit('log','沿用中断前已生成表格，不重新生成：'+str(target));self.emit('progress',100);self.emit('status','表格已生成 · 待手动导入')
        return target

    def run(self,uploader,links_path=None):
        with task_lock(self.root):
            # Re-read after acquiring the lock, avoiding a stale state from another process.
            self.state=json.loads(self.path.read_text(encoding='utf-8'))
            validate_groups(self.state['groups'],key='sources')
            self.emit('task',str(self.path));self.emit('output',str(self.root))
            if self.state['status']=='complete':
                path=self.local(self.state['workbook'])
                if not path.is_file() or digest(path)!=self.state['workbook_sha256']:raise ValueError('已完成表格缺失或被修改，请先恢复文件')
                self.emit('log','该任务已经完成，沿用已有表格：'+str(path));self.emit('progress',100);self.emit('status','表格已生成 · 待手动导入');return path
            try:
                recovered=self.recover_export()
                if recovered:return recovered
                self.state['status']='running';self.save()
                total=sum(len(g['sources'])+1 for g in self.state['groups'])
                done=sum(len(g['urls']) for g in self.state['groups'])
                self.emit('progress',min(90,done/total*90))
                supplied={}
                if links_path:
                    with open(links_path,encoding='utf-8-sig',newline='') as file:
                        for row in csv.DictReader(file):
                            if row['sku'] in supplied:raise ValueError('链接表有重复货号')
                            supplied[row['sku']]=row
                products=[]
                for g in self.state['groups']:
                    self.boundary();self.prepare_group(g);prepared=g['prepared']
                    files=prepared['carousel']+[prepared['material']]
                    if self.state['settings']['mode']=='ImgBB 自动上传':
                        for relative in files:
                            self.boundary()
                            if relative in g['urls']:continue
                            url=uploader(self.local(relative))
                            from import_tools.dianxiaomi import image_url
                            g['urls'][relative]=image_url(url)
                            self.save();self.write_links();done+=1
                            self.emit('progress',min(90,done/total*90));self.emit('log',g['sku']+' 上传进度已保存')
                    elif g['sku'] in supplied:
                        row=supplied[g['sku']];urls=row.get('carousel_urls','').split('|')
                        if len(urls)!=len(prepared['carousel']):raise ValueError('手动链接数量需与商品图片数量一致')
                        g['urls'].update(dict(zip(prepared['carousel'],urls)))
                        if row.get('material_url'):g['urls'][prepared['material']]=row['material_url']
                        self.save()
                    products.append({'sku':g['sku'],'print_name':g['print_name'],'carousel_urls':'|'.join(g['urls'].get(p,'') for p in prepared['carousel']),
                                     'material_url':g['urls'].get(prepared['material'],'')})
                self.write_links();self.boundary()
                if any(not p['material_url'] or not all(p['carousel_urls'].split('|')) for p in products):
                    self.state['status']='waiting_links';self.save();self.emit('status','图片已处理 · 待补链接');self.emit('log','在图片链接CSV填好链接后，可加载此任务继续生成。');return None
                rows,titles=products_to_rows(self.state['config'],products,self.state['config']['price']);self.emit('progress',95)
                temp=self.root/('.export-'+uuid.uuid4().hex+'.xlsx')
                result=export(self.root/'导入模板.xlsx',rows,temp,titles,self.state['config']['origin'])
                target=self.root/'妙手导入.xlsx'
                if target.exists():target=self.root/('妙手导入_续作_'+uuid.uuid4().hex[:8]+'.xlsx')
                self.state['pending_export']={'temp':temp.name,'target':target.name,'sha256':digest(temp)};self.save()
                os.replace(temp,target)
                self.state.update(status='complete',workbook=target.name,workbook_sha256=digest(target));self.save()
                self.emit('progress',100);self.emit('status','表格已生成 · 待手动导入')
                self.emit('log',f'已生成{result["product_count"]}个商品、{result["sku_count"]}行SKU；表格已生成，待手动导入。')
                for warning in result['warnings']:self.emit('log','提示：'+warning)
                return target
            except Exception:
                self.state['status']='interrupted'
                try:self.save()
                except OSError:pass
                raise


def remember(path):
    directory=storage_dir().parent
    directory.mkdir(parents=True,exist_ok=True)
    atomic_json(directory/'last-task.json',{'task':str(Path(path).resolve())})


def last_task():
    try:
        pointer=json.loads((storage_dir().parent/'last-task.json').read_text(encoding='utf-8'))
        path=Path(pointer['task'])
        return path if path.is_file() else None
    except (OSError,ValueError,KeyError,TypeError):return None
