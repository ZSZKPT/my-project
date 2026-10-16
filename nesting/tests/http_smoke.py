"""Run with a service already listening. Non-destructive synthetic requests."""
import json
import os
from urllib.request import Request,urlopen
from urllib.error import HTTPError
BASE=os.environ.get('NESTING_URL','http://127.0.0.1:8765')

def request(path,body=None,headers=None):
    req=Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json',**(headers or {})})
    try:
        with urlopen(req,timeout=10) as r:return r.status,r.read()
    except HTTPError as e:return e.code,e.read()

assert json.loads(request('/api/health')[1])['defaultGapMm']==3
assert request('/api/health',headers={'Host':'evil.example'})[0]==403
assert request('/api/solve',{}, {'Origin':'https://evil.example'})[0]==403
assert request('/api/import',{'data':'data:image/svg+xml;base64,PHN2Zz48c2NyaXB0Lz48L3N2Zz4='})[0]==400
assert request('/api/solve',{'pieces':[]})[0]==400
print('HTTP smoke passed: health, default 3mm gap, Host/Origin enforcement, unsafe SVG and empty-task rejection.')
