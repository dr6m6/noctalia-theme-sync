"""Data-driven adapters for native app configuration; no shell evaluation."""
import json
import re
import shutil
from importlib.resources import files
from pathlib import Path

from . import xdg
from .model import validate


def assets():
    return files('noctalia_theme_sync').joinpath('assets')


def registry():
    result = {}
    for path in sorted(assets().joinpath('adapters').iterdir(), key=lambda p: p.name):
        if path.name.endswith('.json'):
            item = json.loads(path.read_text())
            if not re.fullmatch(r'[a-z][a-z0-9-]*', item['id']) or item['id'] in result:
                raise ValueError('invalid or duplicate adapter id')
            result[item['id']] = item
    return result


def target(value):
    kind, relative = value.split('/', 1)
    if relative.startswith('/') or '..' in Path(relative).parts:
        raise ValueError('invalid adapter target')
    return xdg.safe(xdg.base(kind) / relative)


def available(item):
    return any(shutil.which(command) for command in item['commands']) or any(target(p).exists() for p in item.get('detect', []))


def render(text, palette):
    """Only color-role/default/hex and mode substitution; never execute templates."""
    validate(palette)
    def replace(match):
        expression = match[1].strip()
        if expression == 'mode':
            return palette['mode']
        token = re.fullmatch(r'colors\.([a-z][a-z0-9_]*)\.default\.hex', expression)
        if not token or token[1] not in palette['colors']:
            raise ValueError('unsupported or missing adapter token: ' + expression)
        return palette['colors'][token[1]]
    result = re.sub(r'\{\{(.*?)\}\}', replace, text, flags=re.S)
    if '{{' in result or '<*' in result:
        raise ValueError('unresolved adapter syntax')
    return result.encode()


def generate(selected, palette):
    catalog = registry()
    result = {}
    for name in selected:
        for output in catalog[name]['outputs']:
            path = str(target(output['path']))
            if path in result:
                raise ValueError('duplicate adapter output')
            result[path] = render(assets().joinpath('adapters', output['template']).read_text(), palette)
    return result


def block(data, label, content):
    """Replace one exact marked block, keeping all surrounding bytes intact."""
    data = (data or b'').decode('utf-8')
    start, end = f'# noctalia-theme-sync begin {label}\n', f'# noctalia-theme-sync end {label}\n'
    if start in data or end in data:
        if data.count(start) != 1 or data.count(end) != 1:
            raise ValueError('malformed managed config block')
        a, b = data.index(start), data.index(end) + len(end)
        if b <= a:
            raise ValueError('malformed managed config block')
        return (data[:a] + start + content + '\n' + end + data[b:]).encode()
    return (data + ('\n' if data and not data.endswith('\n') else '') + start + content + '\n' + end).encode()


def ini(data, section, values):
    """Patch individual INI keys while preserving unrelated content and comments."""
    text = (data or b'').decode('utf-8')
    matches = list(re.finditer(r'^\[([^\]\n]+)\][^\n]*\n?', text, re.M))
    selected = [m for m in matches if m[1] == section]
    if len(selected) > 1:
        raise ValueError('duplicate INI section: ' + section)
    if not selected:
        text += ('\n' if text and not text.endswith('\n') else '') + f'[{section}]\n'
        begin, end = len(text), len(text)
    else:
        match = selected[0]
        begin = match.end()
        end = next((m.start() for m in matches if m.start() > match.start()), len(text))
    body = text[begin:end]
    for key, value in values.items():
        expression = r'^[ \t]*' + re.escape(key) + r'\s*=[^\n]*'
        if len(re.findall(expression, body, re.M)) > 1:
            raise ValueError('duplicate INI key: ' + key)
        if re.search(expression, body, re.M):
            body = re.sub(expression, key + '=' + value, body, flags=re.M)
        else:
            body += ('\n' if body and not body.endswith('\n') else '') + key + '=' + value + '\n'
    return (text[:begin] + body + text[end:]).encode()


def activation(selected, existing, mode='dark'):
    """Managed configuration, changed only after transaction preflight."""
    result = {}
    def get(relative):
        p = str(target('config/' + relative))
        return p, existing(p)
    def marked(relative, label, content):
        p, data = get(relative)
        result[p] = block(data, label, content)
    if 'kitty' in selected:
        marked('kitty/kitty.conf', 'kitty', 'include themes/noctalia-theme-sync.conf')
    if 'tmux' in selected:
        quoted = json.dumps(str(target('config/tmux/themes/noctalia-theme-sync.conf')))
        marked('tmux/tmux.conf', 'tmux', 'source-file ' + quoted)
    if 'neovim' in selected:
        # Do not guess or overwrite an init.lua/init.vim. Explicit user opt-in.
        pass
    if 'gtk' in selected:
        for version in ('3', '4'):
            p, data = get(f'gtk-{version}.0/gtk.css')
            line = '@import url("noctalia-theme-sync.css");\n'
            if line not in (data or b'').decode():
                result[p] = (line + (data or b'').decode()).encode()
            p, data = get(f'gtk-{version}.0/settings.ini')
            result[p] = ini(data, 'Settings', {'gtk-theme-name': 'adw-gtk3' + ('-dark' if mode == 'dark' else ''),
                                                'gtk-application-prefer-dark-theme': '1' if mode == 'dark' else '0'})
    if 'qt' in selected:
        for version in ('5', '6'):
            p, data = get(f'qt{version}ct/qt{version}ct.conf')
            result[p] = ini(data, 'Appearance', {'custom_palette': 'true', 'color_scheme_path': str(target(f'config/qt{version}ct/colors/noctalia-theme-sync.conf'))})
    if 'btop' in selected:
        p, data = get('btop/btop.conf')
        text = (data or b'').decode()
        text = re.sub(r'^[ \t]*color_theme\s*=.*$', 'color_theme = "noctalia-theme-sync"', text, flags=re.M) if re.search(r'^[ \t]*color_theme\s*=', text, re.M) else text + '\ncolor_theme = "noctalia-theme-sync"\n'
        result[p] = text.encode()
    if 'cava' in selected:
        p, data = get('cava/config')
        result[p] = ini(data, 'color', {'theme': '"noctalia-theme-sync"'})
    return result
