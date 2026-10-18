"""Install an editable, versioned copy of the bundled case without overwriting edits."""
import json
import shutil
import uuid
from pathlib import Path


def catalog(root):
    root=Path(root).resolve();path=root/'catalog.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    def safe(value):
        file=(root/value).resolve()
        if not file.is_relative_to(root) or not file.is_file():raise ValueError('系统模板目录不完整或路径非法')
        return file
    paths=[safe(value) for value in data['templates']]
    pattern=safe(data['pattern'])
    return data,paths,pattern


def install(source,destination):
    source,destination=Path(source),Path(destination)
    info,_,_=catalog(source)
    if destination.exists():
        installed,_,_=catalog(destination)
        if installed.get('bundle_id')!=info.get('bundle_id'):raise ValueError('目标目录已有其他模板，不会覆盖')
        return destination
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=destination.with_name('.install-'+uuid.uuid4().hex)
    try:
        shutil.copytree(source,staging)
        catalog(staging)
        try:staging.rename(destination)
        except FileExistsError:catalog(destination)
    finally:
        if staging.exists():shutil.rmtree(staging)
    return destination
