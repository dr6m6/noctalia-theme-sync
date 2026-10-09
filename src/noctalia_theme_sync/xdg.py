"""XDG paths and conservative filesystem operations."""
import hashlib
import os
import stat
import tempfile
from pathlib import Path


def base(kind):
    defaults = {'config': '.config', 'state': '.local/state', 'data': '.local/share', 'cache': '.cache', 'bin': '.local/bin'}
    value = os.environ.get('NTS_BIN_HOME' if kind == 'bin' else 'XDG_' + kind.upper() + '_HOME', '')
    result = Path(value) if value else Path.home() / defaults[kind]
    if not result.is_absolute():
        raise ValueError('XDG directories must be absolute')
    return result


def codex_home():
    value = os.environ.get('CODEX_HOME', '')
    root = Path(value) if value else Path.home() / '.codex'
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('CODEX_HOME must be absolute without traversal')
    return root


def state():
    return base('state') / 'noctalia-theme-sync'


def canonical():
    return base('state') / 'noctalia/theme-sync'


def safe(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('unsafe relative path')
    roots = [base(kind) for kind in ('config', 'data', 'state', 'cache', 'bin')]
    # Only these two native theme targets are permitted outside XDG roots.
    codex_targets = {codex_home() / 'config.toml', codex_home() / 'themes/noctalia-theme-sync.tmTheme'}
    if path not in codex_targets and not any(path.is_relative_to(root) for root in roots):
        raise ValueError('target outside XDG directories')
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('symlink target or ancestor: ' + str(parent))
        if parent.exists() and parent != path and not parent.is_dir():
            raise ValueError('non-directory ancestor: ' + str(parent))
    if path.exists() and not path.is_file():
        raise ValueError('target is not a regular file: ' + str(path))
    if path.exists() and (path.stat().st_uid != os.getuid() or path.stat().st_nlink != 1):
        raise ValueError('target must be owned and not hardlinked: ' + str(path))
    return path


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def read(path):
    path = safe(path)
    if not path.exists():
        return None
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('configuration file too large: ' + str(path))
    return path.read_bytes()


def write(path, data, mode=0o600):
    path = safe(path)
    if data is None:
        if path.exists():
            path.unlink()
        return
    if read(path) == data and stat.S_IMODE(path.stat().st_mode) == mode:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        safe(path)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
