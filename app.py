import json
import mimetypes
import os
import sqlite3
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('TEMU_DATA_DIR', str(ROOT / 'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
IMAGE_ROOT = Path(os.environ.get('TEMU_IMAGE_ROOT', str(DATA / 'images'))).resolve()
IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
DB = DATA / 'temu.sqlite3'
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

with connect() as db:
    db.executescript('''
    CREATE TABLE IF NOT EXISTS print_names (sku TEXT PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS templates (id TEXT PRIMARY KEY, name TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, template_id TEXT NOT NULL REFERENCES templates(id), sku TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', UNIQUE(template_id, sku));
    CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES drafts(id), status TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    ''')

def scan_images():
    groups = {}
    for file in sorted(IMAGE_ROOT.rglob('*')):
        if not file.is_file() or file.suffix.lower() not in EXTENSIONS:
            continue
        try:
            file.resolve().relative_to(IMAGE_ROOT)
        except ValueError:
            continue
        rel = file.relative_to(IMAGE_ROOT)
        sku = rel.parts[0] if len(rel.parts) > 1 else file.stem
        groups.setdefault(sku, []).append(rel.as_posix())
    return [{'sku': sku, 'images': images} for sku, images in groups.items()]

def validate_template(body):
    for key in ('name', 'title', 'category', 'description'):
        if not isinstance(body.get(key), str) or not body[key].strip():
            raise ValueError(f'{key} 不能为空')
    if '{print_name}' not in body['title']:
        raise ValueError('标题必须包含 {print_name}，用于替换印花名称')
    if not isinstance(body.get('source_product_id'), str) or not body['source_product_id'].strip():
        raise ValueError('请填写用于复制的商品编号')
    variants = body.get('variants')
    if not isinstance(variants, list) or not variants:
        raise ValueError('请至少设置一个尺码')
    sizes = set()
    for variant in variants:
        size = str(variant.get('size', '')).strip()
        if not size or size in sizes:
            raise ValueError('尺码不能为空或重复')
        sizes.add(size)
        price = float(variant.get('price', 0))
        stock = variant.get('stock')
        if not (0 < price < 1000000) or type(stock) is not int or stock < 0:
            raise ValueError('价格必须为正数，库存必须为非负整数')

class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/state':
            with connect() as db:
                templates = [dict(row) for row in db.execute('SELECT * FROM templates ORDER BY rowid DESC')]
                drafts = [dict(row) for row in db.execute('SELECT * FROM drafts ORDER BY rowid DESC')]
                names = dict(db.execute('SELECT sku, name FROM print_names').fetchall())
                tasks = [dict(row) for row in db.execute('SELECT * FROM tasks ORDER BY rowid DESC LIMIT 100')]
            for row in templates + drafts:
                row['body'] = json.loads(row['body'])
            return self.send_json({'templates': templates, 'drafts': drafts, 'tasks': tasks, 'images': [dict(item, print_name=names.get(item['sku'], '')) for item in scan_images()], 'integration': 'browser_not_connected', 'image_root': str(IMAGE_ROOT)})
        if path == '/api/export':
            ids = parse_qs(urlparse(self.path).query).get('id', [])
            with connect() as db:
                rows = db.execute('SELECT * FROM drafts').fetchall()
            return self.send_json({'format': 'internal-drafts-v1', 'official_api_payload': False, 'products': [json.loads(r['body']) for r in rows if not ids or r['id'] in ids]})
        if path == '/api/health':
            return self.send_json({'ok': True})
        if path == '/image':
            rel = parse_qs(urlparse(self.path).query).get('path', [''])[0]
            target = (IMAGE_ROOT / rel).resolve()
            try:
                target.relative_to(IMAGE_ROOT)
            except ValueError:
                return self.send_json({'error': '非法路径'}, 403)
            if target.suffix.lower() not in EXTENSIONS:
                return self.send_json({'error': '不支持此图片格式'}, 400)
        else:
            target = ROOT / 'static' / ('index.html' if path == '/' else path.lstrip('/'))
            target = target.resolve()
            try:
                target.relative_to(ROOT / 'static')
            except ValueError:
                return self.send_json({'error': '非法路径'}, 403)
        if not target.is_file():
            return self.send_json({'error': '未找到文件'}, 404)
        raw = target.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 1024 * 1024:
                raise ValueError('请求大小无效')
            body = json.loads(self.rfile.read(length))
            path = urlparse(self.path).path
            if path == '/api/print-names':
                entries = body.get('entries')
                if not isinstance(entries, list) or not entries:
                    raise ValueError('请填写印花名称表格')
                valid = {item['sku'] for item in scan_images()}
                for entry in entries:
                    if entry.get('sku') not in valid or not isinstance(entry.get('name'), str) or not entry['name'].strip():
                        raise ValueError('货号必须存在，印花名称不能为空')
                with connect() as db:
                    for entry in entries:
                        db.execute('INSERT INTO print_names VALUES (?, ?) ON CONFLICT(sku) DO UPDATE SET name=excluded.name', (entry['sku'], entry['name'].strip()))
                return self.send_json({'saved': len(entries)})
            if path == '/api/templates':
                validate_template(body)
                identifier = str(uuid.uuid4())
                with connect() as db:
                    db.execute('INSERT INTO templates VALUES (?, ?, ?)', (identifier, body['name'], json.dumps(body, ensure_ascii=False)))
                return self.send_json({'id': identifier}, 201)
            if path == '/api/generate':
                with connect() as db:
                    template = db.execute('SELECT body FROM templates WHERE id=?', (body.get('template_id'),)).fetchone()
                    if template is None:
                        raise ValueError('请选择有效模板')
                    template = json.loads(template['body'])
                    selected = body.get('skus', [])
                    if not isinstance(selected, list) or not selected:
                        raise ValueError('请选择货号')
                    groups = {item['sku']: item for item in scan_images()}
                    if any(sku not in groups for sku in selected):
                        raise ValueError('图片库已变化，请刷新后重新选择')
                    names = dict(db.execute('SELECT sku, name FROM print_names').fetchall())
                    if any(not names.get(sku) for sku in selected):
                        raise ValueError('所选货号尚未填写印花名称，请先保存名称表格')
                    created = 0
                    for sku in dict.fromkeys(selected):
                        product = dict(template, sku=sku, skc=sku, print_name=names[sku], title=template['title'].replace('{print_name}', names[sku]).replace('{sku}', sku), images=groups[sku]['images'])
                        product['variants'] = [dict(v, seller_sku=f'{sku}-{v["size"]}') for v in template['variants']]
                        cursor = db.execute('INSERT OR IGNORE INTO drafts (id, template_id, sku, body) VALUES (?, ?, ?, ?)', (str(uuid.uuid4()), body['template_id'], sku, json.dumps(product, ensure_ascii=False)))
                        created += cursor.rowcount
                return self.send_json({'created': created, 'skipped': len(set(selected)) - created})
            if path == '/api/submit':
                # Intentionally no guessed endpoints, signatures, or simulated success.
                with connect() as db:
                    draft = db.execute('SELECT id FROM drafts WHERE id=?', (body.get('draft_id'),)).fetchone()
                    if draft is None:
                        raise ValueError('商品草稿不存在')
                    db.execute('INSERT INTO tasks (id, draft_id, status, message) VALUES (?, ?, ?, ?)', (str(uuid.uuid4()), draft['id'], 'blocked', '尚未连接卖家浏览器：需验证复制商品页面、标题、图片与货号字段。未执行复制或发布。'))
                return self.send_json({'error': '网页自动化尚未连接；已记录阻塞任务，未提交商品'}, 409)
            return self.send_json({'error': '未知接口'}, 404)
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            return self.send_json({'error': str(error)}, 400)

class Server(ThreadingHTTPServer):
    allow_reuse_address = True

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    server = Server(('127.0.0.1', port), Handler)
    print(f'Temu workspace listening on port {port}', flush=True)
    server.serve_forever()
