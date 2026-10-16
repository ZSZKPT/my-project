"""Exact, reviewable filename matching for corresponding binding-strip images."""
from pathlib import PurePosixPath
import re
import unicodedata

IMAGE_EXTENSIONS={'.jpg','.jpeg','.png'}


def filename_stem(name):
    if not isinstance(name,str) or not name.strip():raise ValueError('缺少图片文件名')
    return PurePosixPath(name.replace('\\','/')).stem


def normalized(text):
    return unicodedata.normalize('NFKC',text).strip().casefold()


def source_key(name,rule='exact'):
    stem=normalized(filename_stem(name))
    if rule=='remove-copy-number':stem=re.sub(r'[-_ ]\d+$','',stem)
    elif rule not in ('exact','style-prefix','style-folder'):raise ValueError('不支持的文件名匹配规则')
    return stem.rstrip(' _-')


def strip_key(name):
    path=PurePosixPath(name.replace('\\','/'))
    if path.suffix.casefold() not in IMAGE_EXTENSIONS:return None
    stem=normalized(path.stem)
    if not stem.endswith('包边条'):return None
    return stem[:-3].rstrip(' _-')


def match_files(requests,files,rule='style-folder'):
    """One match for each original import instance, never each split panel.

    Match only the selected rule and never pick the first ambiguous file. IDs
    are opaque references from the folder chooser, not caller-provided paths.
    """
    if not isinstance(requests,list) or not 1<=len(requests)<=500:raise ValueError('需要1至500个原图文件')
    source_key('check.jpg',rule)
    by_key={}
    for entry in files:
        key=strip_key(entry['name'])
        if key is not None:by_key.setdefault(key,[]).append(entry)
    matches=[];missing=[];ambiguous=[];seen=set()
    for request in requests:
        ident=request.get('id');name=request.get('filename')
        if not isinstance(ident,str) or not ident or ident in seen:raise ValueError('原图组ID为空或重复')
        seen.add(ident);key=source_key(name,rule)
        if rule in ('style-prefix','style-folder'):
            candidates=[entry for base,entries in by_key.items()
                        if key==base or (base and key.startswith(base) and key[len(base):len(base)+1] in ('-','_',' '))
                        for entry in entries
                        if rule!='style-folder' or normalized(entry.get('parentName',''))==base]
        else:candidates=by_key.get(key,[])
        item={'id':ident,'filename':name,'key':key}
        if len(candidates)==1:matches.append({**item,'file':candidates[0]})
        elif not candidates:missing.append(item)
        else:ambiguous.append({**item,'candidates':candidates})
    return {'matches':matches,'missing':missing,'ambiguous':ambiguous,'requested':len(requests),'rule':rule}


def style_code(name):
    """YQ-TJGG-44-L-1 -> YQ-TJGG-44, without conflating 4 and 44."""
    stem=filename_stem(name)
    numbered=re.match(r'^(.+?-\d+)(?:-|$)',stem)
    if numbered:return numbered[1]
    return re.sub(r'[-_ ](?:x{0,4}[sl]|[2-9]xl|m|均码)(?:[-_ ]\d+)?$','',stem,flags=re.I)


def copy_plan(requests,files,rule='style-folder',quantities=None):
    matched=match_files(requests,files,rule)
    if quantities is None:
        if matched['missing'] or matched['ambiguous']:raise ValueError('存在未找到或重名的包边条，请先修正匹配结果')
        return matched['matches']
    if not isinstance(quantities,dict):raise ValueError('包边条数量格式无效')
    groups={}
    for request in requests:
        code=style_code(request['filename']);key=normalized(code)
        groups.setdefault(key,{'style':code,'requests':[]})['requests'].append(request)
    counts={}
    for code,value in quantities.items():
        key=normalized(code)
        if key not in groups or key in counts:raise ValueError('数量包含未知或重复货号')
        if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=1000:raise ValueError('每货号包边条数量应为0至1000的整数')
        counts[key]=value
    by_id={m['id']:m for m in matched['matches']};plan=[]
    for key,group in groups.items():
        members=group['requests'];quantity=counts.get(key,len(members))
        if not quantity:continue
        items=[by_id[r['id']] for r in members if r['id'] in by_id]
        if len(items)!=len(members):raise ValueError(group['style']+'：未找到唯一对应的包边条，请检查款号文件夹')
        if len({m['file']['id'] for m in items})!=1:raise ValueError(group['style']+'：有多个不同包边条，请按货号文件夹匹配')
        if len(plan)+quantity>5000:raise ValueError('单次最多复制5000张包边条，请分批处理')
        for serial in range(1,quantity+1):
            plan.append({**items[(serial-1)%len(items)],'style':group['style'],
                         'outputStem':f"{group['style']}-包边条-{serial:03d}"})
    if not plan:raise ValueError('包边条数量均为0，无需复制')
    if len(plan)>5000:raise ValueError('单次最多复制5000张包边条，请分批处理')
    return plan
