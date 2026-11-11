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
VERSION = '1.1.0'
MAX_BYTES = 256 * 1024 * 1024
TTL = 30 * 60
POSTS: dict = {}
JOBS: dict = {}
LOCK = threading.RLock()
DOWNLOAD_SLOTS = threading.BoundedSemaphore(2)
PARSE_SLOTS = threading.BoundedSemaphore(3)
DESKTOP = False
WINDOW = None
WEB_PROCESSING = os.environ.get('XDOWNLOAD_WEB_PROCESSING', 'browser').strip().lower()
if WEB_PROCESSING not in {'browser', 'server'}:
    raise ValueError('XDOWNLOAD_WEB_PROCESSING must be browser or server')
PROXY = os.environ.get('DONGDONG_PROXY', os.environ.get('XDOWNLOAD_PROXY', ''))
FFMPEG = next((str(p) for p in (HOME / 'vendor/ffmpeg.exe', ROOT / 'vendor/ffmpeg.exe') if p.is_file()), shutil.which('ffmpeg'))
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 8192
logging.basicConfig(level=logging.WARNING)


class UserError(Exception):
    pass


def browser_processing():
    return not DESKTOP and WEB_PROCESSING == 'browser'


def get(url, **kwargs):
    if PROXY:
        kwargs['proxies'] = {'http': PROXY, 'https': PROXY}
    return requests.get(url, timeout=(12, 35), headers={'User-Agent': 'Dongdong/' + VERSION}, **kwargs)


def media_url(value):
    try:
        parsed = urlparse(value or '')
        host = parsed.hostname or ''
        allowed = host in {'pbs.twimg.com', 'video.twimg.com'} or re.fullmatch(r'(?:scontent|instagram)[a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:cdninstagram\.com|fbcdn\.net)', host)
        valid = parsed.scheme == 'https' and allowed and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
    except ValueError:
        valid = False
    if not valid:
        raise UserError('invalidLink')
    return value


def post_id(value):
    match = re.search(r'https?://[^\s<>]+', str(value).strip())
    try:
        parsed = urlparse(match.group(0).rstrip('，。！？,') if match else '')
        if parsed.username is not None or parsed.password is not None or parsed.port not in (None, 80, 443):
            raise UserError('invalidLink')
    except ValueError:
        raise UserError('invalidLink') from None
    if parsed.hostname in {'instagram.com', 'www.instagram.com', 'm.instagram.com'}:
        post = re.fullmatch(r'/(p|reel|reels|tv)/([A-Za-z0-9_-]{5,32})/?', parsed.path)
        if not post:
            raise UserError('invalidLink')
        kind = 'reel' if post[1] == 'reels' else post[1]
        return 'IG_' + post[2], f'https://www.instagram.com/{kind}/{post[2]}/'
    if parsed.hostname not in {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com', 'm.twitter.com'}:
        raise UserError('invalidLink')
    status = re.fullmatch(r'/(?:i/web|i|[\w]+)/status/(\d{10,25})(?:/(?:video|photo)/\d+)?/?', parsed.path)
    if not status:
        raise UserError('invalidLink')
    return status.group(1), f'https://x.com/i/status/{status[1]}'


def dimensions(url, width=0, height=0):
    match = re.search(r'/(\d+)x(\d+)/', url)
    return (int(match[1]), int(match[2])) if match else (int(width or 0), int(height or 0))


def photo_original(url):
    parsed = urlparse(media_url(url))
    if parsed.hostname != 'pbs.twimg.com':
        ext = Path(parsed.path).suffix.lstrip('.').lower()
        return url, ext if ext in {'jpg', 'jpeg', 'png', 'webp', 'avif'} else 'jpg'
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


def instagram_error(error):
    detail = str(error).lower()
    if any(term in detail for term in ('429', 'too many requests', 'rate limit', 'please wait a few minutes')):
        return 'instagramRateLimited'
    return 'instagramUnavailable'


def from_instagram(identifier, url):
    """Resolve one public post anonymously; never load browser cookies or a login session."""
    shortcode = identifier[3:]
    media, avatar = [], None
    if '/p/' in url:
        import instaloader
        with instaloader.Instaloader(quiet=True, sleep=False, max_connection_attempts=1,
                                   request_timeout=20, fatal_status_codes=[400, 401, 403, 429],
                                   iphone_support=False) as loader:
            if PROXY:
                loader.context._session.proxies.update({'http': PROXY, 'https': PROXY})
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
            # Use the metadata already fetched for the post. Profile properties can
            # trigger additional profile requests and are deliberately not accessed.
            node = post._node
            owner = {**(node.get('user') or {}), **(node.get('owner') or {})}
            if owner.get('is_private'):
                raise UserError('instagramUnavailable')
            handle = owner.get('username') or ''
            author = owner.get('full_name') or handle
            title = post.caption or ''
            if owner.get('profile_pic_url'):
                try:
                    avatar = media_url(owner['profile_pic_url'])
                except UserError:
                    pass
            nodes = [edge['node'] for edge in node.get('edge_sidecar_to_children', {}).get('edges', [])] if post.typename == 'GraphSidecar' else [node]
            if len(nodes) > 20:
                raise UserError('invalidSelection')
            raw_nodes = node.get('carousel_media') or [node]
            for index, item in enumerate(nodes):
                video = bool(item.get('is_video'))
                preview = media_url(item.get('display_url') or item.get('display_src'))
                source = media_url(item.get('video_url')) if video else preview
                raw = raw_nodes[index] if index < len(raw_nodes) else item
                variants = raw.get('video_versions') if video else (raw.get('image_versions2') or {}).get('candidates')
                dimensions = (variants or [{}])[0] or item.get('dimensions') or {}
                width, height = int(dimensions.get('width') or 0), int(dimensions.get('height') or 0)
                ext = 'mp4' if video else photo_original(source)[1]
                media.append({'kind': 'video' if video else 'photo', 'preview': preview,
                              'has_audio': raw.get('has_audio'),
                              'duration': raw.get('video_duration') or item.get('video_duration') or 0,
                              'formats': [{'url': source, 'ext': ext, 'label': 'original',
                                           'width': width, 'height': height}]})
        source_name = 'Instaloader'
    else:
        import yt_dlp
        options = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'socket_timeout': 15,
                   'retries': 0, 'extractor_retries': 0, 'noplaylist': True, 'cachedir': False}
        if PROXY:
            options['proxy'] = PROXY
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        # Instagram's uploader_id is the numeric account ID, not its username.
        handle = info.get('channel') or ''
        author = info.get('uploader') or handle
        title = info.get('description') or info.get('title') or ''
        for entry in info.get('entries') or [info]:
            if not entry:
                continue
            formats, has_audio = [], None
            # DASH video-only formats must not be offered as ordinary MP4 files.
            # yt-dlp orders formats worst-to-best; keep the best complete MP4.
            for variant in reversed(entry.get('formats') or []):
                if (variant.get('ext') != 'mp4' or variant.get('protocol') != 'https'
                        or variant.get('vcodec') == 'none' or variant.get('fragments')
                        or variant.get('manifest_url') or str(variant.get('format_id', '')).startswith('dash')):
                    continue
                has_audio = False if variant.get('acodec') == 'none' else None
                width, height = int(variant.get('width') or 0), int(variant.get('height') or 0)
                formats.append({'url': media_url(variant['url']), 'ext': 'mp4',
                                'label': f'{min(width, height)}p' if width and height else 'original',
                                'width': width, 'height': height})
                break
            if formats:
                preview = media_url(entry['thumbnail']) if entry.get('thumbnail') else None
                media.append({'kind': 'video', 'duration': entry.get('duration') or 0,
                              'has_audio': has_audio, 'preview': preview, 'formats': formats})
        source_name = 'yt-dlp'
    profile = f'https://www.instagram.com/{handle}/' if re.fullmatch(r'[A-Za-z0-9_.]{1,30}', handle) else ''
    return {'id': identifier, 'platform': 'instagram', 'title': title, 'author': author,
            'handle': handle, 'avatar': avatar, 'profile_url': profile, 'url': url,
            'media': media, 'source': source_name}


def filename_prefix(post):
    return post['id'] if post.get('platform') == 'instagram' else f'X_{post["id"]}'


def public_post(post):
    if browser_processing():
        media = []
        for index, item in enumerate(post['media']):
            preview = media_url(item['preview']) if item.get('preview') else None
            cover = None
            if preview and item['kind'] != 'photo':
                url, ext = photo_original(preview)
                cover = {'url': url, 'ext': ext}
            media.append({
                **{k: v for k, v in item.items() if k not in {'formats', 'preview'}},
                'index': index, 'preview': preview, 'cover': cover,
                'formats': [{**fmt, 'url': media_url(fmt['url'])} for fmt in item['formats']],
            })
        return {
            **{k: v for k, v in post.items() if k not in {'media', 'created', 'avatar'}},
            'avatar': media_url(post['avatar']) if post.get('avatar') else None,
            'media': media,
        }
    return {**{k: v for k, v in post.items() if k not in {'media', 'created', 'avatar'}}, 'avatar': f'/api/avatar/{post["id"]}?token={TOKEN}' if post.get('avatar') else None, 'media': [
        {**{k: v for k, v in item.items() if k not in {'formats', 'preview'}}, 'index': i, 'preview': f'/api/preview/{post["id"]}/{i}?token={TOKEN}' if item['preview'] else None,
         'formats': [{k: v for k, v in fmt.items() if k != 'url'} for fmt in item['formats']]}
        for i, item in enumerate(post['media'])]}


def update_job(job, **values):
    with LOCK:
        job.update(values)
        if job.get('cancelled'):
            job.update(status='cancelled', message='cancelled')


def check_cancelled(job):
    if job.get('cancelled'):
        raise UserError('cancelled')


def retrieve(url, job):
    check_cancelled(job)
    size = 0
    start = time.monotonic()
    with get(media_url(url), stream=True, allow_redirects=False) as response:
        check_cancelled(job)
        response.raise_for_status()
        if response.status_code != 200:
            raise UserError('downloadError')
        total = int(response.headers.get('Content-Length', 0))
        if total > MAX_BYTES:
            raise UserError('sizeError')
        for chunk in response.iter_content(64 * 1024):
            check_cancelled(job)
            size += len(chunk)
            if size > MAX_BYTES or time.monotonic() - start > 600:
                raise UserError('sizeError')
            update_job(job, progress=min(95, round(size / total * 95)) if total else 10)
            yield chunk
    if not size:
        raise UserError('downloadError')


def converted(url, mode, job):
    check_cancelled(job)
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
    stopped = threading.Event()
    def stop_when_cancelled():
        deadline = time.monotonic() + 600
        while not stopped.wait(0.25):
            if job.get('cancelled') or time.monotonic() >= deadline:
                try:
                    process.kill()
                except OSError:
                    pass
                return
    watchdog = threading.Thread(target=stop_when_cancelled, daemon=True)
    watchdog.start()
    try:
        for chunk in iter(lambda: process.stdout.read(64 * 1024), b''):
            check_cancelled(job)
            yield chunk
        process.wait()
        reader.join(timeout=2)
        check_cancelled(job)
        if process.returncode:
            detail = b''.join(errors).decode('utf-8', errors='replace')
            if 'matches no streams' in detail or 'does not contain any stream' in detail:
                raise UserError('noAudio')
            raise UserError('conversionError')
    finally:
        stopped.set()
        watchdog.join(timeout=1)
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
    check_cancelled(job)
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
                check_cancelled(job)
                update_job(job, message='packing', number=number, total=len(selections), progress=0)
                with archive.open(f'{filename_prefix(post)}_{index + 1}.{fmt["ext"]}', 'w', force_zip64=True) as output:
                    with closing(retrieve(fmt['url'], job)) as stream:
                        for chunk in stream:
                            output.write(chunk)
                            yield from sink.drain()
                yield from sink.drain()
        yield from sink.drain()


def stream_job(job):
    with LOCK:
        check_cancelled(job)
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
                check_cancelled(job)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise UserError('sizeError')
                yield chunk
        check_cancelled(job)
        if not size:
            raise UserError('downloadError')
        update_job(job, status='done', progress=100, message='done', size=size, completed=time.time())
    except GeneratorExit:
        update_job(job, status='cancelled' if job.get('cancelled') else 'error', message='cancelled' if job.get('cancelled') else 'downloadError', completed=time.time())
        raise
    except Exception as error:
        message = 'cancelled' if job.get('cancelled') else str(error) if isinstance(error, UserError) else 'downloadError'
        update_job(job, status='cancelled' if message == 'cancelled' else 'error', message=message, completed=time.time())
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
    response.headers['Cache-Control'] = 'public, max-age=86400' if request.endpoint == 'browser_vendor' and response.status_code in (200, 304) else 'no-store'
    media_sources = ' https://video.twimg.com https://pbs.twimg.com https://*.cdninstagram.com https://*.fbcdn.net' if browser_processing() else ''
    playback_sources = media_sources or " 'none'"
    wasm = " 'wasm-unsafe-eval'" if browser_processing() else ''
    response.headers['Content-Security-Policy'] = f"default-src 'self'; script-src 'self' 'unsafe-inline'{wasm}; style-src 'self' 'unsafe-inline'; img-src 'self' data:{media_sources}; media-src{playback_sources}; connect-src 'self'{media_sources}; worker-src 'self' blob:; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
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
    if name not in {'style.css', 'app.js', 'browser-media.js', 'i18n.js', 'brand.svg', 'brand.ico', 'brand.png'}:
        abort(404)
    return send_file(ROOT / 'web' / name)


@app.get('/vendor/<name>')
def browser_vendor(name):
    if name not in {'fflate.min.js', 'ffmpeg.js', '814.ffmpeg.js', 'ffmpeg-core.js', 'ffmpeg-core.wasm', 'LICENSE.fflate', 'LICENSE.ffmpeg', 'LICENSE.ffmpeg-core'}:
        abort(404)
    path = ROOT / 'web/vendor' / name
    if not path.is_file():
        abort(404)
    mimetype = 'application/wasm' if name.endswith('.wasm') else 'text/plain' if name.startswith('LICENSE.') else 'text/javascript'
    return send_file(path, mimetype=mimetype)


@app.get('/api/config')
def config():
    browser = browser_processing()
    conversion = all((ROOT / 'web/vendor' / name).is_file() for name in ('ffmpeg.js', '814.ffmpeg.js', 'ffmpeg-core.js', 'ffmpeg-core.wasm')) if browser else bool(FFMPEG)
    return jsonify(version=VERSION, desktop=DESKTOP, webProcessing='browser' if browser else 'server', conversion=conversion, desktopDownload=desktop_binary().is_file())


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
    identifier, url = post_id(data.get('url', ''))
    with LOCK:
        cached = POSTS.get(identifier)
    if cached and time.time() - cached['created'] < 900:
        return jsonify(public_post(cached))
    if not PARSE_SLOTS.acquire(blocking=False):
        return jsonify(error='busyError'), 429
    try:
        if identifier.startswith('IG_'):
            try:
                post = from_instagram(identifier, url)
            except UserError:
                raise
            except Exception as error:
                message = instagram_error(error)
                result = {'error': message}
                if not app.config.get('REMOTE'):
                    result['diagnostics'] = {'instagram': type(error).__name__ + ': ' + str(error)[:400]}
                return jsonify(result), 429 if message == 'instagramRateLimited' else 400
        else:
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
            post['platform'] = 'x'
            handle = post.get('handle') or ''
            post['profile_url'] = f'https://x.com/{handle}' if re.fullmatch(r'[A-Za-z0-9_]{1,15}', handle) else ''
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
    if browser_processing():
        return jsonify(error='invalidSelection'), 403
    with LOCK:
        post = POSTS.get(identifier)
    if not post or index >= len(post['media']) or not post['media'][index]['preview']:
        abort(404)
    return image_response(post['media'][index]['preview'])


@app.get('/api/avatar/<identifier>')
def author_avatar(identifier):
    if browser_processing():
        return jsonify(error='invalidSelection'), 403
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
    if browser_processing():
        return jsonify(error='invalidSelection'), 403
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'original')
    if mode not in {'original', 'photo', 'mp3', 'gif', 'cover'}:
        raise UserError('invalidSelection')
    with LOCK:
        post = POSTS.get(str(data.get('post', '')))
    if not post or time.time() - post['created'] > TTL:
        raise UserError('expired')
    indices = data.get('indices')
    if not isinstance(indices, list) or not 1 <= len(indices) <= 20 or len(set(map(str, indices))) != len(indices):
        raise UserError('invalidSelection')
    selections = []
    for index in indices:
        if type(index) is not int or not 0 <= index < len(post['media']):
            raise UserError('invalidSelection')
        item = post['media'][index]
        if mode == 'photo' and item['kind'] != 'photo':
            raise UserError('invalidSelection')
        if mode == 'mp3' and (item['kind'] != 'video' or item.get('has_audio') is False):
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
    prefix = filename_prefix(post)
    filename = f'{prefix}_all.zip' if len(selections) > 1 else f'{prefix}_{indices[0] + 1}{"_cover" if mode == "cover" else ""}.{mode if mode in {"mp3", "gif"} else selections[0][2]["ext"]}'
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


@app.post('/api/jobs/<identifier>/cancel')
def cancel_job(identifier):
    if browser_processing():
        return jsonify(error='invalidSelection'), 403
    with LOCK:
        job = JOBS.get(identifier)
        if not job:
            return jsonify(error='expired'), 404
        if job['status'] != 'done':
            update_job(job, cancelled=True, status='cancelled', message='cancelled', completed=time.time())
        return jsonify(cancelled=bool(job.get('cancelled')), status=job['status'])


@app.get('/api/files/<identifier>')
def file_download(identifier):
    if browser_processing():
        return jsonify(error='invalidSelection'), 403
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
            if job.get('cancelled'):
                return {'cancelled': True}
        selected = WINDOW.create_file_dialog(webview.FileDialog.SAVE, save_filename=job['filename'])
        if not selected or job.get('cancelled'):
            update_job(job, cancelled=True, status='cancelled', message='cancelled', completed=time.time())
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
            if job.get('cancelled'):
                update_job(job, status='cancelled', message='cancelled', completed=time.time())
                return {'cancelled': True}
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
    parser = argparse.ArgumentParser(description='Dongdong — free X and Instagram media downloader')
    parser.add_argument('--web', action='store_true', help='Run in the browser instead of a desktop window')
    parser.add_argument('--no-browser', action='store_true', help='Run the web server without opening a browser')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--production', action='store_true', help='Disable local diagnostics behind a reverse proxy')
    parser.add_argument('--port', type=int, default=None)
    parser.add_argument('--proxy', default=PROXY, help='Optional HTTP/HTTPS proxy URL')
    args = parser.parse_args()
    PROXY = args.proxy
    DESKTOP = not (args.web or args.no_browser)
    app.config['REMOTE'] = args.production or args.host not in {'127.0.0.1', 'localhost'}
    if DESKTOP and app.config['REMOTE']:
        parser.error('Desktop mode must use localhost; use --web for server deployment.')
    server = create_server(app, host=args.host, port=args.port if args.port is not None else (0 if DESKTOP else 18765), threads=8, max_request_body_size=8192, outbuf_overflow=sys.maxsize, outbuf_high_watermark=256 * 1024)
    url = f'http://127.0.0.1:{server.effective_port}'
    threading.Thread(target=cleanup_loop, daemon=True).start()
    if DESKTOP:
        threading.Thread(target=server.run, daemon=True).start()
        try:
            import webview
            WINDOW = webview.create_window('东东下载', url, js_api=DesktopAPI(), width=1180, height=850, min_size=(760, 600), background_color='#faf8f4', text_select=True)
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
