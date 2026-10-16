"""Build a source release without environments, dependencies or personal data."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'output'/'buxu-nesting-v1.zip');args=parser.parse_args()
target=args.output.resolve();target.parent.mkdir(parents=True,exist_ok=True)
files=[]
for p in sorted(ROOT.rglob('*')):
    if not p.is_file() or p.name=='startup.log':continue
    rel=p.relative_to(ROOT)
    if any(part in {'.venv','node_modules','__pycache__','output','.git'} for part in rel.parts) or p.suffix in {'.pyc','.zip'}:continue
    if p.is_symlink():raise ValueError(f'不打包符号链接：{rel}')
    files.append((p,rel))
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
    for p,rel in files:z.write(p,Path('buxu-nesting')/rel)
with zipfile.ZipFile(target) as z:
    if z.testzip() is not None:raise RuntimeError('ZIP完整性检查失败')
digest=hashlib.sha256(target.read_bytes()).hexdigest();target.with_suffix('.zip.sha256').write_text(f'{digest}  {target.name}\n')
print(f'{target}\n{len(files)} files, {target.stat().st_size} bytes\nSHA256 {digest}')
