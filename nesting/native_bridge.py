"""Native save and local collection, available only to this app's window."""
import base64
import logging
import os
from pathlib import Path
import tempfile
import threading
import uuid
import csv
import shutil
from datetime import datetime
from urllib.parse import urlparse


class NativeBridge:
    def __init__(self,origin):
        self._origin=origin
        self._window=None
        self._save_lock=threading.Lock()
        self._exports={}
        self._export_mutex=threading.Lock()
        self._binding_files={}
        self._binding_root=None
        self._binding_lock=threading.Lock()

    def _check_origin(self):
        current=urlparse(self._window.get_current_url() if self._window else '')
        expected=urlparse(self._origin)
        if (current.scheme,current.netloc)!=(expected.scheme,expected.netloc):
            raise ValueError('保存仅允许从本软件界面发起')

    def info(self):
        self._check_origin()
        return {'embedded':True,'version':'7.0','nativeSave':True}

    def choose_binding_folder(self,recursive=False):
        """Read only the folder explicitly selected in the native chooser."""
        try:
            self._check_origin()
            import webview
            from binding import strip_key
            chosen=self._window.create_file_dialog(webview.FileDialog.FOLDER)
            if not chosen:return {'cancelled':True}
            root=Path(chosen[0] if isinstance(chosen,(list,tuple)) else chosen).resolve()
            if not root.is_dir():raise ValueError('请选择有效的包边条文件夹')
            files={};count=0
            for candidate in (root.rglob('*') if recursive else root.iterdir()):
                count+=1
                if count>50000:raise ValueError('文件夹超过50000个条目，请缩小选择范围')
                if not candidate.is_file() or strip_key(candidate.name) is None:continue
                resolved=candidate.resolve()
                if root not in resolved.parents:continue
                key=uuid.uuid4().hex
                files[key]={'id':key,'name':candidate.name,'relativePath':str(candidate.relative_to(root)),
                            'size':resolved.stat().st_size,'path':resolved}
            with self._binding_lock:self._binding_root=root;self._binding_files=files
            return {'folder':str(root),'files':[{k:v for k,v in entry.items() if k!='path'} for entry in files.values()]}
        except Exception as exc:return {'error':str(exc)}

    def match_binding_files(self,requests,rule='style-prefix'):
        try:
            self._check_origin()
            from binding import match_files
            with self._binding_lock:
                if self._binding_root is None:raise ValueError('请先选择包边条文件夹')
                files=[{k:v for k,v in entry.items() if k!='path'} for entry in self._binding_files.values()]
            return match_files(requests,files,rule)
        except Exception as exc:return {'error':str(exc)}

    def _binding_entry(self,file_id):
        with self._binding_lock:
            entry=self._binding_files.get(file_id);root=self._binding_root
            if entry is None or root is None:raise ValueError('文件已失效，请重新选择包边条文件夹')
            path=entry['path'].resolve()
            if root not in path.parents or not path.is_file():raise ValueError('包边条已移动或不在所选文件夹内')
            return path

    def copy_binding_files(self,requests,rule='style-prefix'):
        """One byte-identical strip copy for every original source instance."""
        if not self._save_lock.acquire(blocking=False):return {'error':'正在保存，请等待完成'}
        staging=None
        try:
            self._check_origin()
            from binding import match_files,filename_stem
            with self._binding_lock:
                if self._binding_root is None:raise ValueError('请先选择包边条文件夹')
                files=[{k:v for k,v in entry.items() if k!='path'} for entry in self._binding_files.values()]
            matched=match_files(requests,files,rule)
            if matched['missing'] or matched['ambiguous']:raise ValueError('存在未找到或重名的包边条，请先修正匹配结果')
            paths=[self._binding_entry(m['file']['id']) for m in matched['matches']]
            import webview
            chosen=self._window.create_file_dialog(webview.FileDialog.FOLDER)
            if not chosen:return {'cancelled':True}
            parent=Path(chosen[0] if isinstance(chosen,(list,tuple)) else chosen).resolve()
            if not parent.is_dir():raise ValueError('请选择有效的输出文件夹')
            required=sum(path.stat().st_size for path in paths)
            if shutil.disk_usage(parent).free<required+1024*1024:raise ValueError('输出文件夹磁盘空间不足')
            staging=Path(tempfile.mkdtemp(dir=parent,prefix='.buxu-binding-'))
            mapping=[];used=set()
            for match,path in zip(matched['matches'],paths):
                stem=filename_stem(match['filename']);base=stem+'-包边条';name=base+path.suffix.lower();serial=2
                while name.casefold() in used:name=f'{base} ({serial})'+path.suffix.lower();serial+=1
                # Filenames came from source metadata, never allow path syntax
                # to escape the new output folder (including Windows paths).
                name=''.join('_' if c in '<>:"/\\|?*' or ord(c)<32 else c for c in name).rstrip(' .')
                if not name or len(name)>220:raise ValueError('输出图片文件名为空或过长')
                if name.casefold() in used:raise ValueError('输出文件名清理后重复，请修改原文件名')
                used.add(name.casefold())
                # Recheck the selected source path immediately before reading.
                source=self._binding_entry(match['file']['id'])
                shutil.copy2(source,staging/name)
                mapping.append((match['filename'],match['file']['relativePath'],name))
            with (staging/'包边条对应清单.csv').open('w',encoding='utf-8-sig',newline='') as output:
                writer=csv.writer(output);writer.writerow(['已排原图片','包边条来源','复制文件'])
                def safe(v):return "'"+v if v.startswith(('=','+','-','@','\t','\r')) else v
                writer.writerows([[safe(v) for v in row] for row in mapping])
            folder=parent/('布序包边条-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
            os.rename(staging,folder);staging=None
            return {'saved':True,'folder':str(folder),'count':len(mapping)}
        except Exception as exc:
            logging.exception('Binding strip copy failed');return {'error':str(exc)}
        finally:
            if staging is not None:shutil.rmtree(staging,ignore_errors=True)
            self._save_lock.release()

    def _choose(self,name):
        import webview
        name=Path(name).name
        extension=Path(name).suffix.lower()
        filters={'.jpg':'JPEG (*.jpg;*.jpeg)', '.png':'PNG (*.png)', '.json':'项目 (*.json)',
                 '.zip':'ZIP (*.zip)', '.csv':'CSV (*.csv)', '.svg':'SVG (*.svg)'}
        if extension not in filters:raise ValueError('不支持的保存格式')
        chosen=self._window.create_file_dialog(webview.FileDialog.SAVE,save_filename=name,
            file_types=(filters[extension],'所有文件 (*.*)'))
        if not chosen:return None
        target=Path(chosen[0] if isinstance(chosen,(list,tuple)) else chosen)
        if not target.suffix:target=target.with_suffix(extension)
        if target.suffix.lower()!=extension and not (extension=='.jpg' and target.suffix.lower()=='.jpeg'):
            raise ValueError(f'请使用{extension}扩展名保存')
        return target

    def _write(self,target,payload):
        if isinstance(payload,str):payload=payload.encode('utf-8')
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.buxu-',suffix='.tmp',delete=False) as f:
                temporary=Path(f.name);f.write(payload);f.flush();os.fsync(f.fileno())
            os.replace(temporary,target);temporary=None
            return {'saved':True,'filename':target.name,'bytes':len(payload)}
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)

    def save_data(self,encoded,name):
        """Save an in-memory project/preview through the OS Save As dialog."""
        if not self._save_lock.acquire(blocking=False):return {'error':'正在保存，请等待完成'}
        try:
            self._check_origin()
            if not isinstance(encoded,str) or len(encoded)>180_000_000:raise ValueError('保存内容超过安全大小')
            target=self._choose(name)
            if target is None:return {'cancelled':True}
            return self._write(target,base64.b64decode(encoded,validate=True))
        except Exception as exc:
            logging.exception('Native save failed');return {'error':str(exc)}
        finally:self._save_lock.release()

    def choose_export(self,name):
        """Choose destination before transferring artwork or doing geometry work."""
        self._check_origin()
        with self._export_mutex:
            if any(j['state'] in ('chosen','running') for j in self._exports.values()):
                return {'error':'已有导出任务正在运行'}
            target=self._choose(name)
            if target is None:return {'cancelled':True}
            key=uuid.uuid4().hex
            self._exports={key:{'target':target,'state':'chosen','percent':0,'message':'等待生成','cancel':threading.Event()}}
        return {'job':key}

    def start_export(self,key,path,body):
        self._check_origin()
        job=self._exports.get(key)
        if not job or job['state']!='chosen':return {'error':'导出任务已失效'}
        if path!='/api/export/jpg':return {'error':'后台生成暂仅用于生产JPG'}
        job['state']='running'
        def run():
            temporary=None
            try:
                from exporting import production_jpg
                def progress(percent,message):
                    if job['cancel'].is_set():raise InterruptedError('已取消生成')
                    if percent is not None:job['percent']=percent;job['message']=message
                progress(1,'正在独立复核排料')
                target=job['target']
                with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.buxu-',suffix='.tmp',delete=False) as out:
                    temporary=Path(out.name)
                    production_jpg(body['project'],progress=progress,output=out)
                    out.flush();os.fsync(out.fileno())
                # Cancel and final replace share a lock: never overwrite after a successful cancel.
                with self._export_mutex:
                    progress(99,'完成保存')
                    os.replace(temporary,target);temporary=None
                    job.update(state='done',percent=100,message='已保存：'+target.name)
            except InterruptedError:job.update(state='cancelled',message='已取消，原文件未更改')
            except Exception as exc:
                logging.exception('Background export failed');job.update(state='error',message=str(exc))
            finally:
                if temporary is not None:temporary.unlink(missing_ok=True)
        threading.Thread(target=run,daemon=True).start()
        return {'started':True}

    def export_status(self,key):
        self._check_origin()
        job=self._exports.get(key)
        if not job:return {'state':'error','message':'导出任务不存在'}
        return {k:job[k] for k in ('state','percent','message')}

    def cancel_export(self,key):
        self._check_origin()
        with self._export_mutex:
            job=self._exports.get(key)
            if job and job['state'] in ('chosen','running'):
                job['cancel'].set()
                if job['state']=='chosen':job.update(state='cancelled',message='已取消')
        return {'cancelled':True}

    def export_file(self,path,body,name):
        """Render directly in Python, avoiding large JPEG copies across JS IPC."""
        if not self._save_lock.acquire(blocking=False):return {'error':'正在生成文件，请等待完成'}
        try:
            self._check_origin()
            from exporting import production_jpg,jpg_zip,production_zip,svg_document,csv_text
            from geometry import validate
            renderers={'/api/export/jpg':production_jpg,'/api/export/svg':svg_document,
                       '/api/export/csv':csv_text,'/api/export/zip':production_zip,
                       '/api/export/jpg-zip':jpg_zip}
            if path not in renderers or not isinstance(body,dict):raise ValueError('不支持的导出请求')
            raw=body.get('project',{})
            if sum(len(p.get('source','')) for p in raw.get('pieces',[]))>100*1024*1024:
                raise ValueError('项目素材超过100MB，请分批导出')
            checked=validate(raw)
            if not checked['valid']:raise ValueError('复核未通过：'+checked['errors'][0]['message'])
            target=self._choose(name)
            if target is None:return {'cancelled':True}
            fn=renderers[path]
            payload=fn(raw,body.get('segmentMm',2000)) if path.endswith(('jpg-zip','/zip')) else fn(raw)
            return self._write(target,payload)
        except Exception as exc:
            logging.exception('Native export failed');return {'error':str(exc)}
        finally:self._save_lock.release()
