"""Configuration evidence is separate from unobserved running application state."""
import json
import re
import tomllib
from pathlib import Path

from . import adapters, jsonc, native, xdg


def kitty_options(path, seen=None):
    seen = set() if seen is None else seen
    path = xdg.safe(path)
    if path in seen or len(seen) >= 32:
        raise ValueError('cyclic or excessive Kitty includes')
    seen.add(path)
    data = xdg.read(path)
    if data is None:
        return {}, []
    options, includes = {}, []
    for line in data.decode().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, _, value = line.partition(' ')
        if key == 'include':
            # Diagnose ordinary files only; dynamic/env/glob includes stay unknown.
            if any(c in value for c in '$*?['):
                raise ValueError('dynamic Kitty include requires native verification')
            child = Path(value) if Path(value).is_absolute() else path.parent / value
            nested, paths = kitty_options(child, seen)
            options.update(nested)
            includes += [str(child), *paths]
        elif key.startswith('color') or key in ('background', 'foreground', 'cursor', 'selection_background', 'selection_foreground'):
            options[key] = value.strip()
    seen.remove(path)
    return options, includes


def states(manifest, palette=None):
    result = {}
    for name, item in adapters.registry().items():
        entry = {'available': False, 'installed': name in manifest['adapters'],
                 'active': False, 'palette_applied': None, 'running_palette': 'unverified',
                 'reload': item['reload'], 'reload_required': 'unknown', 'issues': []}
        try:
            entry['available'] = adapters.available(item)
            if name == 'codex':
                entry['compatibility'] = native.codex_version()
                data = xdg.read(adapters.target('codex/config.toml'))
                entry['active'] = bool(data and tomllib.loads(data.decode()).get('tui', {}).get('theme') == native.THEME)
                entry['reload_required'] = 'restart after palette changes'
            elif name == 'fastfetch':
                entry['compatibility'] = native.fastfetch_version()
                data = xdg.read(native.fastfetch_path())
                if data:
                    value = jsonc.parse(data.decode()).value
                    colors = value.get('display', {}).get('color', {})
                    entry['active'] = entry['installed'] and bool(colors)
                    if palette and entry['active']:
                        expected = json.loads(adapters.render(adapters.assets().joinpath('adapters/fastfetch.colors').read_text(), palette))
                        entry['palette_applied'] = all(colors.get(k) == v for k, v in expected.items())
                entry['reload_required'] = 'next invocation; no persistent process'
            elif name == 'kitty':
                options, includes = kitty_options(adapters.target('config/kitty/kitty.conf'))
                owned = str(adapters.target(item['outputs'][0]['path']))
                entry['active'] = owned in includes
                external = [p for p in includes if 'noctalia' in Path(p).name and p != owned]
                entry['external_noctalia_includes'] = external
                entry['managed_activation'] = owned in includes
                entry['active'] = owned in includes or bool(external)
                if entry['managed_activation'] and palette:
                    rendered = adapters.render(adapters.assets().joinpath('adapters/kitty.conf').read_text(), palette).decode()
                    expected = dict(re.findall(r'^(color\d+|background|foreground|cursor|selection_background|selection_foreground)\s+(\S+)', rendered, re.M))
                    entry['palette_applied'] = all(options.get(k) == v for k, v in expected.items())
                    if not entry['palette_applied']:
                        entry['issues'].append('effective Kitty config differs from palette; inspect later overrides')
                entry['reload_required'] = 'Ctrl+Shift+F5 or apply --reload; running colors unverified'
            else:
                entry['active'] = None  # App activation varies; do not infer pixels.
            if entry['installed'] and palette and entry['palette_applied'] is None:
                outputs = adapters.generate([name], palette)
                entry['palette_applied'] = all(xdg.read(p) == data for p, data in outputs.items())
            entry['modified'] = any(xdg.digest(xdg.read(p)) != e['installed_sha256'] for p, e in manifest['files'].items()
                                    if p in {str(adapters.target(o['path'])) for o in item['outputs']})
        except (OSError, ValueError, TypeError, KeyError) as exc:
            entry['issues'].append(str(exc))
        result[name] = entry
    return result
