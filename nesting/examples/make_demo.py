"""Explicitly synthetic test pieces, never customer production data."""
import base64
import json
from pathlib import Path

def create():
    pieces=[]
    shapes=[('前片-A',1000,600,[[0,0],[1000,0],[0,600]]),('前片-B',1000,600,[[0,0],[1000,0],[0,600]]),
            ('后片-A',1000,600,[[0,0],[1000,0],[0,600]]),('后片-B',1000,600,[[0,0],[1000,0],[0,600]])]
    for i,(name,w,h,ring) in enumerate(shapes):
        color=['#b8caa4','#e1b697','#a8c5ba','#dab5b0'][i]
        path='M'+' L'.join(f'{x},{y}' for x,y in ring)+' Z'
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}"><path id="cut" d="{path}" fill="{color}"/><g fill="#fffdf0" opacity="0.65"><circle cx="80" cy="80" r="38"/><circle cx="240" cy="80" r="38"/><circle cx="400" cy="80" r="38"/><circle cx="560" cy="80" r="38"/><circle cx="720" cy="80" r="38"/><circle cx="80" cy="240" r="38"/><circle cx="240" cy="240" r="38"/><circle cx="400" cy="240" r="38"/><circle cx="80" cy="400" r="38"/></g></svg>'
        pieces.append({'id':f'demo{i}','name':name+'（虚构样本）','filename':name+'.svg','style':'DEMO','size':'示例','quantity':1,
          'width':w,'height':h,'contours':[ring],'source':'data:image/svg+xml;base64,'+base64.b64encode(svg.encode()).decode(),
          'confirmed':True,'dimensionConfirmed':True,'allow180':True,'bleed':0,'contourTolerance':0,'contourSource':'已知毫米坐标的虚构三角裁片'})
    return {'version':1,'unit':'mm','settings':{'width':1580,'left':10,'right':10,'gap':3,'head':0,'tail':0,'seconds':15,'iterations':12,'seed':42},'pieces':pieces,'placements':[]}

if __name__=='__main__':
    root=Path(__file__).parent
    project=create();(root/'demo.nest.json').write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
    for p in project['pieces']:(root/p['filename']).write_bytes(base64.b64decode(p['source'].split(',',1)[1]))
