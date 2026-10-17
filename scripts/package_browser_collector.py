"""Build a public extension ZIP as part of the existing Pages artifact."""
from pathlib import Path
import hashlib
import json
import zipfile

root=Path(__file__).resolve().parents[1]
source=root/'browser-collector'
files=sorted(p for p in source.iterdir() if p.is_file() and p.suffix in ('.js','.json','.html','.md'))
output=root/'selection'/'FeifanBrowserCollector.zip'
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
    for file in files:
        info=zipfile.ZipInfo(file.name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
        archive.writestr(info,file.read_bytes())
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    manifest=json.loads(archive.read('manifest.json'))
report={'version':manifest['version'],'file':output.name,'bytes':output.stat().st_size,
        'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'files':len(files)}
(output.parent/'collector-build.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
