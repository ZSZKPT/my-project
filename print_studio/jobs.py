"""Self-contained task snapshots. No input mutation, no automatic paid retries."""
import csv
import json
import re
import shutil
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from print_studio import api
from print_studio.core import EXTENSIONS, atomic_json, load_image, render, settings, sha256, template


@contextmanager
def task_lock(root):
    file = (Path(root) / '.task.lock').open('a+b')
    try:
        file.seek(0, 2)
        if not file.tell(): file.write(b'0'); file.flush()
        file.seek(0)
        try:
            import os
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: raise ValueError('该任务已被其他窗口占用，请先退出其他窗口') from None
        yield
    finally:
        file.close()  # Closing the handle releases the advisory lock on either platform.


def scan(folder):
    root = Path(folder)
    if not root.is_dir(): raise ValueError('请选择图片文件夹')
    files = sorted((p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in EXTENSIONS), key=lambda p: str(p).casefold())
    if len(files) > 1000: raise ValueError('单次最多导入1000张图片，请分批处理')
    return files


class Job:
    def __init__(self, path, emit=None, stop=None):
        self.path = Path(path).resolve(); self.root = self.path.parent
        self.emit = emit or (lambda kind, value: None)
        self.stop = stop or threading.Event()
        self.state = json.loads(self.path.read_text(encoding='utf-8'))
        if self.state.get('app') != 'feifan-print-studio' or self.state.get('version') != 1:
            raise ValueError('这不是飞凡印花设计任务；请勿选择飞凡上架的任务记录')

    def local(self, value):
        result = (self.root / value).resolve()
        if not result.is_relative_to(self.root): raise ValueError('任务记录含有超出任务目录的路径')
        return result

    def save(self): atomic_json(self.path, self.state)

    @classmethod
    def create(cls, files, output, options, template_paths=(), api_config=None, emit=None, stop=None):
        files = list(dict.fromkeys(Path(p).resolve() for p in files))
        if not files: raise ValueError('请先导入印花或效果图')
        if len(files) > 1000: raise ValueError('单次最多1000张图片')
        normalized = settings(options)
        configs = [template(p) for p in template_paths]
        # Validate before making a new task directory.
        for p in files: load_image(p)
        if api_config:
            api.secure_url(api_config['endpoint'])
            if not api_config.get('model', '').strip(): raise ValueError('请填写API模型ID')
            if not api_config.get('prompt', '').strip(): raise ValueError('请填写花型还原提示词')
        root = Path(output) / ('印花任务_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
        root.mkdir(parents=True)
        try:
            (root / 'sources').mkdir(); (root / 'templates').mkdir()
            entries = []
            for i, source in enumerate(files, 1):
                name = re.sub(r'[^\w\-\u4e00-\u9fff]', '_', source.stem)[:60] or '印花'
                slug = f'{i:04d}_{name}'
                dest = root / 'sources' / (slug + source.suffix.lower())
                shutil.copyfile(source, dest)
                entries.append({'id': slug, 'name': source.name, 'source': dest.relative_to(root).as_posix(),
                                'source_sha256': sha256(dest), 'status': 'pending', 'files': {}})
            saved_templates = []
            for i, config in enumerate(configs, 1):
                folder = root / 'templates' / str(i); folder.mkdir()
                for key in ('base', 'mask'): shutil.copyfile(config[key], folder / (key + '.png')) if config[key].suffix.lower() == '.png' else load_image(config[key]).save(folder / (key + '.png'))
                spec = {'name': config['name'], 'mode': 'full_repeat', 'base': 'base.png', 'mask': 'mask.png', 'canvas_width_cm': config['canvas_width_cm']}
                atomic_json(folder / 'template.json', spec)
                saved_templates.append({'path': (folder / 'template.json').relative_to(root).as_posix(),
                                        'base_sha256': sha256(folder / 'base.png'), 'mask_sha256': sha256(folder / 'mask.png'),
                                        'config_sha256': sha256(folder / 'template.json')})
            # Only explicitly allow-listed API fields are persisted, never key or arbitrary headers.
            safe_api = {k: api_config[k] for k in ('protocol', 'endpoint', 'model', 'size', 'prompt') if k in api_config} if api_config else None
            state = {'app': 'feifan-print-studio', 'version': 1, 'status': 'ready', 'settings': normalized,
                     'api': safe_api, 'api_submissions': 0, 'templates': saved_templates, 'items': entries}
            atomic_json(root / '印花任务.json', state)
        except Exception:
            # Keep failed snapshots for review instead of deleting any user-selected path.
            raise
        return cls(root / '印花任务.json', emit, stop)

    def boundary(self):
        if self.stop.is_set(): raise InterruptedError('已暂停，当前任务可继续；已发出的API请求会先保存结果')

    def specs(self):
        result = []
        for item in self.state['templates']:
            spec = template(self.local(item['path']))
            if sha256(spec['base']) != item['base_sha256'] or sha256(spec['mask']) != item['mask_sha256'] or sha256(spec['path']) != item['config_sha256']:
                raise ValueError('任务模板快照已被修改，请恢复原文件；不会使用新模板覆盖旧任务')
            result.append(spec)
        return result

    def permit_uncertain_retries(self):
        with task_lock(self.root):
            self.state = json.loads(self.path.read_text(encoding='utf-8'))
            for item in self.state['items']:
                folder = self.root / item['id']; marker = folder / 'AI花型.request.json'
                if marker.exists() and not (folder / 'AI花型.response.json').exists() and not (folder / 'AI花型.png').exists():
                    marker.rename(marker.with_name('已确认重试_' + uuid.uuid4().hex[:8] + '.json'))

    def run(self, key='', max_new_requests=20):
        if not isinstance(max_new_requests, int) or not 1 <= max_new_requests <= 1000:
            raise ValueError('本次API调用上限需为1至1000的整数')
        with task_lock(self.root):
            self.state = json.loads(self.path.read_text(encoding='utf-8'))
            specs = self.specs(); submitted = 0
            self.state['status'] = 'running'; self.save()
            try:
                for index, item in enumerate(self.state['items']):
                    self.boundary()
                    if item['status'] == 'complete':
                        for name, checksum in item['files'].items():
                            path = self.local(name)
                            if not path.is_file() or sha256(path) != checksum:
                                raise ValueError('已完成文件缺失或修改：' + name + '；请恢复文件，避免覆盖已审核结果')
                        self.emit('log', '复用已完成：' + item['name'])
                        self.emit('progress', (index + 1) / len(self.state['items']) * 100)
                        continue
                    source = self.local(item['source'])
                    if not source.is_file() or sha256(source) != item['source_sha256']:
                        raise ValueError('任务输入快照缺失或被修改：' + item['name'])
                    folder = self.root / item['id']; folder.mkdir(exist_ok=True)
                    tile = source
                    if self.state['api']:
                        tile = folder / 'AI花型.png'
                        if tile.exists():
                            load_image(tile)
                            if item.get('tile_sha256') and sha256(tile) != item['tile_sha256']:
                                raise ValueError('已还原花型被修改，请恢复任务文件')
                        else:
                            def reserve():
                                nonlocal submitted
                                if submitted >= max_new_requests:
                                    raise InterruptedError('已达到本次API调用上限；任务已保存，可核对费用后继续')
                                submitted += 1
                                self.state['api_submissions'] += 1; self.save()
                                self.emit('log', f'提交AI还原：{item["name"]}（本次 {submitted}/{max_new_requests}）')
                            api.generate(source, tile, self.state['api'], key, self.stop, reserve)
                        item['tile_sha256'] = sha256(tile); self.save()
                    self.boundary()
                    outputs = render(tile, folder, self.state['settings'], specs)
                    item['files'] = {p.relative_to(self.root).as_posix(): sha256(p) for p in outputs}
                    item['status'] = 'complete'; self.save()
                    self.emit('image', str(folder / ('套版效果_01.png' if specs else '平铺检查_2x2.png')))
                    self.emit('log', '完成：' + item['name'])
                    self.emit('progress', (index + 1) / len(self.state['items']) * 100)
                self.state['status'] = 'complete'; self.save()
                self.write_manifest(); self.emit('log', '全部完成。请检查平铺接缝、颜色和实际花型比例。')
                return self.root
            except Exception:
                self.state['status'] = 'paused' if self.stop.is_set() else 'interrupted'
                try: self.save()
                except OSError: pass
                raise

    def write_manifest(self):
        target = self.root / '生成清单.csv'; temp = self.root / ('.manifest-' + uuid.uuid4().hex + '.tmp')
        try:
            with temp.open('w', encoding='utf-8-sig', newline='') as file:
                writer = csv.writer(file); writer.writerow(['编号', '原文件名', '状态', '输出目录'])
                for item in self.state['items']:
                    writer.writerow([item['id'], "'" + item['name'] if item['name'].startswith(('=', '+', '-', '@')) else item['name'], item['status'], item['id']])
            import os
            try: os.replace(temp, target)
            except PermissionError:
                target = self.root / ('生成清单_' + uuid.uuid4().hex[:8] + '.csv'); os.replace(temp, target)
        finally: temp.unlink(missing_ok=True)
