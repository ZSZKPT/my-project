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
    elif rule not in ('exact','style-prefix'):raise ValueError('不支持的文件名匹配规则')
    return stem.rstrip(' _-')


def strip_key(name):
    path=PurePosixPath(name.replace('\\','/'))
    if path.suffix.casefold() not in IMAGE_EXTENSIONS:return None
    stem=normalized(path.stem)
    if not stem.endswith('包边条'):return None
    return stem[:-3].rstrip(' _-')


def match_files(requests,files,rule='style-prefix'):
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
        if rule=='style-prefix':
            candidates=[entry for base,entries in by_key.items()
                        if key==base or (base and key.startswith(base) and key[len(base):len(base)+1] in ('-','_',' '))
                        for entry in entries]
        else:candidates=by_key.get(key,[])
        item={'id':ident,'filename':name,'key':key}
        if len(candidates)==1:matches.append({**item,'file':candidates[0]})
        elif not candidates:missing.append(item)
        else:ambiguous.append({**item,'candidates':candidates})
    return {'matches':matches,'missing':missing,'ambiguous':ambiguous,'requested':len(requests),'rule':rule}
