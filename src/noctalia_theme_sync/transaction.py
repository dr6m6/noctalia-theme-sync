"""Durable transaction journal; backups are private, local and never deleted."""
import base64
import copy
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path

from . import xdg


def encode(data):
    return base64.b64encode(data).decode() if data is not None else None


def decode(data):
    return base64.b64decode(data, validate=True) if data is not None else None


def manifest_path():
    return xdg.state() / 'installation.json'


def load():
    data = xdg.read(manifest_path())
    if data is None:
        return {'version': 1, 'adapters': [], 'files': {}, 'consume_existing': False, 'bridge': False}
    m = json.loads(data)
    if m.get('version') != 1 or not isinstance(m.get('files'), dict):
        raise ValueError('unsupported installation manifest')
    return m


@contextmanager
def locked():
    root = xdg.state()
    xdg.safe(root / '.lock')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / '.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if xdg.read(root / 'pending.json') is not None:
            raise ValueError('interrupted transaction: run rollback --recover')
        yield


def check(m, path):
    path = str(path)
    current = xdg.read(path)
    entry = m['files'].get(path)
    if entry and xdg.digest(current) != entry['installed_sha256']:
        if entry.get('kind') == 'codex-theme' and path == str(xdg.codex_home() / 'config.toml'):
            from .native import codex_selected
            if codex_selected(current):
                return current  # Native app/user edits to unrelated settings are retained.
        raise ValueError('user-modified managed file; preserve or reconcile it first: ' + path)
    return current


def commit(m, changes, registrations=None, modes=None, forget=()):
    """Preflight everything, save journal, write files, then commit ownership."""
    m = copy.deepcopy(m)
    registrations = registrations or {}
    modes = modes or {}
    all_paths = set(changes) | set(registrations)
    snapshots = {}
    for path in sorted(all_paths):
        current = check(m, path)
        mode = Path(path).stat().st_mode & 0o777 if current is not None else 0o600
        snapshots[path] = {'data': encode(current), 'mode': mode}
        if path not in m['files']:
            m['files'][path] = {'original': encode(current), 'original_mode': mode,
                                'installed_sha256': xdg.digest(current), 'kind': registrations.get(path, 'static')}
            if registrations.get(path) == 'codex-theme':
                m['files'][path]['owned_initial'] = encode(changes.get(path, current))
        if path in changes:
            data = changes[path]
            m['files'][path]['installed_sha256'] = xdg.digest(data)
    old_manifest = xdg.read(manifest_path())
    journal = {'before': snapshots, 'after': {p: xdg.digest(changes.get(p, decode(v['data']))) for p, v in snapshots.items()},
               'manifest': encode(old_manifest)}
    pending = xdg.state() / 'pending.json'
    xdg.write(pending, (json.dumps(journal) + '\n').encode())
    try:
        for path, data in changes.items():
            if xdg.digest(xdg.read(path)) != xdg.digest(decode(snapshots[path]['data'])):
                raise ValueError('configuration changed during transaction: ' + path)
            xdg.write(path, data, modes.get(path, snapshots[path]['mode']))
        for path in forget:
            m['files'].pop(path, None)
        xdg.write(manifest_path(), (json.dumps(m, indent=2) + '\n').encode())
    except BaseException:
        recover()
        raise
    xdg.write(pending, None)
    return m


def recover():
    pending = xdg.state() / 'pending.json'
    data = xdg.read(pending)
    if data is None:
        return False
    j = json.loads(data)
    for path, before in j['before'].items():
        current = xdg.digest(xdg.read(path))
        if current not in (xdg.digest(decode(before['data'])), j['after'][path]):
            raise ValueError('recovery stopped to preserve an external edit: ' + path)
    for path, before in j['before'].items():
        xdg.write(path, decode(before['data']), before['mode'])
    xdg.write(manifest_path(), decode(j['manifest']))
    xdg.write(pending, None)
    return True
