"""Small image API adapters; credentials stay in memory and response bodies are never logged."""
import base64
import json
import mimetypes
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from io import BytesIO
from pathlib import Path
from PIL import Image
from print_studio.core import MAX_PIXELS, load_image, save_png

DEFAULT_PROMPT = '''根据上传的服装效果图，重建服装上的相似平面纺织印花稿。
尽量保留原图的花型元素、配色、底色、大小比例和密度，不随意改变风格。
去除人物、皮肤、头发、饰品、服装轮廓、背景、文字及水印。
校正透视，消除摄影光影、褶皱和织物纹理；遮挡处用周围同类图案合理补绘。
输出正方形满版循环图案：上下左右边缘对应衔接，边缘被截断的元素在对侧延续。
图案分布自然均匀，无中心主体、边框、明显重复条带或空白。
只输出清晰的平面图案，不输出模特效果图、拼图或标注。'''


class APIError(RuntimeError):
    pass


class APIUncertain(APIError):
    """A submitted request may have been billed; do not auto retry."""


def secure_url(value):
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('API和图片下载地址必须是无内嵌账号密码的 HTTPS 地址')
    if parsed.query or parsed.fragment:
        raise ValueError('地址请不要附带查询参数或密钥；密钥使用单独输入框')
    return value.strip()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward bearer credentials to a redirected host.
        return None


def request(url, data=None, key='', content_type=None):
    url = secure_url(url)
    headers = {'Accept': 'application/json', 'User-Agent': 'FeifanPrintStudio/0.1'}
    if key: headers['Authorization'] = 'Bearer ' + key
    if content_type: headers['Content-Type'] = content_type
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=180) as response:
            payload = response.read(48 * 1024 * 1024 + 1)
            if len(payload) > 48 * 1024 * 1024:
                raise APIUncertain('响应超过48MB；请求可能已计费，未自动重试')
            return payload
    except urllib.error.HTTPError as error:
        status = error.code
        if status in (401, 403): message = '认证或权限不足，请检查本平台的密钥、模型权限和余额'
        elif status == 429: message = '触发限流或额度不足，请检查平台控制台'
        elif status in (400, 404, 405, 422): message = '请求格式、模型或接口路径不匹配，请核对服务商API文档'
        elif status in (301, 302, 303, 307, 308): message = '接口返回重定向；为保护密钥未跟随，请填写最终接口地址'
        else: raise APIUncertain(f'API返回HTTP {status}；可能已计费，未自动重试') from None
        raise APIError(f'HTTP {status}：{message}；未自动重试') from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError):
        raise APIUncertain('连接中断或超时；平台可能已接收并计费，未自动重试，请先核对用量') from None


def multipart(fields, image):
    boundary = 'Feifan' + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                      str(value).encode('utf-8'), b'\r\n'])
    parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="reference.png"\r\nContent-Type: image/png\r\n\r\n'.encode(),
                  image, f'\r\n--{boundary}--\r\n'.encode()])
    return b''.join(parts), 'multipart/form-data; boundary=' + boundary


def reference_bytes(path):
    # EXIF orientation is normalized and metadata removed; only this image is submitted.
    image = load_image(path); image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    out = BytesIO(); image.save(out, 'PNG')
    payload = out.getvalue()
    if len(payload) > 18 * 1024 * 1024: raise ValueError('参考图编码超过18MB，请先缩小图片')
    return payload


def extract_result(response):
    if response.get('error') or response.get('code') and response.get('code') not in ('Success', 'OK'):
        raise APIError('平台返回业务错误，请在平台控制台核对模型与参数；未输出原始响应以避免泄露信息')
    for item in response.get('data', []):
        if isinstance(item, dict):
            if item.get('b64_json'): return 'b64', item['b64_json']
            if item.get('url'): return 'url', item['url']
    for choice in response.get('output', {}).get('choices', []):
        for item in choice.get('message', {}).get('content', []):
            if isinstance(item, dict) and item.get('image'): return 'url', item['image']
    if response.get('output', {}).get('task_id'):
        raise APIUncertain('接口返回异步任务ID；此适配器仅支持同步接口。请在平台查看任务结果，避免重复付费')
    raise APIUncertain('没有识别到图片结果；请求可能已计费，请核对接口响应格式，勿反复重试')


def download_image(url):
    # Signed result URLs may have query strings; never send the API key to them.
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise APIError('结果图片地址不是合法HTTPS地址')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'FeifanPrintStudio/0.1'})
        # Signed hosts can redirect on the same or another HTTPS domain, without authorization.
        class HTTPSOnly(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if urllib.parse.urlsplit(newurl).scheme != 'https':
                    raise APIError('图片下载被重定向到非HTTPS地址')
                return super().redirect_request(req, fp, code, msg, headers, newurl)
        with urllib.request.build_opener(HTTPSOnly()).open(req, timeout=90) as result:
            data = result.read(48 * 1024 * 1024 + 1)
        if len(data) > 48 * 1024 * 1024: raise APIError('结果图片超过48MB')
        return data
    except (urllib.error.URLError, OSError):
        raise APIError('已生成图片，但下载失败；结果地址已保存在任务目录，可重新下载，无需再次生成') from None


def write_result(data, target):
    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > MAX_PIXELS: raise APIError('结果图片超过3600万像素')
            image = source.convert('RGB'); image.load()
    except APIError: raise
    except Exception: raise APIError('API返回的内容不是可读取的图片，请核对接口') from None
    save_png(image, target)


def generate(source, target, config, key, stop=None, before_submit=None):
    """One paid submission at most. Durable response enables download-only recovery."""
    target = Path(target)
    response_path = target.with_suffix('.response.json')
    request_path = target.with_suffix('.request.json')
    from print_studio.core import atomic_json
    if response_path.exists():
        try: response = json.loads(response_path.read_text(encoding='utf-8'))
        except (ValueError, OSError): raise APIUncertain('已保存响应无法读取，请检查任务目录，不会自动重新计费') from None
    else:
        if request_path.exists():
            raise APIUncertain('上次请求没有保存结果，可能已计费。请先在平台核对；使用“允许重试未返回请求”后才能重新提交')
        if not key: raise ValueError('请在API设置中填写本次使用的密钥')
        endpoint = secure_url(config['endpoint'])
        model = config.get('model', '').strip()
        if not model: raise ValueError('请填写服务商实际支持的图像模型ID')
        prompt = config.get('prompt', '').strip()
        if not prompt: raise ValueError('请填写花型还原提示词')
        size = config.get('size', '1024x1024')
        image = reference_bytes(source)
        protocol = config.get('protocol', 'openai_edit')
        if protocol == 'openai_edit':
            body, content_type = multipart({'model': model, 'prompt': prompt, 'n': 1, 'size': size}, image)
        elif protocol == 'dashscope':
            payload = {'model': model, 'input': {'messages': [{'role': 'user', 'content': [
                {'image': 'data:image/png;base64,' + base64.b64encode(image).decode()}, {'text': prompt}]}]},
                'parameters': {'n': 1, 'size': size.replace('x', '*'), 'watermark': False}}
            body, content_type = json.dumps(payload).encode(), 'application/json'
        else: raise ValueError('不支持的API协议')
        if stop and stop.is_set(): raise InterruptedError('任务已暂停')
        if before_submit: before_submit()
        atomic_json(request_path, {'submitted_at': time.time(), 'model': model,
                                   'note': '请求可能已计费，不自动重发；无API密钥'})
        try:
            raw = request(endpoint, body, key, content_type)
            response = json.loads(raw)
        except APIError as error:
            # Known HTTP 4xx rejection is safe to let user retry after correction.
            if not isinstance(error, APIUncertain): request_path.unlink(missing_ok=True)
            raise
        except (ValueError, UnicodeError):
            raise APIUncertain('响应不是JSON；可能已计费，请核对平台，未自动重试') from None
        atomic_json(response_path, response)
    kind, result = extract_result(response)
    if kind == 'b64':
        try: data = base64.b64decode(result, validate=True)
        except (ValueError, TypeError): raise APIError('返回图片编码无效') from None
    elif result.startswith('data:image/'):
        try: data = base64.b64decode(result.split(',', 1)[1], validate=True)
        except (ValueError, IndexError): raise APIError('返回图片编码无效') from None
    else: data = download_image(result)
    write_result(data, target)
    return target
