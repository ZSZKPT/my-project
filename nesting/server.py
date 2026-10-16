#!/usr/bin/env python3
"""Local-only HTTP service. No uploads leave this machine."""
import argparse
import json
import mimetypes
import threading
import time
import uuid
import traceback
import logging
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from assets import import_asset,FragmentedContour
from geometry import validate
from engine import solve
from exporting import production_zip,svg_document,csv_text,production_jpg,jpg_zip

ROOT=Path(__file__).parent
JOBS={};MUTEX=threading.Lock()
MAX_BODY=100*1024*1024

def run_job(job,raw):
    try:
        def update(r):
            with MUTEX:job['result']=r
        r=solve(raw,job['stop'],update)
        with MUTEX:job.update(state='done',result=r)
    except Exception as exc:
        traceback.print_exc()
        with MUTEX:job.update(state='error',error=str(exc))

class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        # Windowed Windows EXEs have no sys.stderr stream.
        logging.getLogger('buxu.http').info(format,*args)
    def send(self,data,status=200,ctype='application/json; charset=utf-8',filename=None):
        if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode() if ctype.startswith('application/json') else data.encode()
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        if filename:self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        if self.headers.get('Host','') not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
            return self.send({'error':'Host不允许'},403)
        path=urlparse(self.path).path
        if path=='/api/health':return self.send({'ok':True,'app':'nesting','defaultGapMm':3})
        if path.startswith('/api/jobs/'):
            with MUTEX:
                job=JOBS.get(path.rsplit('/',1)[-1]);snapshot={k:v for k,v in job.items() if k!='stop'} if job else None
            return self.send(snapshot or {'error':'任务不存在'},200 if job else 404)
        file={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}.get(path)
        if file:return self.send((ROOT/'web'/file).read_bytes(),ctype=mimetypes.guess_type(file)[0] or 'text/plain')
        if path=='/api/example':return self.send((ROOT/'examples'/'demo.nest.json').read_bytes())
        return self.send({'error':'未找到'},404)

    def do_POST(self):
        try:
            # Reject cross-site writes and DNS rebinding, even though only localhost is bound.
            host=self.headers.get('Host','');origin=self.headers.get('Origin')
            if host not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
                return self.send({'error':'Host不允许'},403)
            if origin and origin not in (f'http://{host}',):return self.send({'error':'跨站操作不允许'},403)
            if not self.headers.get('Content-Type','').startswith('application/json'):return self.send({'error':'需要JSON'},415)
            length=int(self.headers.get('Content-Length','0'))
            if length<1 or length>MAX_BODY:return self.send({'error':'请求为空或超过100MB'},413)
            raw=json.loads(self.rfile.read(length));path=urlparse(self.path).path
            if path=='/api/import':return self.send(import_asset(raw))
            if path=='/api/project/check':
                from geometry import polygon,number,settings
                from exporting import verify_sources
                if raw.get('version')!=1 or raw.get('unit')!='mm' or not isinstance(raw.get('pieces'),list) or len(raw['pieces'])>500:
                    raise ValueError('项目格式无效')
                settings(raw.get('settings',{}));ids=set()
                for p in raw['pieces']:
                    if not isinstance(p.get('id'),str) or not p['id'] or p['id'] in ids:raise ValueError('裁片ID重复或无效')
                    ids.add(p['id'])
                    if p.get('quantity')!=1:raise ValueError('每文件只排一片')
                    number(p.get('width'),'宽度',.01,10000);number(p.get('height'),'高度',.01,100000);polygon(p.get('contours'))
                verify_sources({p['id']:p for p in raw['pieces']})
                if raw.get('placements'):
                    v=validate(raw)
                    if not v['valid']:raise ValueError(v['errors'][0]['message'])
                return self.send({'ok':True})
            if path=='/api/validate':return self.send(validate(raw))
            if path=='/api/solve':
                # Validate synchronously, before allocating a worker.
                from geometry import prepare
                prepare(raw)
                with MUTEX:
                    if any(j['state']=='running' for j in JOBS.values()):raise ValueError('已有优化任务在运行，请先停止或等待完成')
                    for key in list(JOBS):
                        if len(JOBS)>8 and JOBS[key]['state']!='running':JOBS.pop(key)
                    jid=uuid.uuid4().hex;job={'id':jid,'state':'running','result':None,'stop':threading.Event()};JOBS[jid]=job
                threading.Thread(target=run_job,args=(job,raw),daemon=True).start()
                return self.send({'id':jid},202)
            if path.startswith('/api/stop/'):
                with MUTEX:
                    job=JOBS.get(path.rsplit('/',1)[-1])
                    if not job:raise ValueError('任务不存在')
                    job['stop'].set()
                return self.send({'ok':True})
            if path=='/api/export/svg':return self.send(svg_document(raw['project']),ctype='image/svg+xml',filename='layout-1to1.svg')
            if path=='/api/export/jpg':return self.send(production_jpg(raw['project']),ctype='image/jpeg',filename='layout-110dpi.jpg')
            if path=='/api/export/jpg-zip':return self.send(jpg_zip(raw['project'],raw.get('segmentMm',2000)),ctype='application/zip',filename='production-jpg-110dpi.zip')
            if path=='/api/export/csv':
                v=validate(raw['project'])
                if not v['valid']:raise ValueError('校验失败，不能导出')
                return self.send(csv_text(raw['project']),ctype='text/csv; charset=utf-8',filename='positions.csv')
            if path=='/api/export/zip':return self.send(production_zip(raw['project'],raw.get('segmentMm',2000)),ctype='application/zip',filename='production.zip')
            return self.send({'error':'未找到'},404)
        except FragmentedContour as exc:self.send({'error':str(exc),**exc.details},400)
        except (ValueError,TypeError,KeyError,IndexError,OverflowError) as exc:self.send({'error':str(exc)},400)
        except Exception as exc:
            traceback.print_exc();self.send({'error':str(exc)},400)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    print(f'数码印花裁片排料 · 本机端口 {args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
