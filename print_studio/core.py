"""Deterministic full-repeat rendering. All distances are explicit; no body inference."""
import hashlib
import json
import math
import os
import uuid
import time
from pathlib import Path
from PIL import Image, ImageChops, ImageOps, ImageStat

EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp'}
MAX_PIXELS = 36_000_000


def number(value, label, minimum, maximum):
    try:
        result = float(str(value).strip().replace('，', '.').replace(',', '.'))
    except (ValueError, TypeError):
        raise ValueError(f'{label}必须填写数字') from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f'{label}需在 {minimum} 至 {maximum} 之间')
    return result


def pixels(cm, dpi):
    return max(1, round(cm / 2.54 * dpi))


def settings(values):
    result = {'mode': 'full_repeat'}
    for key, label, low, high in [('width_cm', '画布宽度/cm', 1, 300),
                                  ('height_cm', '画布高度/cm', 1, 300),
                                  ('tile_cm', '图案循环宽度/cm', .2, 200),
                                  ('dpi', 'DPI', 36, 600),
                                  ('offset_x_cm', '水平偏移/cm', -300, 300),
                                  ('offset_y_cm', '垂直偏移/cm', -300, 300)]:
        result[key] = number(values.get(key, 0), label, low, high)
    result['dpi'] = round(result['dpi'])
    result['shade'] = bool(values.get('shade', True))
    w, h = pixels(result['width_cm'], result['dpi']), pixels(result['height_cm'], result['dpi'])
    if w * h > MAX_PIXELS:
        raise ValueError('单张画布超过3600万像素，请降低尺寸或DPI；首版不生成超大排料图')
    return result


def load_image(path):
    with Image.open(path) as image:
        if image.width * image.height > MAX_PIXELS:
            raise ValueError('图片超过3600万像素，请先缩小图片')
        return ImageOps.exif_transpose(image).convert('RGB')


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('w', encoding='utf-8') as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.flush(); os.fsync(file.fileno())
        for attempt in range(4):
            try:
                os.replace(temp, path); break
            except PermissionError:
                if attempt == 3: raise
                time.sleep((.3, .7, 2)[attempt])
    except PermissionError:
        raise PermissionError('任务文件无法写入：' + str(path) + '；请退出其他任务窗口并检查目录写权限') from None
    finally:
        try: temp.unlink(missing_ok=True)
        except OSError: pass


def save_png(image, path, dpi=None):
    path = Path(path)
    temp = path.with_name('.' + uuid.uuid4().hex + '.png')
    try:
        image.save(temp, format='PNG', **({'dpi': (dpi, dpi)} if dpi else {}))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def repeat(tile, size, tile_width, offsets=(0, 0)):
    width, height = map(int, size)
    if width < 1 or height < 1 or width * height > MAX_PIXELS:
        raise ValueError('输出图片尺寸不合法或超过3600万像素')
    tw = max(1, int(tile_width))
    th = max(1, round(tile.height * tw / tile.width))
    if tw * th > MAX_PIXELS:
        raise ValueError('循环单元过大，请调小循环宽度')
    tile = tile.convert('RGB').resize((tw, th), Image.Resampling.LANCZOS)
    x0, y0 = int(offsets[0]) % tw, int(offsets[1]) % th
    # Doubling blocks makes tiny repeats fast without millions of individual pastes.
    block = tile
    while block.width < width + tw:
        new_width = min(block.width * 2, width + tw)
        new = Image.new('RGB', (new_width, block.height))
        new.paste(block, (0, 0)); new.paste(block, (block.width, 0)); block = new
    while block.height < height + th:
        new_height = min(block.height * 2, height + th)
        if new_height * block.width > MAX_PIXELS * 4:
            raise ValueError('循环缓冲区过大，请降低画布或循环单元尺寸')
        new = Image.new('RGB', (block.width, new_height))
        new.paste(block, (0, 0)); new.paste(block, (0, block.height)); block = new
    return block.crop((tw - x0, th - y0, tw - x0 + width, th - y0 + height))


def proof(tile, limit=500):
    tile = tile.copy(); tile.thumbnail((limit, limit), Image.Resampling.LANCZOS)
    return repeat(tile, (tile.width * 2, tile.height * 2), tile.width)


def seam_report(tile):
    # A warning indicator only: neighboring pixels need not be identical in a valid repeat.
    tile = tile.convert('RGB')
    left, right = tile.crop((0, 0, 1, tile.height)), tile.crop((tile.width - 1, 0, tile.width, tile.height))
    top, bottom = tile.crop((0, 0, tile.width, 1)), tile.crop((0, tile.height - 1, tile.width, tile.height))
    vertical = sum(ImageStat.Stat(ImageChops.difference(left, right)).mean) / 3
    horizontal = sum(ImageStat.Stat(ImageChops.difference(top, bottom)).mean) / 3
    return {'left_right_mean_difference': round(vertical, 2),
            'top_bottom_mean_difference': round(horizontal, 2),
            'note': '仅为边缘色差参考，不是无缝合格证明；请查看2×2平铺图。'}


def template(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding='utf-8'))
    if config.get('mode', 'full_repeat') != 'full_repeat':
        raise ValueError('首版只支持 full_repeat 满版循环模板')
    def local(key):
        item = (path.parent / config[key]).resolve()
        if not item.is_relative_to(path.parent) or not item.is_file():
            raise ValueError('模板图片路径不存在或超出模板目录：' + key)
        return item
    base, mask = local('base'), local('mask')
    b = load_image(base)
    with Image.open(mask) as m:
        m = ImageOps.exif_transpose(m)
        if m.size != b.size:
            raise ValueError('蒙版尺寸必须与底图完全相同')
        if 'A' in m.getbands():
            raise ValueError('蒙版请保存为无透明通道的灰度PNG：白色印花，黑色保留')
        if not m.convert('L').getbbox():
            raise ValueError('蒙版全黑，没有可印花区域')
    width_cm = number(config.get('canvas_width_cm', 60), '模板整张底图对应宽度/cm', 1, 500)
    return {'name': str(config.get('name', path.parent.name)), 'path': str(path),
            'base': base, 'mask': mask, 'canvas_width_cm': width_cm}


def mockup(tile, spec, options):
    base = load_image(spec['base'])
    with Image.open(spec['mask']) as source:
        mask = ImageOps.exif_transpose(source).convert('L')
    factor = base.width / spec['canvas_width_cm']
    layer = repeat(tile, base.size, round(options['tile_cm'] * factor),
                   (round(options['offset_x_cm'] * factor), round(options['offset_y_cm'] * factor)))
    if options.get('shade', True):
        luminance = ImageOps.grayscale(base).point(lambda x: max(75, x))
        layer = ImageChops.multiply(layer, Image.merge('RGB', (luminance,) * 3))
    return Image.composite(layer, base, mask)


def render(tile_path, output, options, templates=()):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    tile = load_image(tile_path)
    save_png(tile, output / '花型单元.png')
    save_png(proof(tile), output / '平铺检查_2x2.png')
    flat = repeat(tile, (pixels(options['width_cm'], options['dpi']), pixels(options['height_cm'], options['dpi'])),
                  pixels(options['tile_cm'], options['dpi']),
                  (pixels(abs(options['offset_x_cm']), options['dpi']) * (-1 if options['offset_x_cm'] < 0 else 1) if options['offset_x_cm'] else 0,
                   pixels(abs(options['offset_y_cm']), options['dpi']) * (-1 if options['offset_y_cm'] < 0 else 1) if options['offset_y_cm'] else 0))
    save_png(flat, output / '满版印花画布.png', options['dpi'])
    flat.close()
    for index, spec in enumerate(templates, 1):
        result = mockup(tile, spec, options)
        save_png(result, output / f'套版效果_{index:02d}.png')
        result.close()
    report = {'settings': options, 'seams': seam_report(tile),
              'templates': [s['name'] for s in templates],
              'notice': '平面印花画布不包含工厂版型、放码、缝份或色彩校准；请审核花型并打样。'}
    atomic_json(output / '生成参数.json', report)
    return sorted(output.glob('*.png')) + [output / '生成参数.json']
