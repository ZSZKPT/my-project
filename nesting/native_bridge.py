"""Narrow native save interface, available only to this app's local window."""
import base64
import logging
import os
from pathlib import Path
import tempfile
import threading
import uuid
from urllib.parse import urlparse


class NativeBridge:
    def __init__(self,origin):
        self._origin=origin
        self._window=None
        self._save_lock=threading.Lock()
        self._exports={}
        self._export_mutex=threading.Lock()

    def _check_origin(self):
        current=urlparse(self._window.get_current_url() if self._window else '')
        expected=urlparse(self._origin)
        if (current.scheme,current.netloc)!=(expected.scheme,expected.netloc):
            raise ValueError('保存仅允许从本软件界面发起')

    def info(self):
        self._check_origin()
        return {'embedded':True,'version':'6.0','nativeSave':True}

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
