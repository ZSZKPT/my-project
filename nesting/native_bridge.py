"""Narrow native save interface, available only to this app's local window."""
import base64
import logging
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlparse


class NativeBridge:
    def __init__(self,origin):
        self._origin=origin
        self._window=None
        self._save_lock=threading.Lock()

    def _check_origin(self):
        current=urlparse(self._window.get_current_url() if self._window else '')
        expected=urlparse(self._origin)
        if (current.scheme,current.netloc)!=(expected.scheme,expected.netloc):
            raise ValueError('保存仅允许从本软件界面发起')

    def info(self):
        self._check_origin()
        return {'embedded':True,'version':'3.0','nativeSave':True}

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
