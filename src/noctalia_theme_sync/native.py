"""Small native configuration helpers. Never read authentication or pet assets."""
from contextlib import contextmanager
import copy
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from . import jsonc, xdg

THEME = 'noctalia-theme-sync'
MIN_CODEX = (0, 160, 1)  # Conservatively the version whose native API was inspected.


def fastfetch_path():
    value = os.environ.get('NTS_FASTFETCH_CONFIG')
    if value:
        return xdg.safe(Path(value))
    root = xdg.base('config') / 'fastfetch'
    return xdg.safe(root / ('config.json' if (root / 'config.json').exists() and not (root / 'config.jsonc').exists() else 'config.jsonc'))


def fastfetch_config(data, palette=None):
    text = (data or b'{}\n').decode()
    old = jsonc.parse(text).value
    colors = palette['colors'] if palette else {}
    roles = {'keys': 'primary', 'title': 'secondary', 'separator': 'tertiary', 'output': 'on_surface'}
    for key, role in roles.items():
        text = jsonc.set_value(text, ('display', 'color', key), colors.get(role, {'keys': 'blue', 'title': 'magenta', 'separator': 'cyan', 'output': 'default'}[key]))
    logo = old.get('logo', {})
    if isinstance(logo, str):
        text = jsonc.set_value(text, ('logo',), {'source': logo})
        logo = {'source': logo}
    if isinstance(logo, dict):
        for slot, role, fallback in (('1', 'primary', 'blue'), ('2', 'secondary', 'magenta'), ('3', 'tertiary', 'cyan')):
            text = jsonc.set_value(text, ('logo', 'color', slot), colors.get(role, fallback))
    return text.encode()


def codex_theme(data, theme=THEME):
    """Only tui.theme may change; parsing proves all other TOML values survive.

    Unsupported inline/multiline/quoted layouts stop safely rather than rewriting.
    """
    text = (data or b'').decode()
    before = tomllib.loads(text)
    expected = copy.deepcopy(before)
    if not isinstance(expected.setdefault('tui', {}), dict):
        raise ValueError('Codex tui must be a table')
    expected['tui']['theme'] = theme
    if before == expected:
        return text.encode()
    headers = list(re.finditer(r'^\s*\[[^\n]+\][ \t]*(?:#[^\n]*)?$', text, re.M))
    selected = [m for m in headers if re.fullmatch(r'\s*\[tui\][ \t]*(?:#[^\n]*)?', m[0])]
    if selected:
        begin = selected[0].end()
        end = next((m.start() for m in headers if m.start() > selected[0].start()), len(text))
        body = text[begin:end]
        key = r'(?m)^([ \t]*theme[ \t]*=[ \t]*)("(?:[^"\\\n]|\\.)*"|\x27[^\x27\n]*\x27)([ \t]*(?:#[^\n]*)?)$'
        if 'theme' in before.get('tui', {}):
            if len(list(re.finditer(key, body))) != 1:
                raise ValueError('unsupported Codex theme value layout; use a plain [tui] table')
            body = re.sub(key, lambda m: m[1] + json.dumps(theme) + m[3], body)
        else:
            body += ('\n' if body and not body.endswith('\n') else '') + 'theme = ' + json.dumps(theme) + '\n'
        if body and not body.startswith('\n'):
            body = '\n' + body
        text = text[:begin] + body + text[end:]
    elif 'tui' not in before:
        text += ('\n' if text and not text.endswith('\n') else '') + '\n[tui]\ntheme = ' + json.dumps(theme) + '\n'
    else:
        raise ValueError('unsupported Codex tui layout; use a plain [tui] table')
    if tomllib.loads(text) != expected:
        raise ValueError('Codex configuration preservation check failed')
    return text.encode()


def codex_version():
    binary = os.environ.get('NTS_CODEX_BIN') or shutil.which('codex')
    if not binary:
        return {'version': None, 'compatible': False, 'reason': 'Codex executable missing'}
    try:
        # Do not invoke known privileged/network/pet wrappers during diagnostics.
        path = Path(binary)
        with path.open('rb') as stream:
            prefix = stream.read(8192)
        if prefix.startswith(b'#!') and any(word in prefix for word in (b'sudo', b'vpn-run', b'codex-vpn', b'pixel_cache')):
            return {'version': None, 'compatible': False, 'reason': 'wrapper needs explicit native executable via NTS_CODEX_BIN; no sudo or pet initialization performed'}
        # Read-only query; never retry via sudo or manipulate a wrapper.
        result = subprocess.run([binary, '--version'], text=True, capture_output=True, timeout=4)
        m = re.search(r'\bcodex(?:-cli)?\s+(\d+)\.(\d+)\.(\d+)', result.stdout)
        version = tuple(map(int, m.groups())) if m and result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        version = None
    compatible = version is not None and version >= MIN_CODEX
    return {'version': version, 'compatible': compatible, 'reason': 'native custom themes; restart after changes' if compatible else 'requires verified Codex >=0.160.1; for wrappers set NTS_CODEX_BIN to the native executable'}


def fastfetch_version():
    binary = shutil.which('fastfetch')
    version = None
    if binary:
        try:
            result = subprocess.run([binary, '--version'], text=True, capture_output=True, timeout=4)
            match = re.search(r'(?:fastfetch\s+)?(\d+)\.(\d+)\.(\d+)', result.stdout)
            version = tuple(map(int, match.groups())) if match and result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {'version': version, 'compatible': version is not None and version >= (2, 63, 1),
            'reason': 'requires verified Fastfetch >=2.63.1 (native JSONC colors)'}


@contextmanager
def installation_context(manifest):
    """Keep native targets stable when Noctalia's hook has a different environment."""
    context = manifest.get('native_context', {})
    allowed = {'CODEX_HOME', 'NTS_FASTFETCH_CONFIG', 'NTS_CODEX_BIN'}
    if not isinstance(context, dict) or set(context) - allowed:
        raise ValueError('invalid native installation context')
    previous = {key: os.environ.get(key) for key in context}
    try:
        for key, value in context.items():
            if not isinstance(value, str) or not Path(value).is_absolute() or '..' in Path(value).parts:
                raise ValueError('native installation context must contain absolute paths')
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def target_context(names):
    context = {}
    if 'codex' in names:
        context['CODEX_HOME'] = str(xdg.codex_home())
        if os.environ.get('NTS_CODEX_BIN'):
            context['NTS_CODEX_BIN'] = str(Path(os.environ['NTS_CODEX_BIN']).resolve())
    if 'fastfetch' in names:
        context['NTS_FASTFETCH_CONFIG'] = str(fastfetch_path())
    return context


def codex_selected(data):
    return data is not None and tomllib.loads(data.decode()).get('tui', {}).get('theme') == THEME


def codex_restore(data, original, baseline=None):
    """Restore only the original theme; preserve all subsequent non-theme changes."""
    if data == original:
        return data
    old = tomllib.loads((original or b'').decode())
    if 'theme' in old.get('tui', {}):
        result = codex_theme(data, old['tui']['theme'])
    else:
        text = (data or b'').decode()
        before = tomllib.loads(text)
        expected = copy.deepcopy(before)
        expected.setdefault('tui', {}).pop('theme', None)
        pattern = r'(?m)^[ \t]*theme[ \t]*=[^\n]*\n?'
        header = re.search(r'(?m)^[ \t]*\[tui\][^\n]*', text)
        if not header:
            raise ValueError('cannot safely restore Codex theme layout')
        end_match = re.search(r'(?m)^[ \t]*\[', text[header.end():])
        end = header.end() + end_match.start() if end_match else len(text)
        body = re.sub(pattern, '', text[header.end():end])
        text = text[:header.end()] + body + text[end:]
        if not expected['tui'] and 'tui' not in old:
            expected.pop('tui')
            text = text[:header.start()] + text[header.end() + len(body):]
        if tomllib.loads(text) != expected:
            raise ValueError('Codex restore preservation check failed')
        result = text.encode()
    if data == baseline and tomllib.loads(result.decode()) == old:
        return original  # Exact original bytes/absence when no new preferences exist.
    return result
