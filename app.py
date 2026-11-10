"""Dongdong: shared web and Windows desktop application."""
from __future__ import annotations

import argparse
from collections import deque
from contextlib import closing
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from urllib.request import getproxies
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import webbrowser
import zipfile

import requests
from flask import Flask, abort, jsonify, request, send_file
from waitress import create_server

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
HOME = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else ROOT
TOKEN = secrets.token_urlsafe(32)
VERSION = '0.1.1'
MAX_BYTES = 256 * 1024 * 1024
TTL = 30 * 60
POSTS: dict = {}
JOBS: dict = {}
LOCK = threading.RLock()
DOWNLOAD_SLOTS = threading.BoundedSemaphore(2)
PARSE_SLOTS = threading.BoundedSemaphore(3)
DESKTOP = False
WINDOW = None
PROXY = os.environ.get('DONGDONG_PROXY', os.environ.get('XDOWNLOAD_PROXY', ''))
FFMPEG = next((str(p) for p in (HOME / 'vendor/ffmpeg.exe', ROOT / 'vendor/ffmpeg.exe') if p.is_file()), shutil.which('ffmpeg'))
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 8192
logging.basicConfig(level=logging.WARNING)


class UserError(Exception):
    pass


def get(url, **kwargs):
    if PROXY:
        kwargs['proxies'] = {'http': PROXY, 'https': PROXY}
    return requests.get(url, timeout=(12, 35), headers={'User-Agent': 'Dongdong/0.1'}, **kwargs)


def media_url(value):
    parsed = urlparse(value or '')
    if parsed.scheme != 'https' or parsed.hostname not in {'pbs.twimg.com', 'video.twimg.com'} or parsed.port not in (None, 443) or parsed.username:
        raise UserError('invalidLink')
    return value


def post_id(value):
    match = re.search(r'https?://[^\s<>]+', str(value).strip())
    parsed = urlparse(match.group(0) if match else '')
    if parsed.hostname not in {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com', 'm.twitter.com'}:
        raise UserError('invalidLink')
    status = re.fullmatch(r'/(?:i/web|i|[\w]+)/status/(\d{10,25})(?:/(?:video|photo)/\d+)?/?', parsed.path)
    if not status:
        raise UserError('invalidLink')
    return status.group(1)


def dimensions(url, width=0, height=0):
    match = re.search(r'/(\d+)x(\d+)/', url)
    return (int(match[1]), int(match[2])) if match else (int(width or 0), int(height or 0))


def photo_original(url):
    parsed = urlparse(media_url(url))
    query = parse_qs(parsed.query)
    ext = Path(parsed.path).suffix.lstrip('.') or query.get('format', ['jpg'])[0]
    path = re.sub(r'\.(jpg|jpeg|png|webp)$', '', parsed.path)
    return urlunparse(parsed._replace(path=path, query=urlencode({'format': ext, 'name': 'orig'}))), ext


def from_fx(identifier):
    with get(f'https://api.fxtwitter.com/status/{identifier}', allow_redirects=False) as response:
        response.raise_for_status()
        data = response.json()
    if data.get('code') != 200:
        raise UserError('parseError')
    tweet = data.get('tweet') or {}
    media = []
    source = tweet.get('media') or {}
    for item in source.get('all') or [*source.get('photos', []), *source.get('videos', [])]:
        kind = item.get('type', 'photo')
        if kind == 'photo':
            url, ext = photo_original(item['url'])
            formats = [{'url': url, 'label': 'original', 'ext': ext, 'width': item.get('width', 0), 'height': item.get('height', 0)}]
            preview = media_url(item['url'])
        else:
            kind = 'gif' if kind in {'gif', 'animated_gif'} else 'video'
            formats = []
            for variant in item.get('formats') or item.get('variants') or []:
                url = variant.get('url', '')
                if '.mp4' not in url:
                    continue
                width, height = dimensions(url, item.get('width'), item.get('height'))
                quality = min(width, height)
                formats.append({'url': media_url(url), 'label': f'{quality}p' if quality else 'original', 'ext': 'mp4', 'width': width, 'height': height, 'bitrate': variant.get('bitrate', 0)})
            if not formats and '.mp4' in item.get('url', ''):
                width, height = dimensions(item['url'], item.get('width'), item.get('height'))
                formats.append({'url': media_url(item['url']), 'label': f'{min(width, height)}p' if width and height else 'original', 'ext': 'mp4', 'width': width, 'height': height})
            if not formats:
                continue
            formats.sort(key=lambda f: (f.get('height', 0) * f.get('width', 0), f.get('bitrate', 0)), reverse=True)
            formats = list({f['url']: f for f in formats}.values())
            preview = media_url(item['thumbnail_url']) if item.get('thumbnail_url') else None
        media.append({'kind': kind, 'duration': item.get('duration', 0), 'preview': preview, 'formats': formats})
    author = tweet.get('author') or {}
    avatar = None
    try:
        candidate = media_url(author.get('avatar_url'))
        if urlparse(candidate).hostname == 'pbs.twimg.com':
            avatar = candidate
    except (UserError, ValueError):
        pass
    return {'id': identifier, 'title': tweet.get('text') or 'X', 'author': author.get('name', ''), 'handle': author.get('screen_name', ''), 'avatar': avatar, 'url': f'https://x.com/i/status/{identifier}', 'media': media, 'source': 'FxEmbed'}


def from_ytdlp(identifier):
    import yt_dlp
    options = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'socket_timeout': 15, 'retries': 1, 'extractor_retries': 1, 'noplaylist': False}
    if PROXY:
        options['proxy'] = PROXY
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f'https://x.com/i/status/{identifier}', download=False)
    media = []
    for entry in info.get('entries') or [info]:
        if not entry:
            continue
        formats = []
        for variant in entry.get('formats', []):
            url = variant.get('url', '')
            if variant.get('ext') != 'mp4' or '.mp4' not in url or variant.get('vcodec') == 'none':
                continue
            width, height = dimensions(url, variant.get('width'), variant.get('height'))
            formats.append({'url': media_url(url), 'label': f'{min(width, height)}p' if width and height else 'original', 'ext': 'mp4', 'width': width, 'height': height, 'bitrate': variant.get('tbr') or 0})
        formats.sort(key=lambda f: (f['width'] * f['height'], f['bitrate']), reverse=True)
        formats = list({f['url']: f for f in formats}.values())
        if formats:
            is_gif = all('/tweet_video/' in f['url'] for f in formats)
            preview = entry.get('thumbnail')
            media.append({'kind': 'gif' if is_gif else 'video', 'duration': entry.get('duration') or 0, 'preview': media_url(preview) if preview else None, 'formats': formats})
    return {'id': identifier, 'title': info.get('description') or info.get('title') or 'X', 'author': info.get('uploader') or '', 'handle': info.get('uploader_id') or '', 'url': f'https://x.com/i/status/{identifier}', 'media': media, 'source': 'yt-dlp'}


def public_post(post):
    return {**{k: v for k, v in post.items() if k not in {'media', 'created', 'avatar'}}, 'avatar': f'/api/avatar/{post["id"]}?token={TOKEN}' if post.get('avatar') else None, 'media': [
        {**{k: v for k, v in item.items() if k not in {'formats', 'preview'}}, 'index': i, 'preview': f'/api/preview/{post["id"]}/{i}?token={TOKEN}' if item['preview'] else None,
         'formats': [{k: v for k, v in fmt.items() if k != 'url'} for fmt in item['formats']]}
        for i, item in enumerate(post['media'])]}


def update_job(job, **values):
    with LOCK:
        job.update(values)


def retrieve(url, job):
    size = 0
    start = time.monotonic()
    with get(media_url(url), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise UserError('downloadError')
        total = int(response.headers.get('Content-Length', 0))
        if total > MAX_BYTES:
            raise UserError('sizeError')
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_BYTES or time.monotonic() - start > 600:
                raise UserError('sizeError')
            update_job(job, progress=min(95, round(size / total * 95)) if total else 10)
            yield chunk
    if not size:
        raise UserError('downloadError')


def converted(url, mode, job):
    args = [FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-rw_timeout', '30000000']
    proxy = PROXY or getproxies().get('https') or getproxies().get('http')
    if proxy:
        args += ['-http_proxy', proxy]
    args += ['-i', media_url(url)]
    if mode == 'mp3':
        args += ['-map', '0:a:0', '-vn', '-codec:a', 'libmp3lame', '-q:a', '2', '-f', 'mp3']
    else:
        args += ['-t', '120', '-filter_complex', 'fps=12,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer', '-loop', '0', '-f', 'gif']
    update_job(job, message='convertingMp3' if mode == 'mp3' else 'convertingGif', progress=10)
    process = subprocess.Popen([*args, 'pipe:1'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    errors = deque(maxlen=16)
    def read_errors():
        for chunk in iter(lambda: process.stderr.read(1024), b''):
            errors.append(chunk)
    reader = threading.Thread(target=read_errors, daemon=True)
    reader.start()
    timeout = threading.Timer(600, process.kill)
    timeout.start()
    try:
        for chunk in iter(lambda: process.stdout.read(64 * 1024), b''):
            yield chunk
        process.wait()
        reader.join(timeout=2)
        if process.returncode:
            detail = b''.join(errors).decode('utf-8', errors='replace')
            if 'matches no streams' in detail or 'does not contain any stream' in detail:
                raise UserError('noAudio')
            raise UserError('conversionError')
    finally:
        timeout.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        reader.join(timeout=2)
        process.stdout.close()
        process.stderr.close()


class ZipSink(io.RawIOBase):
    def __init__(self):
        self.chunks = deque()
        self.position = 0

    def writable(self):
        return True

    def write(self, chunk):
        self.chunks.append(chunk)
        self.position += len(chunk)
        return len(chunk)

    def tell(self):
        return self.position

    def drain(self):
        while self.chunks:
            yield self.chunks.popleft()


def payload(job):
    selections, mode = job['selections'], job['mode']
    if len(selections) == 1:
        fmt = selections[0][2]
        stream = converted(fmt['url'], mode, job) if mode in {'mp3', 'gif'} else retrieve(fmt['url'], job)
        with closing(stream):
            yield from stream
    else:
        sink = ZipSink()
        with zipfile.ZipFile(sink, 'w', zipfile.ZIP_STORED) as archive:
            for number, (post, item, fmt, index) in enumerate(selections, 1):
                update_job(job, message='packing', number=number, total=len(selections), progress=0)
                with archive.open(f'X_{post["id"]}_{index + 1}.{fmt["ext"]}', 'w', force_zip64=True) as output:
                    with closing(retrieve(fmt['url'], job)) as stream:
                        for chunk in stream:
                            output.write(chunk)
                            yield from sink.drain()
                yield from sink.drain()
        yield from sink.drain()


def stream_job(job):
    with LOCK:
        if job.get('active'):
            raise UserError('busyError')
        if not DOWNLOAD_SLOTS.acquire(blocking=False):
            update_job(job, status='error', message='busyError')
            raise UserError('busyError')
        job['active'] = True
        job.update(status='running', message='connecting', progress=0)
    try:
        size = 0
        with closing(payload(job)) as stream:
            for chunk in stream:
                size += len(chunk)
                if size > MAX_BYTES:
                    raise UserError('sizeError')
                yield chunk
        if not size:
            raise UserError('downloadError')
        update_job(job, status='done', progress=100, message='done', size=size, completed=time.time())
    except GeneratorExit:
        update_job(job, status='error', message='downloadError', completed=time.time())
        raise
    except Exception as error:
        message = str(error) if isinstance(error, UserError) else 'downloadError'
        update_job(job, status='error', message=message, completed=time.time())
        raise UserError(message) from None
    finally:
        update_job(job, active=False)
        DOWNLOAD_SLOTS.release()


@app.before_request
def authorize():
    if request.path.startswith('/api/'):
        token = request.headers.get('X-App-Token') or request.args.get('token', '')
        if not secrets.compare_digest(token, TOKEN):
            abort(403)
    if not app.config.get('REMOTE') and request.host.split(':')[0] not in {'127.0.0.1', 'localhost', '[::1]'}:
        abort(403)


@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
    return response


@app.errorhandler(UserError)
def user_error(error):
    return jsonify(error=str(error)), 400


@app.errorhandler(413)
def large_request(error):
    return jsonify(error='invalidLink'), 413


@app.get('/')
def index():
    return (ROOT / 'web/index.html').read_text(encoding='utf-8').replace('__APP_TOKEN__', TOKEN)


@app.get('/<name>')
def web_asset(name):
    if name not in {'style.css', 'app.js', 'i18n.js', 'brand.svg', 'brand.ico', 'brand.png'}:
        abort(404)
    return send_file(ROOT / 'web' / name)


@app.get('/api/config')
def config():
    return jsonify(version=VERSION, desktop=DESKTOP, conversion=bool(FFMPEG), desktopDownload=desktop_binary().is_file())


def release_version(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(value))
    if not match:
        raise ValueError('Invalid release version')
    return tuple(map(int, match.groups()))


def release_url(value):
    parsed = urlparse(str(value))
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Invalid release URL')
    return str(value)


def release_json(url):
    with get(release_url(url), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(16384):
            data.extend(chunk)
            if len(data) > 1024 * 1024:
                raise ValueError('Release response too large')
        return json.loads(data)


@app.post('/api/check-update')
def check_update():
    if not DESKTOP:
        abort(404)
    try:
        settings_file = HOME / 'updates.json'
        if not settings_file.is_file():
            settings_file = ROOT / 'updates.json'
        settings = json.loads(settings_file.read_text(encoding='utf-8-sig'))
        manifest = str(settings.get('manifest_url', '')).strip()
        repository = str(settings.get('github_repo', '')).strip()
        prefix = str(settings.get('tag_prefix', 'v'))
        if not manifest and not repository:
            return jsonify(status='updateNotConfigured')
        release = None
        if manifest:
            try:
                payload = release_json(manifest)
                release = (release_version(payload['version']), release_url(payload['url']))
            except Exception:
                if not repository:
                    raise
        if release is None and repository:
            if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
                raise ValueError('Invalid release repository')
            releases = release_json(f'https://api.github.com/repos/{repository}/releases?per_page=100')
            candidates = []
            for item in releases:
                tag = item.get('tag_name', '')
                if item.get('draft') or item.get('prerelease') or not tag.startswith(prefix):
                    continue
                if not any(asset.get('name') in {'Dongdong.exe', 'Dongdong-Windows.zip'} for asset in item.get('assets', [])):
                    continue
                try:
                    candidates.append((release_version(tag[len(prefix):]), release_url(item['html_url'])))
                except (ValueError, KeyError):
                    continue
            if not candidates:
                return jsonify(status='noRelease')
            release = max(candidates, key=lambda item: item[0])
        version, url = release
        available = version > release_version(VERSION)
        return jsonify(status='updateAvailable' if available else 'noUpdate', version='.'.join(map(str, version)), url=url if available else '')
    except Exception as error:
        if not app.config.get('REMOTE'):
            return jsonify(error='updateError', diagnostics={'update': str(error)[:700]}), 502
        raise UserError('updateError')


def desktop_binary():
    return Path(sys.executable) if getattr(sys, 'frozen', False) else HOME / 'release/current/Dongdong.exe'


@app.get('/download/windows')
def windows_download():
    binary = desktop_binary()
    if not binary.is_file():
        abort(404)
    return send_file(binary, as_attachment=True, download_name='Dongdong.exe')


@app.post('/api/parse')
def parse():
    data = request.get_json(silent=True) or {}
    identifier = post_id(data.get('url', ''))
    with LOCK:
        cached = POSTS.get(identifier)
    if cached and time.time() - cached['created'] < 900:
        return jsonify(public_post(cached))
    if not PARSE_SLOTS.acquire(blocking=False):
        return jsonify(error='busyError'), 429
    try:
        try:
            post = from_fx(identifier)
        except Exception as primary_error:
            try:
                post = from_ytdlp(identifier)
            except Exception as fallback_error:
                result = {'error': 'parseError'}
                if not app.config.get('REMOTE'):
                    result['diagnostics'] = {'primary': str(primary_error)[:700], 'fallback': str(fallback_error)[:700]}
                return jsonify(result), 400
        if not post['media']:
            raise UserError('noMedia')
        post['created'] = time.time()
        with LOCK:
            if len(POSTS) >= 100:
                POSTS.pop(next(iter(POSTS)))
            POSTS[identifier] = post
        return jsonify(public_post(post))
    finally:
        PARSE_SLOTS.release()


@app.get('/api/preview/<identifier>/<int:index>')
def preview(identifier, index):
    with LOCK:
        post = POSTS.get(identifier)
    if not post or index >= len(post['media']) or not post['media'][index]['preview']:
        abort(404)
    return image_response(post['media'][index]['preview'])


@app.get('/api/avatar/<identifier>')
def author_avatar(identifier):
    with LOCK:
        post = POSTS.get(identifier)
    if not post or not post.get('avatar'):
        abort(404)
    return image_response(post['avatar'])


def image_response(url):
    try:
        with get(media_url(url), stream=True, allow_redirects=False) as upstream:
            upstream.raise_for_status()
            content = upstream.raw.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024 or not upstream.headers.get('Content-Type', '').startswith('image/'):
                abort(502)
            return app.response_class(content, mimetype=upstream.headers['Content-Type'])
    except requests.RequestException:
        abort(502)


@app.post('/api/jobs')
def create_job():
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'original')
    if mode not in {'original', 'photo', 'mp3', 'gif', 'cover'}:
        raise UserError('invalidSelection')
    with LOCK:
        post = POSTS.get(str(data.get('post', '')))
    if not post or time.time() - post['created'] > TTL:
        raise UserError('expired')
    indices = data.get('indices')
    if not isinstance(indices, list) or not 1 <= len(indices) <= 10 or len(set(map(str, indices))) != len(indices):
        raise UserError('invalidSelection')
    selections = []
    for index in indices:
        if type(index) is not int or not 0 <= index < len(post['media']):
            raise UserError('invalidSelection')
        item = post['media'][index]
        if mode == 'photo' and item['kind'] != 'photo':
            raise UserError('invalidSelection')
        if mode == 'mp3' and item['kind'] != 'video':
            raise UserError('noAudio')
        if mode == 'gif' and item['kind'] != 'gif':
            raise UserError('invalidSelection')
        if mode in {'gif', 'mp3'} and not FFMPEG:
            raise UserError('noFfmpeg')
        selected = data.get('quality', 0) if len(indices) == 1 else 0
        if type(selected) is not int or not 0 <= selected < len(item['formats']):
            raise UserError('invalidSelection')
        fmt = item['formats'][selected]
        if mode == 'cover':
            if not item['preview']:
                raise UserError('invalidSelection')
            cover, ext = photo_original(item['preview'])
            fmt = {'url': cover, 'ext': ext}
        selections.append((post, item, fmt, index))
    if len(selections) > 1 and mode in {'gif', 'mp3', 'cover'}:
        raise UserError('invalidSelection')
    identifier = secrets.token_hex(16)
    filename = f'X_{post["id"]}_all.zip' if len(selections) > 1 else f'X_{post["id"]}_{indices[0] + 1}{"_cover" if mode == "cover" else ""}.{mode if mode in {"mp3", "gif"} else selections[0][2]["ext"]}'
    job = {'id': identifier, 'status': 'ready', 'progress': 0, 'message': 'ready', 'created': time.time(), 'filename': filename, 'selections': selections, 'mode': mode}
    with LOCK:
        if len(JOBS) >= 100:
            for key, existing in list(JOBS.items()):
                if not existing.get('active'):
                    JOBS.pop(key)
                    break
            else:
                raise UserError('busyError')
        JOBS[identifier] = job
    return jsonify(id=identifier, filename=filename)


@app.get('/api/jobs/<identifier>')
def job_status(identifier):
    with LOCK:
        job = JOBS.get(identifier)
        if not job:
            return jsonify(error='expired'), 404
        return jsonify({k: v for k, v in job.items() if k not in {'selections', 'active'}})


@app.get('/api/files/<identifier>')
def file_download(identifier):
    with LOCK:
        job = JOBS.get(identifier)
        if not job:
            abort(404)
    stream = stream_job(job)
    first = next(stream)
    def body():
        try:
            yield first
            yield from stream
        finally:
            stream.close()
    response = app.response_class(body(), mimetype='application/octet-stream')
    response.headers['Content-Disposition'] = f'attachment; filename="{job["filename"]}"'
    response.headers['X-Accel-Buffering'] = 'no'
    response.call_on_close(stream.close)
    return response


class DesktopAPI:
    def save_file(self, identifier):
        import webview
        with LOCK:
            job = JOBS.get(identifier)
            if not job:
                return {'error': 'expired'}
        selected = WINDOW.create_file_dialog(webview.FileDialog.SAVE, save_filename=job['filename'])
        if not selected:
            update_job(job, status='cancelled', message='cancelled', completed=time.time())
            return {'cancelled': True}
        destination = selected[0] if isinstance(selected, (tuple, list)) else selected
        created = False
        try:
            with open(destination, 'xb') as output:
                created = True
                with closing(stream_job(job)) as stream:
                    for chunk in stream:
                        output.write(chunk)
            return {'saved': True, 'name': Path(destination).name}
        except Exception as error:
            if created:
                Path(destination).unlink(missing_ok=True)
            message = str(error) if isinstance(error, UserError) else 'saveError'
            update_job(job, status='error', message=message, completed=time.time())
            return {'error': message}


def cleanup_loop():
    while True:
        time.sleep(60)
        with LOCK:
            for key, job in list(JOBS.items()):
                if not job.get('active') and job.get('completed', job['created']) < time.time() - TTL:
                    JOBS.pop(key, None)
            for key, post in list(POSTS.items()):
                if post['created'] < time.time() - TTL:
                    POSTS.pop(key, None)


def main():
    global DESKTOP, WINDOW, PROXY
    parser = argparse.ArgumentParser(description='Dongdong — free X media downloader')
    parser.add_argument('--web', action='store_true', help='Run in the browser instead of a desktop window')
    parser.add_argument('--no-browser', action='store_true', help='Run the web server without opening a browser')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=None)
    parser.add_argument('--proxy', default=PROXY, help='Optional HTTP/HTTPS proxy URL')
    args = parser.parse_args()
    PROXY = args.proxy
    DESKTOP = not (args.web or args.no_browser)
    app.config['REMOTE'] = args.host not in {'127.0.0.1', 'localhost'}
    if DESKTOP and app.config['REMOTE']:
        parser.error('Desktop mode must use localhost; use --web for server deployment.')
    server = create_server(app, host=args.host, port=args.port if args.port is not None else (0 if DESKTOP else 18765), threads=8, max_request_body_size=8192, outbuf_overflow=sys.maxsize, outbuf_high_watermark=256 * 1024)
    url = f'http://127.0.0.1:{server.effective_port}'
    threading.Thread(target=cleanup_loop, daemon=True).start()
    if DESKTOP:
        threading.Thread(target=server.run, daemon=True).start()
        try:
            import webview
            WINDOW = webview.create_window('东东下载 · Dongdong', url, js_api=DesktopAPI(), width=1180, height=850, min_size=(760, 600), background_color='#faf8f4', text_select=True)
            webview.start(gui='edgechromium', private_mode=True)
        finally:
            server.close()
    else:
        if sys.stdout:
            print(f'Dongdong is ready: {url}', flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.run()
        except KeyboardInterrupt:
            server.close()


if __name__ == '__main__':
    main()
