"""Read-only writer inventory and checksum-bound, private installation plans."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib

from . import adapters, transaction as tx, xdg


def expand(value):
    """Expand documented path variables without shell evaluation."""
    variables = {'HOME': str(Path.home()), **{
        'XDG_' + k.upper() + '_HOME': str(xdg.base(k)) for k in ('config', 'state', 'data', 'cache')
    }}
    value = re.sub(r'\$\{([A-Z_]+)\}|\$([A-Z_]+)', lambda m: variables.get(m[1] or m[2], m[0]), value)
    return value.replace('~/', str(Path.home()) + '/', 1) if value.startswith('~/') else value


def inventory(selected, consume=False):
    """Find native and personal writers even when output filenames differ."""
    aliases = {'gtk3': 'gtk', 'gtk4': 'gtk', 'pywalfox': 'firefox'}
    catalog = adapters.registry()
    legacy = {'kitty.conf': 'kitty', 'gtk3.css': 'gtk', 'gtk4.css': 'gtk', 'qtct.conf': 'qt',
              'btop.theme': 'btop', 'cava.ini': 'cava', 'neovim.lua': 'neovim', 'tmux.conf': 'tmux',
              'pywalfox.json': 'firefox', 'vesktop.css': 'vesktop', 'telegram.tdesktop-theme': 'telegram',
              'codex.tmTheme': 'codex', 'steam.css': 'steam'}
    issues, writers, publishers, hooks = [], [], [], []
    owned = tx.load()['files']
    for path in sorted((xdg.base('config') / 'noctalia').glob('*.toml')):
        try:
            raw = xdg.read(path)
            templates = tomllib.loads(raw.decode()).get('theme', {}).get('templates', {})
            if str(path) in owned and path.name == 'noctalia-theme-sync.toml':
                continue
            for group, enabled, ids in (
                ('builtin', templates.get('enable_builtin_templates', True), templates.get('builtin_ids', [])),
                ('community', templates.get('enable_community_templates', False), templates.get('community_ids', [])),
            ):
                if enabled:
                    overlap = {aliases.get(n, n) for n in ids} & set(selected)
                    if overlap:
                        issues.append('existing ' + group + ' adapters in ' + path.name + ': ' + ', '.join(sorted(overlap)))
            for key, entry in templates.get('user', {}).items():
                outputs = entry.get('output_path', [])
                outputs = [outputs] if isinstance(outputs, str) else outputs
                if not isinstance(outputs, list) or not all(isinstance(v, str) for v in outputs):
                    raise ValueError('invalid user output_path')
                resolved = [expand(v) for v in outputs]
                writer = {'file': str(path), 'key': key, 'input': entry.get('input_path'), 'outputs': resolved}
                writers.append(writer)
                if any(p in resolved for p in (str(xdg.canonical() / 'palette.json'), str(xdg.canonical() / 'current.json'))):
                    publishers.append(writer)
                for field in ('pre_hook', 'post_hook', 'post_action'):
                    if field in entry:
                        hooks.append({'file': str(path), 'key': key, 'field': field, 'value': entry[field]})
                name = aliases.get(key, key)
                input_path = entry.get('input_path', '')
                if isinstance(input_path, str):
                    name = legacy.get(Path(input_path).name, name)
                for candidate in selected:
                    exact = {str(adapters.target(o['path'])) for o in catalog[candidate]['outputs']}
                    if candidate == name or exact.intersection(resolved):
                        issues.append('existing user writer for ' + candidate + ' in ' + path.name + ': ' + key)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            issues.append('cannot inspect Noctalia TOML: ' + path.name + ' (' + type(exc).__name__ + ')')
    publisher_outputs = [p for writer in publishers for p in writer['outputs']
                         if p in (str(xdg.canonical() / 'palette.json'), str(xdg.canonical() / 'current.json'))]
    if len(publisher_outputs) != len(set(publisher_outputs)):
        issues.append('multiple writers for canonical state; reconcile before consuming or publishing')
    if publishers and not consume:
        issues.append('canonical publisher already configured; use --consume-existing')
    # Existing installations without a readable fragment must not get a second producer.
    if xdg.read(xdg.canonical() / 'palette.json') is not None and not consume and not owned:
        issues.append('unmanaged rendered palette exists; identify its publisher and use --consume-existing')
    return {'writers': writers, 'publishers': publishers, 'hooks': hooks, 'blockers': sorted(set(issues))}


def signature(path):
    raw = xdg.read(path)
    if raw is None:
        return {'sha256': None, 'mode': None}
    return {'sha256': xdg.digest(raw), 'mode': stat.S_IMODE(Path(path).stat().st_mode)}


def bind(report, changes, registrations):
    """Bind decisions, input bytes, permissions, target roots and runtime content."""
    paths = set(changes) | set(registrations) | {str(tx.manifest_path()), str(xdg.state() / 'pending.json')}
    paths |= {str(p) for p in (xdg.base('config') / 'noctalia').glob('*.toml')}
    paths.add(str(xdg.canonical() / 'current.json'))
    payload = {
        'format': 1, 'adapters': report['adapters'], 'consume_existing': report['consume_existing'],
        'bridge': report['bridge'], 'native_context': report['native_context'],
        'roots': {k: str(xdg.base(k)) for k in ('config', 'state', 'data', 'cache', 'bin')},
        'inputs': {p: signature(p) for p in sorted(paths)},
        'outputs': {p: xdg.digest(data) for p, data in sorted(changes.items())},
        'registrations': registrations, 'blockers': report['blockers'],
    }
    report['reviewed_plan'] = payload
    report['plan_sha256'] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def save(path, report):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('plan file must be absolute without symlinks')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Never replace a previously reviewed plan or loosen its permissions.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(json.dumps(report, indent=2) + '\n')
        out.flush()
        os.fsync(out.fileno())


def check(path, report):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('reviewed plan must be an absolute regular file without symlinks')
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('reviewed plan too large')
    previous = json.loads(path.read_text())
    if previous.get('blockers') or previous.get('reviewed_plan') != report['reviewed_plan'] or previous.get('plan_sha256') != report['plan_sha256']:
        raise ValueError('reviewed plan drift or unresolved blockers; inspect and create a new plan')
