#!/usr/bin/env python3
"""Verify native rendering and optional wallpaper change without replacing the desktop."""
import argparse
import contextlib
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from noctalia_theme_sync import adapters, cli, xdg  # noqa: E402
from noctalia_theme_sync.model import read_json, validate  # noqa: E402


def run(*argv, env=None):
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('command failed: ' + ' '.join(argv[:3]) + '; ' + result.stderr)
    return result.stdout.strip()


def image(path):
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    data = (b'\0' + bytes((154, 72, 214)) * 32 + bytes((65, 140, 95)) * 32) * 64
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 64, 64, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(data)) + chunk(b'IEND', b''))


def wait_theme(source, expected_wallpaper, before=None):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            p = validate(read_json(source))
            if p['wallpaper'] == expected_wallpaper and (before is None or p['revision'] > before):
                return p
        except (ValueError, OSError):
            pass
        time.sleep(.2)
    raise RuntimeError('canonical publisher did not settle within 25 seconds')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-wallpaper', action='store_true', help='temporarily use a synthetic image, then restore the original in finally')
    args = parser.parse_args()
    source = xdg.canonical() / 'current.json'
    original = validate(read_json(source))
    wallpaper = run('noctalia', 'msg', 'wallpaper-get')
    mode = run('noctalia', 'msg', 'theme-mode-get')
    if not Path(wallpaper).is_file() or original['wallpaper'] != wallpaper:
        raise RuntimeError('current canonical export must match a readable active wallpaper')
    # No profile/state tree is copied. Only code and a private canonical palette snapshot.
    config_root = xdg.base('config') / 'noctalia'
    config_before = {p: p.read_bytes() for p in config_root.glob('*.toml')}
    selected = ['gtk', 'qt', 'neovim', 'btop', 'cava']
    parity_sources = [('gtk3.css', 'config/gtk-3.0/noctalia.css'), ('gtk4.css', 'config/gtk-4.0/noctalia.css'),
                      ('qt.conf', 'config/qt6ct/colors/noctalia.conf'), ('btop.theme', 'config/btop/themes/noctalia.theme'),
                      ('cava.ini', 'config/cava/themes/noctalia'), ('neovim.lua', 'config/nvim/colors/noctalia.lua'),
                      ('tmux.conf', 'config/tmux/themes/noctalia.conf')]
    parity = []
    for template, existing in parity_sources:
        path = adapters.target(existing)
        if path.exists():
            generated = adapters.render(adapters.assets().joinpath('adapters', template).read_text(), original)
            if path.read_bytes() != generated:
                raise RuntimeError('extracted template parity mismatch: ' + template)
            parity.append(template)
    baseline_palette = original
    env_before = dict(os.environ)
    changed = False
    with tempfile.TemporaryDirectory(prefix='nts-desktop-smoke-') as tmp:
        root = Path(tmp)
        # Offline native renderer uses a precomputed Noctalia palette, never another extraction.
        native = root / 'native.json'
        native.write_text(json.dumps({'dark': original['colors'], 'light': original['colors']}))
        for template in ('gtk3.css', 'gtk4.css', 'qt.conf', 'btop.theme', 'cava.ini', 'neovim.lua', 'tmux.conf'):
            out = root / (template + '.rendered')
            inp = adapters.assets().joinpath('adapters', template)
            run('noctalia', 'theme', '--theme-json', str(native), '--default-mode', mode, '-r', str(inp) + ':' + str(out), env=dict(env_before, GSETTINGS_BACKEND='memory'))
            if out.read_bytes() != adapters.render(inp.read_text(), original):
                raise RuntimeError('native renderer parity mismatch: ' + template)
        isolated_env = dict(env_before, HOME=str(root / 'home'), NTS_BIN_HOME=str(root / 'bin'),
                            **{'XDG_' + k.upper() + '_HOME': str(root / k) for k in ('config', 'state', 'data', 'cache')})
        (root / 'config/noctalia').mkdir(parents=True)
        isolated_palette = root / 'state/noctalia/theme-sync/current.json'
        isolated_palette.parent.mkdir(parents=True)
        isolated_palette.write_text(json.dumps(original))
        def command(*arguments):
            with contextlib.redirect_stdout(io.StringIO()):
                result = cli.main(arguments)
            if result:
                raise RuntimeError('isolated CLI failed: ' + arguments[0])
        os.environ.clear()
        os.environ.update(isolated_env)
        try:
            command('doctor')
            command('install', '--adapters', ','.join(selected), '--dry-run')
            command('install', '--adapters', ','.join(selected))
            command('install', '--adapters', ','.join(selected))
            command('apply')
        finally:
            os.environ.clear()
            os.environ.update(env_before)
        try:
            if args.cycle_wallpaper:
                sample = root / 'synthetic.png'
                image(sample)
                changed = True
                run('noctalia', 'msg', 'wallpaper-set', str(sample))
                # Old working pipeline runs its own hooks. The new project remains isolated.
                next_palette = wait_theme(source, str(sample), original['revision'])
                if next_palette['colors'] == original['colors']:
                    raise RuntimeError('synthetic image did not change Noctalia colors')
                isolated_palette.write_text(json.dumps(next_palette))
                os.environ.clear()
                os.environ.update(isolated_env)
                try:
                    command('apply')
                    for name in selected:
                        for output in adapters.registry()[name]['outputs']:
                            expected = adapters.render(adapters.assets().joinpath('adapters', output['template']).read_text(), next_palette)
                            if adapters.target(output['path']).read_bytes() != expected:
                                raise RuntimeError('adapter update mismatch: ' + name)
                finally:
                    os.environ.clear()
                    os.environ.update(env_before)
        finally:
            if changed:
                run('noctalia', 'msg', 'wallpaper-set', wallpaper)
                restored = wait_theme(source, wallpaper)
                if restored['mode'] != baseline_palette['mode'] or restored['colors'] != baseline_palette['colors']:
                    raise RuntimeError('original palette restoration mismatch')
                # Restore exact persisted TOML bytes only if unrelated preferences stayed intact.
                for path, before in config_before.items():
                    if path.read_bytes() != before:
                        import tomllib
                        old, new = tomllib.loads(before.decode()), tomllib.loads(path.read_text())
                        old.pop('wallpaper', None)
                        new.pop('wallpaper', None)
                        if old != new:
                            raise RuntimeError('concurrent unrelated config change; preserve it and review: ' + path.name)
                        fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
                        with os.fdopen(fd, 'wb') as stream:
                            stream.write(before)
                            stream.flush()
                            os.fsync(stream.fileno())
            os.environ.clear()
            os.environ.update(isolated_env)
            try:
                command('uninstall')
            finally:
                os.environ.clear()
                os.environ.update(env_before)
    print(json.dumps({'native_template_parity': 'PASS', 'existing_output_parity': parity,
                      'isolated_install_repeat_apply_uninstall': 'PASS', 'wallpaper_cycle': 'PASS' if changed else 'not requested',
                      'desktop_replaced': False, 'original_wallpaper_restored': changed}, indent=2))


if __name__ == '__main__':
    main()
