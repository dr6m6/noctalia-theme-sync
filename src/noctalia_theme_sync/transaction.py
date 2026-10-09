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


class Manifest(dict):
    """In-memory read precondition; never serialized into installation state."""

    signature = None


def load():
    data = xdg.read(manifest_path())
    if data is None:
        m = Manifest(version=1, adapters=[], files={}, consume_existing=False, bridge=False)
        m.signature = {'sha256': None, 'mode': None}
        return m
    m = json.loads(data)
    if (not isinstance(m, dict) or m.get('version') != 1 or not isinstance(m.get('files'), dict)
            or not all(isinstance(p, str) and isinstance(e, dict) for p, e in m['files'].items())):
        raise ValueError('unsupported installation manifest')
    m = Manifest(m)
    m.signature = xdg.signature(manifest_path())
    if m.signature['sha256'] != xdg.digest(data):
        raise ValueError('manifest changed while reading')
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
    if entry and entry.get('installed_mode') is not None and current is not None:
        if (Path(path).stat().st_mode & 0o777) != entry['installed_mode']:
            raise ValueError('user-modified managed permissions; preserve or reconcile them first: ' + path)
    if entry and xdg.digest(current) != entry['installed_sha256']:
        if entry.get('kind') == 'codex-theme' and path == str(xdg.codex_home() / 'config.toml'):
            from .native import codex_selected
            if codex_selected(current):
                return current  # Native app/user edits to unrelated settings are retained.
        raise ValueError('user-modified managed file; preserve or reconcile it first: ' + path)
    return current


def commit(m, changes, registrations=None, modes=None, forget=(), expected=None):
    """Preflight everything, save journal, write files, then commit ownership."""
    if getattr(m, 'signature', None) is not None and xdg.signature(manifest_path()) != m.signature:
        raise ValueError('manifest changed before transaction')
    if expected is not None:
        from .adoption import signature
        if any(signature(path) != value for path, value in expected.items()):
            raise ValueError('reviewed input changed before transaction; replan')
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
                                'installed_sha256': xdg.digest(current), 'installed_mode': mode if current is not None else None, 'kind': registrations.get(path, 'static')}
            if registrations.get(path) == 'codex-theme':
                m['files'][path]['owned_initial'] = encode(changes.get(path, current))
        if path in changes:
            data = changes[path]
            m['files'][path]['installed_sha256'] = xdg.digest(data)
            m['files'][path]['installed_mode'] = modes.get(path, snapshots[path]['mode']) if data is not None else None
    old_manifest = xdg.read(manifest_path())
    for path in forget:
        m['files'].pop(path, None)
    new_manifest = (json.dumps(m, indent=2) + '\n').encode()
    old_manifest_signature = xdg.signature(manifest_path())
    if old_manifest_signature['sha256'] != xdg.digest(old_manifest):
        raise ValueError('manifest changed before journal')
    journal = {'version': 2, 'before': snapshots,
               'after': {p: xdg.digest(changes.get(p, decode(v['data']))) for p, v in snapshots.items()},
               'after_modes': {p: modes.get(p, v['mode']) if changes.get(p, decode(v['data'])) is not None else None
                               for p, v in snapshots.items()},
               'manifest': encode(old_manifest), 'manifest_before': old_manifest_signature,
               'manifest_after': {'sha256': xdg.digest(new_manifest), 'mode': 0o600}}
    pending = xdg.state() / 'pending.json'
    xdg.write(pending, (json.dumps(journal) + '\n').encode())
    try:
        for path, data in changes.items():
            expected_signature = {'sha256': xdg.digest(decode(snapshots[path]['data'])),
                                  'mode': snapshots[path]['mode'] if snapshots[path]['data'] is not None else None}
            xdg.write(path, data, modes.get(path, snapshots[path]['mode']), expected=expected_signature)
        xdg.write(manifest_path(), new_manifest, expected=old_manifest_signature)
    except BaseException:
        recover()
        raise
    xdg.write(pending, None)
    if isinstance(m, Manifest):
        m.signature = journal['manifest_after']
    return m


def recover():
    pending = xdg.state() / 'pending.json'
    data = xdg.read(pending)
    if data is None:
        return False
    j = json.loads(data)
    if not isinstance(j, dict) or not isinstance(j.get('before'), dict) or set(j['before']) != set(j.get('after', {})):
        raise ValueError('invalid recovery journal targets')
    if any(not isinstance(v, dict) or type(v.get('mode')) is not int or not 0 <= v['mode'] <= 0o777
           for v in j['before'].values()):
        raise ValueError('invalid recovery journal permissions')
    if j.get('version', 1) not in (1, 2):
        raise ValueError('unsupported recovery journal')
    if j.get('version') == 2 and set(j.get('after_modes', {})) != set(j['before']):
        raise ValueError('invalid recovery journal modes')
    observed = {}
    for path, before in j['before'].items():
        current = xdg.signature(path)
        original = {'sha256': xdg.digest(decode(before['data'])),
                    'mode': before['mode'] if before['data'] is not None else None}
        # Legacy journals cannot prove a changed mode; ambiguity must fail closed.
        after = {'sha256': j['after'][path],
                 'mode': j.get('after_modes', {}).get(path, before['mode']) if j['after'][path] is not None else None}
        if current not in (original, after):
            raise ValueError('recovery stopped to preserve an external edit: ' + path)
        observed[path] = current
    manifest_current = xdg.signature(manifest_path())
    manifest_before = j.get('manifest_before', {'sha256': xdg.digest(decode(j['manifest'])),
                                               'mode': 0o600 if j['manifest'] is not None else None})
    if manifest_current not in (manifest_before, j.get('manifest_after', manifest_before)):
        raise ValueError('recovery stopped to preserve an external manifest edit')
    for path, before in j['before'].items():
        xdg.write(path, decode(before['data']), before['mode'], expected=observed[path])
    xdg.write(manifest_path(), decode(j['manifest']), manifest_before['mode'] or 0o600, expected=manifest_current)
    xdg.write(pending, None)
    return True
