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
    parser=argparse.ArgumentParser()
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--window-test',action='store_true')
    args=parser.parse_args()
    logfile=configure_logging()
    service=None
    try:
        if args.self_test:
            self_test();logging.info('EXE self-test passed');return 0
        import webview
        from native_bridge import NativeBridge
        from server import Handler
        service=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server_thread=threading.Thread(target=service.serve_forever,daemon=True);server_thread.start()
        url=f'http://127.0.0.1:{service.server_port}'
        bridge=NativeBridge(url)
        webview.settings['ALLOW_DOWNLOADS']=True
        webview.settings['ALLOW_FILE_URLS']=False
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=False
        window=webview.create_window('布序 v6 · 本地排料工作台',url,js_api=bridge,
            width=1440,height=960,min_size=(1000,700),background_color='#f6f5f0')
        bridge._window=window
        state={'passed':False,'error':None}
        def check_window():
            try:
                if not window.events.shown.wait(45):raise RuntimeError('桌面窗口未能显示')
                renderer=getattr(window.gui,'renderer','')
                if sys.platform=='win32' and renderer!='edgechromium':
                    raise RuntimeError('系统缺少Microsoft Edge WebView2运行时。请从微软安装后重新启动：https://go.microsoft.com/fwlink/p/?LinkId=2124703')
                if not args.window_test:return
                if not window.events.loaded.wait(45):raise RuntimeError('软件界面加载超时')
                for _ in range(100):
                    dom=window.evaluate_js("Boolean(document.getElementById('solve') && document.getElementById('exportJpg') && window.pywebview && window.pywebview.api)")
                    if dom:break
                    time.sleep(.2)
                else:raise RuntimeError('内嵌界面或原生保存接口未就绪')
                window.evaluate_js("window.pywebview.api.info().then(info => { window.__buxuNativeInfo = info; })")
                for _ in range(50):
                    if window.evaluate_js("Boolean(window.__buxuNativeInfo && window.__buxuNativeInfo.embedded)"):break
                    time.sleep(.2)
                else:raise RuntimeError('原生文件桥接未响应')
                if window.evaluate_js("document.getElementById('importDpi').value")!='110':raise RuntimeError('默认DPI不正确')
                state['passed']=True
                logging.info('Embedded WebView2 window self-test passed; native bridge ready; 110 DPI')
            except Exception as exc:
                state['error']=str(exc);logging.exception('Embedded window test failed')
            finally:
                if args.window_test or state['error']:
                    try:window.destroy()
                    except Exception:logging.exception('Closing embedded window failed')
        webview.start(check_window,gui='edgechromium',debug=False,private_mode=True,
            storage_path=str(logfile.parent/'webview'))
        if state['error']:raise RuntimeError(state['error'])
        if args.window_test and not state['passed']:raise RuntimeError('内嵌桌面窗口未完成自测')
        return 0
    except Exception as exc:
        logging.exception('Desktop startup failed')
        if not args.self_test and not args.window_test:
            try:
                import tkinter as tk
                from tkinter import messagebox
                root=tk.Tk();root.withdraw();messagebox.showerror('布序启动失败',f'{exc}\n\n日志：{logfile}');root.destroy()
            except Exception:pass
        return 1
    finally:
        if service is not None:service.shutdown();service.server_close()


if __name__=='__main__':sys.exit(main())
