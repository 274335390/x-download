"""Restore pinned browser runtimes using only Python 3.10+ standard libraries."""

import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / 'build' / 'browser-deps'
OUTPUT = ROOT / 'web' / 'vendor'


def inside(path, directory):
    resolved = path.resolve()
    if not resolved.is_relative_to(directory.resolve()):
        raise ValueError(f'Path outside intended directory: {path.name}')
    return resolved


def sri(path):
    digest = hashlib.sha512()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return 'sha512-' + base64.b64encode(digest.digest()).decode('ascii')


def archive_for(package):
    name = package['name'].replace('@', '').replace('/', '-') + '-' + package['version']
    if not re.fullmatch(r'[A-Za-z0-9._-]+', name):
        raise ValueError('Invalid package name in manifest.')
    archive = inside(CACHE / (name + '.tgz'), CACHE)
    expected = package['integrity']
    if archive.is_file() and sri(archive) == expected:
        return archive
    source = urlsplit(package['url'])
    if source.scheme != 'https' or source.netloc != 'registry.npmjs.org':
        raise ValueError('Browser packages must come from the official npm registry.')
    partial = None
    try:
        digest = hashlib.sha512()
        request = Request(package['url'], headers={'User-Agent': 'Dongdong-vendor-installer'})
        with urlopen(request, timeout=60) as response:
            if urlsplit(response.geturl()).netloc != 'registry.npmjs.org':
                raise ValueError('Unexpected package download redirect.')
            with tempfile.NamedTemporaryFile(dir=CACHE, prefix=name + '-', suffix='.part', delete=False) as stream:
                partial = inside(Path(stream.name), CACHE)
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    digest.update(chunk)
                    stream.write(chunk)
        actual = 'sha512-' + base64.b64encode(digest.digest()).decode('ascii')
        if actual != expected:
            raise ValueError(f'Integrity mismatch for {name}.')
        partial.replace(archive)
        partial = None
        return archive
    finally:
        if partial is not None:
            checked = inside(partial, CACHE)
            if checked.suffix != '.part':
                raise ValueError('Unexpected temporary download path.')
            checked.unlink(missing_ok=True)


def output_file(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9._-]+', name) or name in {'.', '..'}:
        raise ValueError('Invalid output filename in manifest.')
    return inside(OUTPUT / name, OUTPUT)


def main():
    inside(CACHE, ROOT / 'build')
    inside(OUTPUT, ROOT / 'web')
    inside(CACHE, ROOT)
    inside(OUTPUT, ROOT)
    CACHE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'web' / 'vendor-manifest.json').read_text(encoding='utf-8'))
    for package in manifest['packages']:
        archive = archive_for(package)
        with tarfile.open(archive, 'r:gz') as source:
            for member_name, name in package['files'].items():
                member_path = PurePosixPath(member_name)
                if member_path.is_absolute() or '..' in member_path.parts or '\\' in member_name:
                    raise ValueError('Invalid archive member path in manifest.')
                member = source.getmember(member_name)
                if not member.isfile():
                    raise ValueError(f'Archive member is not a regular file: {member_name}')
                # Read only manifest-listed files; never extract archive paths or links.
                with source.extractfile(member) as incoming, output_file(name).open('wb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
        print(f"Installed {package['name']} {package['version']} ({package['license']})", flush=True)
    for license_path, name in manifest['licenses'].items():
        source = inside(ROOT / license_path, ROOT / 'licenses')
        shutil.copyfile(source, output_file(name))
    print('Browser processing dependencies are ready in web/vendor.', flush=True)


if __name__ == '__main__':
    main()
