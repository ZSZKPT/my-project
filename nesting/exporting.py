import csv
import io
import json
import math
import html
import zipfile
from datetime import datetime,timezone
from assets import decode_data, safe_svg
from geometry import prepare,validate,rings,number

def raster_canvas(raw,start=0,length=None,dpi=110):
    from PIL import Image,ImageDraw
    from geometry import placed
    result=validate(raw)
    if not result['valid']:raise ValueError('导出被阻止：'+result['errors'][0]['message'])
    s,catalog,instances=prepare(raw)
    length=result['stats']['length'] if length is None else length
    scale=dpi/25.4;width=max(1,round(s['width']*scale));height=max(1,round(length*scale))
    if width>65000 or height>65000 or width*height>64_000_000:
        raise ValueError('内部渲染分块超限')
    canvas=Image.new('RGB',(width,height),'white')
    for p in result['placements']:
        item=instances[p['key']];g=placed(item,p);a,b,c,d=g.bounds
        if d<=start or b>=start+length:continue
        if item['source'].startswith('data:image/svg+xml;'):
            raise ValueError('生产JPG暂仅支持JPG/PNG素材；SVG请用矢量导出或先转为实际尺寸的JPG')
        with Image.open(io.BytesIO(decode_data(item['source']))) as source:
            image=source.convert('RGBA')
        target=(max(1,round(item['width']*scale)),max(1,round(item['height']*scale)))
        if image.size!=target:image=image.resize(target,Image.Resampling.LANCZOS)
        if p['angle']==180:image=image.transpose(Image.Transpose.ROTATE_180)
        x0=max(0,math.floor(a*scale));y0=max(0,math.floor((b-start)*scale))
        x1=min(width,math.ceil(c*scale));y1=min(height,math.ceil((d-start)*scale))
        if x1<=x0 or y1<=y0:continue
        patch=Image.new('RGB',(x1-x0,y1-y0),'white')
        patch.paste(image,(round(p['x']*scale)-x0,round(p['y']*scale)-round(start*scale)-y0),image)
        mask=Image.new('L',patch.size);draw=ImageDraw.Draw(mask)
        for ring in rings(g):draw.polygon([(round(x*scale)-x0,round(y*scale)-round(start*scale)-y0) for x,y in ring],fill=255)
        canvas.paste(patch,(x0,y0),mask)
    return canvas

def production_jpg(raw,start=0,length=None,dpi=110):
    from PIL import Image
    import mmap
    import shutil
    import tempfile
    result=validate(raw)
    if not result['valid']:raise ValueError('导出被阻止：'+result['errors'][0]['message'])
    s,_,_=prepare(raw);scale=dpi/25.4
    length=result['stats']['length'] if length is None else length
    width=max(1,round(s['width']*scale));height=max(1,round(length*scale))
    if width>65000 or height>65000:
        raise ValueError('超过JPG格式的单边尺寸上限，请使用分段JPG；不会缩小生产尺寸')
    out=io.BytesIO()
    if width*height<=24_000_000:
        image=raster_canvas(raw,start,length,dpi)
        image.save(out,'JPEG',quality=100,subsampling=0,dpi=(dpi,dpi))
        image.close()
    else:
        # JPEG accepts RGBX input directly. Write bounded RGBX strips to a disk
        # file and map it read-only: no giant mutable Pillow image or rescaling.
        required=width*height*4
        if shutil.disk_usage(tempfile.gettempdir()).free<required*1.2+100_000_000:
            raise ValueError('生成长JPG的临时磁盘空间不足，请清理系统临时盘或使用分段JPG')
        rows=max(1,12_000_000//width)
        with tempfile.TemporaryFile() as pixels:
            base_row=round(start*scale)
            for offset in range(0,height,rows):
                count=min(rows,height-offset)
                strip=raster_canvas(raw,(base_row+offset)/scale,count/scale,dpi)
                rgbx=strip.convert('RGBX');pixels.write(rgbx.tobytes());rgbx.close();strip.close()
            pixels.flush()
            with mmap.mmap(pixels.fileno(),0,access=mmap.ACCESS_READ) as mapped:
                image=Image.frombuffer('RGBX',(width,height),mapped,'raw','RGBX',0,1)
                image.save(out,'JPEG',quality=100,subsampling=0,dpi=(dpi,dpi))
                image.close();del image
    return out.getvalue()

def jpg_zip(raw,segment=2000,dpi=110):
    result=validate(raw)
    if not result['valid']:raise ValueError('导出被阻止：'+result['errors'][0]['message'])
    s,_,_=prepare(raw);scale=dpi/25.4;width=max(1,round(s['width']*scale))
    total_pixels=max(1,round(result['stats']['length']*scale))
    requested=max(1,round(number(segment,'分段长度',100,10000)*scale))
    rows=min(requested,max(1,30_000_000//width),65000)
    if math.ceil(total_pixels/rows)>500:raise ValueError('分段超过500张，请拆分任务')
    output=io.BytesIO();manifest=[]
    with zipfile.ZipFile(output,'w',zipfile.ZIP_STORED) as z:
        for i,start_row in enumerate(range(0,total_pixels,rows)):
            count=min(rows,total_pixels-start_row);start=start_row/scale;length=count/scale
            name=f'print-{i+1:03d}-110dpi.jpg'
            z.writestr(name,production_jpg(raw,start,length,dpi))
            manifest.append({'file':name,'dpi':dpi,'pixelWidth':width,'pixelHeight':count,
                'startPixel':start_row,'endPixel':start_row+count,'startMm':start,'endMm':start+length,'overlapPixels':0})
        z.writestr('manifest.json',json.dumps({'dpi':dpi,'unit':'mm','segments':manifest,'stats':result['stats']},ensure_ascii=False,indent=2))
        z.writestr('positions.csv',csv_text(raw))
        z.writestr('PRINT-README.txt','生产JPG：110DPI、白底、质量100、无色度抽样。二维码/连接条/尺码在原图中随片保留；不添加界面辅助标签。按manifest中连续像素顺序拼接，无重叠、无重复行。打印关闭适应纸张与额外缩放；栅格尺寸存在不超过半个像素的取整。先验证实际尺寸、二维码和颜色。浏览器预览不能代替生产校准。')
    return output.getvalue()

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
    writer.writerow(['实例ID','文件','款号','尺码','X_mm','Y_mm','角度','锁定','原文件组','左右片','仅上下错位'])
    def safe(value):
        value=str(value)
        return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value
    for p in raw['placements']:
        item=instances[p['key']]
        writer.writerow([safe(p['key']),safe(item.get('filename',item['name'])),safe(item.get('style','')),safe(item.get('size','')),p['x'],p['y'],p['angle'],p.get('locked',False),safe(item.get('sourceGroup','')),safe(item.get('sourcePart','')),item.get('verticalOnly',False)])
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
        z.writestr('PRINT-README.txt','生产SVG使用毫米尺寸、1:1比例。双片按原始像素及110DPI换算，同组只允许上下错位，整体可0/180度旋转。原图中的二维码、连接条和尺码标签参与占用及净间距检查，并随所属裁片打印；界面辅助标签不输出。各段连续无重叠，严格按manifest顺序输出。打印软件关闭适应页面/缩放及自动拼接重叠。先用100mm校准方块验证尺寸、二维码可读性和拼接。没有ICC转换；保留嵌入素材字节。轮廓识别为自动候选，不会自动补造出血图像。')
    return out.getvalue()
