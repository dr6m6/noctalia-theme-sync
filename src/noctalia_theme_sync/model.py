"""Shared v1 contract and atomic IO. No palette generation."""
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime
from pathlib import Path

MAX_JSON = 65536
MAX_WALLPAPER = 64 * 1024 * 1024
ROLES = tuple('''primary on_primary primary_container on_primary_container
secondary on_secondary secondary_container on_secondary_container
tertiary on_tertiary tertiary_container on_tertiary_container
surface on_surface surface_variant on_surface_variant surface_dim surface_bright
surface_container_lowest surface_container_low surface_container surface_container_high
surface_container_highest outline outline_variant error on_error error_container
on_error_container inverse_surface inverse_on_surface inverse_primary background
on_background shadow scrim primary_fixed primary_fixed_dim on_primary_fixed
on_primary_fixed_variant secondary_fixed secondary_fixed_dim on_secondary_fixed
on_secondary_fixed_variant tertiary_fixed tertiary_fixed_dim on_tertiary_fixed
on_tertiary_fixed_variant'''.split())


def paths():
    from .xdg import base
    return base('config') / 'noctalia/theme-sync', base('state') / 'noctalia/theme-sync'


def read_json(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        raise ValueError('JSON exceeds 64 KiB')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError('non-finite JSON number')
    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)


def validate_palette(p):
    if not isinstance(p, dict) or p.get('mode') not in ('dark', 'light'):
        raise ValueError('mode must be dark or light')
    colors = p.get('colors')
    if not isinstance(colors, dict) or not set(ROLES).issubset(colors):
        raise ValueError('missing required Material roles')
    if not all(isinstance(k, str) and re.fullmatch(r'[a-z][a-z0-9_]*', k)
               and isinstance(v, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', v)
               for k, v in colors.items()):
        raise ValueError('colors must be semantic role names and #RRGGBB strings')


def validate(p):
    validate_palette(p)
    if type(p.get('schema_version')) is not int or p['schema_version'] != 1:
        raise ValueError('unsupported schema_version')
    if type(p.get('revision')) is not int or not 1 <= p['revision'] <= 9007199254740991:
        raise ValueError('revision must be a positive JSON-safe integer')
    stamp = p.get('generated_at')
    if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', stamp):
        raise ValueError('generated_at required')
    try:
        date = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError('timezone required')
    except ValueError as exc:
        raise ValueError('generated_at must be a timezone-aware RFC3339 timestamp') from exc
    wallpaper = p.get('wallpaper')
    if not isinstance(wallpaper, str) or '\0' in wallpaper or (wallpaper and not Path(wallpaper).is_absolute()):
        raise ValueError('wallpaper must be an absolute local path or empty string')
    asset = p.get('wallpaper_asset')
    if asset is not None:
        if not isinstance(asset, dict) or not re.fullmatch(r'sha256:[a-f0-9]{64}', str(asset.get('id', ''))):
            raise ValueError('invalid wallpaper_asset.id')
        if asset.get('url') != '/v1/wallpaper/current':
            raise ValueError('invalid wallpaper_asset.url')
        if asset.get('content_type') not in ('image/jpeg', 'image/png', 'image/webp', 'image/gif'):
            raise ValueError('unsupported wallpaper content_type')
        if type(asset.get('size')) is not int or not 0 < asset['size'] <= MAX_WALLPAPER:
            raise ValueError('invalid wallpaper size')
        if not isinstance(asset.get('filename'), str):
            raise ValueError('wallpaper filename required')
    return p


def semantic(p):
    return {'schema_version': 1, 'mode': p['mode'], 'wallpaper': p['wallpaper'],
            'colors': {k: v.lower() for k, v in p['colors'].items()},
            'wallpaper_asset': p.get('wallpaper_asset')}


def atomic_json(path, value):
    path = Path(path)
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError('atomic output must not traverse symlinks')
    if path.exists() and (not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_nlink != 1):
        raise ValueError('atomic output must be an owned regular file')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        dirfd = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def wallpaper_file(path, roots):
    """Open only a regular image inside allowlisted roots; validate the actual FD."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        actual = Path(os.readlink(f'/proc/self/fd/{fd}'))
        allowed = [Path(r).expanduser().resolve() for r in roots]
        if not any(actual.is_relative_to(r) for r in allowed):
            raise ValueError('wallpaper outside allowed roots')
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_WALLPAPER:
            raise ValueError('wallpaper must be a regular file <=64 MiB')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(MAX_WALLPAPER + 1)
        if not 0 < len(data) <= MAX_WALLPAPER:
            raise ValueError('wallpaper size changed')
        if data.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            mime = 'image/webp'
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            mime = 'image/gif'
        else:
            raise ValueError('unsupported wallpaper image')
        asset = {'id': 'sha256:' + hashlib.sha256(data).hexdigest(),
                 'url': '/v1/wallpaper/current', 'filename': Path(path).name,
                 'content_type': mime, 'size': len(data)}
        return asset, data
    finally:
        os.close(fd)


def config(config_path=None):
    confdir, state = paths()
    defaults = {'bind': '127.0.0.1', 'port': 8765, 'trusted_loopback': True,
                'debounce_ms': 250, 'wallpaper_roots': [],
                'token_file': str(state / 'bridge-token')}
    target = Path(config_path or confdir / 'bridge.json')
    if target.exists():
        custom = read_json(target)
        if not isinstance(custom, dict) or set(custom) - set(defaults):
            raise ValueError('unknown bridge configuration keys')
        defaults.update(custom)
    import ipaddress
    ipaddress.ip_address(defaults['bind'])  # numeric addresses only, no DNS rebinding
    if type(defaults['port']) is not int or not 0 <= defaults['port'] <= 65535:
        raise ValueError('invalid port')
    if type(defaults['trusted_loopback']) is not bool:
        raise ValueError('trusted_loopback must be boolean')
    if type(defaults['debounce_ms']) is not int or not 50 <= defaults['debounce_ms'] <= 2000:
        raise ValueError('debounce_ms must be 50..2000')
    if not isinstance(defaults['wallpaper_roots'], list) :
        raise ValueError('wallpaper_roots must be a list')
    for root in defaults['wallpaper_roots']:
        if not isinstance(root, str) or not Path(root).expanduser().is_absolute() or Path(root).expanduser().resolve() == Path('/'):
            raise ValueError('wallpaper_roots must contain specific absolute directories')
    if not isinstance(defaults['token_file'], str) or not Path(defaults['token_file']).expanduser().is_absolute():
        raise ValueError('token_file must be an absolute path')
    return defaults
