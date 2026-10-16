import csv
import io
import json
import math
import html
import zipfile
from datetime import datetime,timezone
from assets import decode_data, safe_svg
from geometry import prepare,validate,rings,number

def path_data(g):
    return ' '.join('M'+' L'.join(f'{x:.6f},{y:.6f}' for x,y in ring)+' Z' for ring in rings(g))

def verify_sources(catalog):
    from PIL import Image
    for p in catalog.values():
        data=p.get('source','');raw=decode_data(data)
        if data.startswith('data:image/svg+xml;'):safe_svg(raw)
        else:
            im=Image.open(io.BytesIO(raw));im.verify()

def svg_document(raw,start=0,length=None,labels=False):
    result=validate(raw)
    if not result['valid']:raise ValueError('导出被阻止：'+result['errors'][0]['message'])
    s,catalog,instances=prepare(raw);verify_sources(catalog)
    length=result['stats']['length'] if length is None else length
    if length<=0:raise ValueError('排料长度为零')
    end=start+length;parts=[];defs=[]
    for i,p in enumerate(result['placements']):
        item=instances[p['key']]
        from geometry import placed
        bounds=placed(item,p).bounds
        if bounds[3]<=start or bounds[1]>=end:continue
        defs.append(f'<clipPath id="c{i}"><path d="{path_data(item["occupied"])}"/></clipPath>')
        transform=f'translate({p["x"]:.9f} {p["y"]:.9f})'
        if p['angle']==180:transform+=f' translate({item["width"]:.9f} {item["height"]:.9f}) rotate(180)'
        source=html.escape(item['source'],quote=True)
        parts.append(f'<g transform="{transform}"><image clip-path="url(#c{i})" width="{item["width"]:.9f}" height="{item["height"]:.9f}" preserveAspectRatio="none" href="{source}"/></g>')
        if labels:
            parts.append(f'<text x="{(bounds[0]+bounds[2])/2:.4f}" y="{(bounds[1]+bounds[3])/2:.4f}" font-size="5" fill="#111">{html.escape(item.get("name",item["id"]))}</text>')
    metadata=html.escape(json.dumps({'unit':'mm','scale':'1:1','segmentStartMm':start,'segmentEndMm':end,'gapMm':s['gap'],'labels':labels},ensure_ascii=False))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{s["width"]:.9f}mm" height="{length:.9f}mm" viewBox="0 {start:.9f} {s["width"]:.9f} {length:.9f}"><metadata>{metadata}</metadata><defs>{"".join(defs)}</defs><g id="artwork">{"".join(parts)}</g></svg>'

def csv_text(raw):
    s,catalog,instances=prepare(raw);out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['实例ID','文件','款号','尺码','X_mm','Y_mm','角度','锁定'])
    def safe(value):
        value=str(value)
        return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value
    for p in raw['placements']:
        item=instances[p['key']]
        writer.writerow([safe(p['key']),safe(item.get('filename',item['name'])),safe(item.get('style','')),safe(item.get('size','')),p['x'],p['y'],p['angle'],p.get('locked',False)])
    return '\ufeff'+out.getvalue()

def production_zip(raw,segment=2000):
    result=validate(raw)
    if not result['valid']:raise ValueError('导出被阻止：'+result['errors'][0]['message'])
    segment=number(segment,'分段长度',100,10000);total=result['stats']['length']
    if math.ceil(total/segment)>500:raise ValueError('超过500段，请增加分段长度或拆分任务')
    _,catalog,instances=prepare(raw)
    estimated=len(json.dumps(raw))
    from geometry import placed
    for p in raw['placements']:
        item=instances[p['key']];bounds=placed(item,p).bounds
        copies=math.ceil(bounds[3]/segment)-math.floor(bounds[1]/segment)
        estimated+=copies*len(item.get('source',''))
    if estimated>256*1024*1024:raise ValueError('分段包预计超过256MB，请加大分段长度或拆分任务')
    out=io.BytesIO();manifest=[]
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for i in range(math.ceil(total/segment)):
            start=i*segment;length=min(segment,total-start);name=f'print-{i+1:03d}.svg'
            z.writestr(name,svg_document(raw,start,length))
            manifest.append({'file':name,'startMm':start,'endMm':start+length,'lengthMm':length,'overlapMm':0})
        z.writestr('positions.csv',csv_text(raw))
        z.writestr('project.nest.json',json.dumps(raw,ensure_ascii=False))
        z.writestr('manifest.json',json.dumps({'unit':'mm','scale':'1:1','segments':manifest,'stats':result['stats']},ensure_ascii=False,indent=2))
        z.writestr('PRINT-README.txt','生产SVG使用毫米尺寸、1:1比例。各段连续无重叠，严格按manifest顺序输出。打印软件必须关闭适应页面/缩放，禁止自动加拼接重叠。请先用100mm校准方块验证尺寸和打印拼接。没有ICC转换或RIP色彩管理；保留嵌入素材字节，实际输出色彩取决于打印软件。SVG按已确认轮廓（含出血）裁剪图像；出血图像内容不会自动生成。标签默认不输出。JPEG背景识别轮廓是候选，确认前请核对所有边缘。')
    return out.getvalue()
