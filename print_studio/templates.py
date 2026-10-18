"""Local ZIP import and reviewable masks for whole-garment repeats.

Raster panel detection is a draft aid for closed outlines on a white sheet,
not a pattern-making or production approval algorithm.
"""
import hashlib
import json
import re
import stat
import uuid
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from print_studio.core import EXTENSIONS, MAX_PIXELS, atomic_json, load_image, number, save_png, sha256


def components(mask, minimum=1, with_seeds=False):
    """Connected run labeling with 8-neighbor connectivity; no OpenCV dependency."""
    mask = mask.convert('L').point(lambda x: 255 if x else 0)
    data = mask.tobytes(); width, height = mask.size
    parent = []; runs = []; previous = []
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for y in range(height):
        current = []; cursor = 0
        for match in re.finditer(b'\xff+', data[y*width:(y+1)*width]):
            left, right = match.span(); label = len(parent); parent.append(label)
            while cursor < len(previous) and previous[cursor][1] < left - 1: cursor += 1
            j = cursor
            while j < len(previous) and previous[j][0] <= right:
                other = previous[j]
                if other[1] >= left: parent[find(label)] = find(other[2])
                j += 1
            runs.append((y, left, right, label)); current.append((left, right, label))
        previous = current
    stats = {}
    for y, left, right, label in runs:
        root = find(label)
        if root not in stats: stats[root] = [left, y, right, y+1, 0, left, y]
        item = stats[root]; item[0] = min(item[0], left); item[1] = min(item[1], y)
        item[2] = max(item[2], right); item[3] = max(item[3], y+1); item[4] += right-left
    keep = {k for k, value in stats.items() if value[4] >= minimum}
    result = Image.new('L', mask.size, 0); draw = ImageDraw.Draw(result)
    for y, left, right, label in runs:
        if find(label) in keep: draw.line((left, y, right-1, y), fill=255)
    boxes = [({'box':stats[k][:4], 'seed':stats[k][5:7]} if with_seeds else stats[k][:4]) for k in sorted(keep, key=lambda k: (stats[k][1], stats[k][0]))]
    return result, boxes


def draft_panels(base, analysis_limit=2800):
    """Fill closed panel outlines and discard small disconnected annotations."""
    view = base.copy(); view.thumbnail((analysis_limit, analysis_limit), Image.Resampling.LANCZOS)
    # White sheet assumption is explicit; non-white borders require manual masks.
    rgb = view.convert('RGB'); minimum = ImageChops.darker(ImageChops.darker(*rgb.split()[:2]), rgb.split()[2])
    barrier = minimum.point(lambda x: 255 if x < 243 else 0)
    flooded = ImageOps.expand(barrier, border=2, fill=0)
    ImageDraw.floodfill(flooded, (0, 0), 128, thresh=0)
    flooded = flooded.crop((2, 2, view.width+2, view.height+2))
    interior = flooded.point(lambda x: 0 if x == 128 else 255)
    area = view.width * view.height
    mask, boxes = components(interior, max(30, round(area * .0009)))
    # Inset retains source outlines. This is approximate until reviewed at full resolution.
    mask = mask.filter(ImageFilter.MinFilter(3))
    mask, regions = components(mask, max(20, round(area * .0005)), with_seeds=True)
    result = mask.resize(base.size, Image.Resampling.NEAREST)
    # Protect red factory marks even when printed inside a piece.
    red, green, blue = base.split()
    red_strong = red.point(lambda x: 255 if x > 140 else 0)
    rg = ImageChops.subtract(red, green).point(lambda x: 255 if x > 55 else 0)
    rb = ImageChops.subtract(red, blue).point(lambda x: 255 if x > 55 else 0)
    marks = ImageChops.multiply(red_strong, ImageChops.multiply(rg, rb)).filter(ImageFilter.MaxFilter(3))
    # Preserve the full annotation boxes, not just red glyph strokes.
    _, annotations = components(marks, minimum=8)
    protected = ImageDraw.Draw(result)
    for b in annotations:
        protected.rectangle((max(0,b[0]-4),max(0,b[1]-4),min(base.width-1,b[2]+4),min(base.height-1,b[3]+4)),fill=0)
    del red, green, blue, red_strong, rg, rb, marks
    result, final_regions = components(result, max(30,round(base.width*base.height*.0005)), with_seeds=True)
    pieces = [{'name':f'裁片{i:02d}',**item,'rotation':0} for i,item in enumerate(final_regions,1)]
    if not result.getbbox() or not pieces: raise ValueError('未找到封闭裁片，请用手绘蒙版，或提供清晰轮廓底版')
    if len(pieces) > 60: raise ValueError('识别区域过多，请提供白底清晰裁片或手绘蒙版')
    return result, pieces


def signature(path, config=None):
    path = Path(path)
    config = config or json.loads(path.read_text(encoding='utf-8'))
    body = {k: v for k, v in config.items() if k not in ('approval', 'name')}
    root = path.parent.resolve()
    for key in ('base', 'mask'):
        file = (root / config[key]).resolve()
        if not file.is_relative_to(root): raise ValueError('模板路径超出目录')
        body[key+'_sha256'] = sha256(file)
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def approve(path):
    path = Path(path); config = json.loads(path.read_text(encoding='utf-8'))
    mask = (path.parent / config['mask']).resolve()
    if not mask.is_relative_to(path.parent.resolve()): raise ValueError('蒙版路径超出模板目录')
    with Image.open(mask) as image:
        if not image.convert('L').getbbox(): raise ValueError('蒙版为空，请先涂抹衣服或裁片区域')
    config['approval'] = signature(path, config); atomic_json(path, config)


def is_reviewed(path, config):
    return not config.get('review_required', False) or config.get('approval') == signature(path, config)


def update(path, **values):
    path = Path(path); config = json.loads(path.read_text(encoding='utf-8'))
    config.update(values); config.pop('approval', None); atomic_json(path, config)


def normalized_name(entry):
    name = entry.filename
    if not entry.flag_bits & 0x800:
        try: name = name.encode('cp437').decode('gb18030')
        except (UnicodeError, LookupError): pass
    name = name.replace('\\', '/')
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or ':' in name or stat.S_ISLNK(entry.external_attr >> 16):
        raise ValueError('ZIP包含不安全的路径或符号链接')
    return p


def import_zip(archive, destination, kind='mockup', stop=None):
    if kind not in ('mockup', 'cutting'): raise ValueError('未知模板类型')
    destination = Path(destination)
    root = destination / ('裁片模板_' if kind == 'cutting' else '效果模板_')
    root = root.with_name(root.name + uuid.uuid4().hex[:8]); root.mkdir(parents=True)
    result = []
    with ZipFile(archive) as zipfile:
        entries = []
        for entry in zipfile.infolist():
            if entry.is_dir(): continue
            name = normalized_name(entry)
            if name.suffix.lower() in EXTENSIONS:
                if entry.file_size > 80 * 1024 * 1024: raise ValueError('ZIP内单张图片不能超过80MB')
                entries.append((entry, name))
        if not entries: raise ValueError('ZIP中没有支持的图片')
        if len(entries) > 100 or sum(e.file_size for e, _ in entries) > 500 * 1024 * 1024:
            raise ValueError('单个模板ZIP最多100张、解压图片合计500MB')
        from io import BytesIO
        for index, (entry, name) in enumerate(entries, 1):
            if stop and stop.is_set(): raise InterruptedError('模板导入已暂停')
            with Image.open(BytesIO(zipfile.read(entry))) as source:
                if source.width * source.height > MAX_PIXELS: raise ValueError('单张模板超过3600万像素')
                dpi = source.info.get('dpi'); base = ImageOps.exif_transpose(source).convert('RGB')
            folder = root / f'{index:02d}'; folder.mkdir()
            save_png(base, folder / 'base.png')
            size_match = re.search(r'(?:^|[-_])(\d*XL|XXXL|XXL|XS|S|M|L)(?=$|[-_])', name.stem, re.I)
            size = size_match.group(1).upper() if size_match else ''
            config = {'name': name.stem, 'mode': 'full_repeat', 'kind': kind, 'base': 'base.png', 'mask': 'mask.png',
                      'source_name': name.name, 'size': size, 'review_required': True,
                      'shade_mode': 'none', 'canvas_width_cm': 65, 'pieces': [],
                      'note': '整件覆盖旧图案；自动蒙版仅为草稿，须核对衣服/裁片范围及方向。'}
            if kind == 'cutting':
                if not dpi or len(dpi) != 2 or not all(36 <= float(v) <= 600 for v in dpi):
                    raise ValueError(f'{name.name} 缺少可信DPI；请先确认工厂分辨率，不会默认改成300DPI')
                dpi = [float(v) for v in dpi]
                if abs(dpi[0]-dpi[1]) > .1: raise ValueError('暂不支持横纵DPI不同的裁片')
                config['source_dpi'] = [float(dpi[0]), float(dpi[1])]
                config['canvas_width_cm'] = base.width / dpi[0] * 2.54
                try: mask, config['pieces'] = draft_panels(base)
                except ValueError:
                    mask = Image.new('L', base.size, 0)
                    config['note'] += ' 自动识别失败，请手绘蒙版。'
            else:
                # Never guess skin/hair/garment segmentation from colors.
                mask = Image.new('L', base.size, 0)
            save_png(mask, folder / 'mask.png')
            atomic_json(folder / 'template.json', config); result.append(folder / 'template.json')
    return result


def overlay(path, limit=(1200, 850)):
    path = Path(path); config = json.loads(path.read_text(encoding='utf-8'))
    base = load_image(path.parent / config['base']); original = base.size
    base.thumbnail(limit)
    with Image.open(path.parent / config['mask']) as mask:
        mask = mask.convert('L').resize(base.size, Image.Resampling.NEAREST)
    tint = Image.blend(base, Image.new('RGB', base.size, '#fb5173'), .5)
    result = Image.composite(tint, base, mask)
    if config.get('kind') == 'cutting':
        draw = ImageDraw.Draw(result)
        for i, piece in enumerate(config.get('pieces', []), 1):
            box = piece['box']; x, y = round(box[0]*base.width/original[0]), round(box[1]*base.height/original[1])
            draw.text((x+3, y+3), f'{i}: {piece.get("rotation",0)}deg', fill='#10b981', stroke_fill='black', stroke_width=1)
    return result


def piece_mask(mask, piece):
    box = piece['box']; crop = mask.crop(box)
    if 'seed' not in piece: return crop
    binary = crop.point(lambda x: 255 if x >= 128 else 0)
    x, y = piece['seed'][0]-box[0], piece['seed'][1]-box[1]
    if not 0 <= x < binary.width or not 0 <= y < binary.height or not binary.getpixel((x,y)):
        raise ValueError('裁片定位点不在蒙版内，请重新编辑蒙版并核对裁片方向')
    ImageDraw.floodfill(binary, (x,y), 128, thresh=0)
    selected = binary.point(lambda v:255 if v==128 else 0).filter(ImageFilter.MaxFilter(3))
    return ImageChops.multiply(crop, selected)
