"""PyInstaller entry point: bundled local app, no Python installation required."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time
from http.server import ThreadingHTTPServer
import webbrowser


def configure_logging():
    import tempfile
    folder=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir())) / 'BuxuNesting'
    folder.mkdir(parents=True,exist_ok=True)
    file=folder/'desktop.log'
    handler=RotatingFileHandler(file,maxBytes=2_000_000,backupCount=2,encoding='utf-8')
    logging.basicConfig(level=logging.INFO,handlers=[handler])
    return file


def self_test():
    from assets import import_asset,data_url
    from PIL import Image,ImageDraw
    from geometry import validate
    from engine import solve
    from exporting import svg_document,production_jpg
    import io
    im=Image.new('RGB',(660,420),'white');d=ImageDraw.Draw(im)
    d.rectangle((10,150,190,400),fill='black');d.rectangle((75,10,125,60),outline='black',width=6)
    d.rectangle((90,55,110,155),fill='black');d.rectangle((185,300,225,330),fill='black')
    d.polygon([(300,20),(360,20),(360,90),(560,90),(560,20),(640,20),(640,400),(300,400)],fill='black')
    out=io.BytesIO();im.save(out,'JPEG',quality=98)
    pair=import_asset({'filename':'self-test.jpg','data':data_url(out.getvalue(),'image/jpeg'),'mode':'garment-pair','dpi':110})
    assert len(pair['splitPieces'])==2
    raw={'version':1,'unit':'mm','pieces':pair['splitPieces'],'placements':[],
        'settings':{'width':1580,'left':10,'right':10,'gap':3,'seconds':3,'iterations':2}}
    report=solve(raw,threading.Event());assert report['valid'];raw['placements']=report['placements']
    assert validate(raw)['valid'];assert 'image/jpeg;base64' in svg_document(raw)
    with Image.open(io.BytesIO(production_jpg(raw))) as jpg:assert jpg.info['dpi']==(110,110)
    from server import ROOT,Handler
    assert (ROOT/'web'/'app.js').is_file()
    service=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
    try:
        from urllib.request import urlopen
        base=f'http://127.0.0.1:{service.server_port}'
        with urlopen(base+'/api/health',timeout=5) as r:assert json.load(r)['ok']
        with urlopen(base+'/',timeout=5) as r:assert b'app.js' in r.read()
    finally:service.shutdown();service.server_close();thread.join(timeout=3)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    logfile=configure_logging()
    try:
        if args.self_test:
            self_test();logging.info('EXE self-test passed');return 0
        import tkinter as tk
        from tkinter import ttk,messagebox
        from server import Handler
        # Per-process ephemeral port avoids accidentally opening an older server.
        service=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{service.server_port}'
        root=tk.Tk();root.title('布序 v2 · 压紧回填优化版');root.geometry('440x220');root.resizable(False,False)
        frame=ttk.Frame(root,padding=24);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='布序 v2 · 排料优化版已启动',font=('Microsoft YaHei',15)).pack(anchor='w')
        ttk.Label(frame,text='110 DPI · 左右片只上下错位 · 二维码和标签随片打印').pack(anchor='w',pady=(13,5))
        ttk.Label(frame,text='请保留此窗口。关闭窗口将停止本地应用。').pack(anchor='w',pady=(0,15))
        ttk.Button(frame,text='打开排料界面',command=lambda:webbrowser.open(url)).pack(anchor='w')
        def close():
            service.shutdown();service.server_close();root.destroy()
        root.protocol('WM_DELETE_WINDOW',close)
        root.after(250,lambda:webbrowser.open(url));root.mainloop();thread.join(timeout=3)
        return 0
    except Exception as exc:
        logging.exception('Desktop startup failed')
        if not args.self_test:
            try:
                import tkinter as tk
                from tkinter import messagebox
                root=tk.Tk();root.withdraw();messagebox.showerror('布序启动失败',f'{exc}\n\n日志：{logfile}');root.destroy()
            except Exception:pass
        return 1


if __name__=='__main__':sys.exit(main())
