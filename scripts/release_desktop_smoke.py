#!/usr/bin/env python3
"""Opt-in v0.2 desktop validation; temporary app windows, no live installation.

Requires an explicitly authorized wallpaper cycle. No accounts/profiles/pet assets
are copied. Stock Codex is optional via --codex-bin (never invokes VPN wrappers).
Evidence stays in the private output directory until manually reviewed.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import signal
import struct
import subprocess
import sys
import time
import tomllib
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from noctalia_theme_sync import adapters, cli, xdg  # noqa: E402
from noctalia_theme_sync.model import read_json, validate  # noqa: E402
from desktop_smoke import run, wait_theme  # noqa: E402


def image(path, rgb):
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    data = (b'\0' + bytes(rgb) * 64) * 64
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 64, 64, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(data)) + chunk(b'IEND', b''))


@contextlib.contextmanager
def environment(env):
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycle-wallpaper', action='store_true', required=True)
    parser.add_argument('--codex-bin', required=True, help='verified stock native executable')
    parser.add_argument('--fastfetch-bin', default='/run/current-system/sw/bin/fastfetch')
    parser.add_argument('--output', type=Path, required=True, help='private evidence directory outside repository')
    args = parser.parse_args()
    root = args.output.absolute()
    if root.exists():
        raise RuntimeError('use a fresh evidence directory')
    root.mkdir(mode=0o700, parents=True)
    original_env = dict(os.environ)
    source = xdg.canonical() / 'current.json'
    original = validate(read_json(source))
    wallpaper = run('noctalia', 'msg', 'wallpaper-get')
    if original['wallpaper'] != wallpaper:
        raise RuntimeError('live palette/wallpaper mismatch')
    config_before = {p: p.read_bytes() for p in (xdg.base('config') / 'noctalia').glob('*.toml')}
    # Snapshot hashes only: never copy credentials or user artwork into evidence.
    protected = [xdg.codex_home() / 'config.toml', xdg.codex_home() / 'auth.json',
                 xdg.base('config') / 'kitty/kitty.conf', xdg.base('config') / 'fastfetch/braille.json',
                 xdg.base('config') / 'fastfetch/render.py']
    pet_root = xdg.codex_home() / 'pets'
    if pet_root.exists():
        protected += [p for p in pet_root.rglob('*') if p.is_file()]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected if p.is_file()}
    isolated = dict(original_env, HOME=str(root / 'home'), CODEX_HOME=str(root / 'codex'),
                    NTS_CODEX_BIN=args.codex_bin, NTS_BIN_HOME=str(root / 'bin'),
                    **{'XDG_' + k.upper() + '_HOME': str(root / k) for k in ('config', 'data', 'state', 'cache')})
    isolated.pop('NTS_FASTFETCH_CONFIG', None)
    tools = root / 'tools'
    tools.mkdir()
    (tools / 'fastfetch').symlink_to(args.fastfetch_bin)
    isolated['PATH'] = str(tools) + ':' + original_env['PATH']
    (root / 'config/noctalia').mkdir(parents=True)
    (root / 'home').mkdir()
    (root / 'codex').mkdir()
    (root / 'codex/config.toml').write_text('[projects.' + json.dumps(str(root / 'home')) + ']\ntrust_level="trusted"\n')
    # A predictable original custom logo/module layout: no personal assets or facts.
    ff = root / 'config/fastfetch/config.jsonc'
    ff.parent.mkdir(parents=True)
    ff.write_text(json.dumps({'logo': {'type': 'data', 'source': '$1██  $2██  $3██', 'padding': {'right': 3}},
                             'modules': [{'type': 'custom', 'key': 'Palette', 'format': 'Noctalia v5'},
                                         {'type': 'custom', 'key': 'Fastfetch', 'format': 'Native JSONC colors'},
                                         {'type': 'custom', 'key': 'Layout', 'format': 'Preserved user modules'}]}))
    canonical = root / 'state/noctalia/theme-sync/current.json'
    canonical.parent.mkdir(parents=True)
    canonical.write_text(json.dumps(original))
    def command(*arguments):
        with environment(isolated), contextlib.redirect_stdout(io.StringIO()):
            if cli.main(arguments):
                raise RuntimeError('isolated CLI failed: ' + arguments[0])
    # Old canonical exports may lack terminal tokens: use native Noctalia's resolved
    # terminal template separately, without inventing colors or another engine.
    include = root / 'config/kitty/themes/native.conf'
    include.parent.mkdir(parents=True)
    kitty_conf = root / 'config/kitty/kitty.conf'
    kitty_conf.write_text('include themes/native.conf\nfont_size 16\nremember_window_size no\ninitial_window_width 950\ninitial_window_height 570\n')
    def terminal_palette(palette):
        native_json = root / 'native.json'
        native_json.write_text(json.dumps({'dark': palette['colors'], 'light': palette['colors']}))
        run('noctalia', 'theme', '--theme-json', str(native_json), '--default-mode', palette['mode'],
            '-r', str(adapters.assets().joinpath('adapters/kitty.conf')) + ':' + str(include),
            env=dict(isolated, GSETTINGS_BACKEND='memory'))
        return include.read_bytes()
    windows, changed = [], False
    title_prefix = 'Noctalia Theme Sync Release Preview'
    def launch(label, argv, env=None, control=None):
        title = title_prefix + ' ' + label
        options = ['--override', 'allow_remote_control=socket-only', '--listen-on', 'unix:' + str(control)] if control else []
        proc = subprocess.Popen(['kitty', '--config', str(kitty_conf), '--title', title, *options, *argv], env=env or original_env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        windows.append(proc)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            items = json.loads(run('niri', 'msg', '--json', 'windows'))
            found = [w for w in items if w.get('title') == title]
            if found:
                return proc, found[0]['id']
            time.sleep(.2)
        raise RuntimeError('preview window unavailable')
    def screenshot(identifier, label):
        run('niri', 'msg', 'action', 'screenshot-window', '--id', str(identifier), '--path', str(root / (label + '.png')))
    query_script = root / 'terminal-preview.sh'
    query_script.write_text('#!/bin/sh\nprintf "Noctalia v5 • Kitty + Fastfetch\\n\\n"\n'
                            'while true; do\n'
                            '  if [ -f "$NTS_PREVIEW_ROOT/query-request" ]; then\n'
                            '    kitty +kitten query_terminal --wait-for=2 foreground background > "$NTS_PREVIEW_ROOT/query.txt"\n'
                            '    rm "$NTS_PREVIEW_ROOT/query-request"\n'
                            '    printf "\\033[2J\\033[HNoctalia v5 • Kitty + Fastfetch\\n\\n"\n'
                            '    "$NTS_FASTFETCH_BIN" --config "$NTS_PREVIEW_ROOT/config/fastfetch/config.jsonc"\n'
                            '    printf "\\nNative Kitty reload: SIGUSR1\\nFastfetch: next invocation\\n"\n'
                            '  fi\n'
                            '  sleep 0.2\n'
                            'done\n')
    preview_env = dict(original_env, NTS_PREVIEW_ROOT=str(root), NTS_FASTFETCH_BIN=args.fastfetch_bin)
    # Native Codex TUI with a deliberately non-networked preview provider, no login.
    preview_env.pop('NO_COLOR', None)
    codex_env = dict(isolated, NTS_PREVIEW_KEY='offline-preview-placeholder', TERM='xterm-kitty')
    codex_env.pop('NO_COLOR', None)
    codex_args = [args.codex_bin, '--cd', str(root / 'home'), '-c', 'model_provider="preview"',
                  '-c', 'check_for_update_on_startup=false', '-c', 'model="offline-preview"', '-c', 'model_providers.preview.name="Offline preview"',
                  '-c', 'model_providers.preview.base_url="http://127.0.0.1:9/v1"',
                  '-c', 'model_providers.preview.env_key="NTS_PREVIEW_KEY"']
    revisions, query_results, native_hashes, existing_kitty_parity = [], [], [], []
    try:
        command('plan', '--adapters', 'fastfetch,codex', '--experimental', '--consume-existing')
        command('install', '--adapters', 'fastfetch,codex', '--experimental', '--consume-existing', '--dry-run')
        command('install', '--adapters', 'fastfetch,codex', '--experimental', '--consume-existing')
        command('install', '--adapters', 'fastfetch,codex', '--experimental', '--consume-existing')
        terminal_palette(original)
        term_proc, term_id = launch('Kitty Fastfetch', ['sh', str(query_script)], preview_env)
        for index, rgb in enumerate(((154, 72, 214), (40, 185, 120)), 1):
            sample = root / ('wallpaper-' + str(index) + '.png')
            image(sample, rgb)
            changed = True
            run('noctalia', 'msg', 'wallpaper-set', str(sample))
            palette = wait_theme(source, str(sample), original['revision'] if not revisions else revisions[-1])
            if index == 1 and palette['colors'] == original['colors']:
                raise RuntimeError('wallpaper did not change semantic colors')
            canonical.write_text(json.dumps(palette))
            command('apply')
            theme_bytes = terminal_palette(palette)
            native_hashes.append(hashlib.sha256(theme_bytes).hexdigest())
            existing_theme = Path(original_env.get('XDG_CONFIG_HOME') or str(Path(original_env['HOME']) / '.config')) / 'kitty/themes/noctalia.conf'
            if existing_theme.is_file():
                if existing_theme.read_bytes() != theme_bytes:
                    raise RuntimeError('existing desktop Kitty output differs from Noctalia native rendering')
                existing_kitty_parity.append(True)
            os.kill(term_proc.pid, signal.SIGUSR1)
            (root / 'query-request').touch()
            deadline = time.monotonic() + 6
            while (root / 'query-request').exists() and time.monotonic() < deadline:
                time.sleep(.1)
            query = (root / 'query.txt').read_text()
            values = dict(line.split(': ', 1) for line in query.strip().splitlines())
            # Extract native file colors, not inferred from schema-only evidence.
            import re
            native_options = dict(re.findall(r'^(foreground|background)\s+(\S+)', include.read_text(), re.M))
            if any(values.get(k) != v for k, v in native_options.items()):
                raise RuntimeError('running Kitty query differs from native theme')
            query_results.append(values)
            revisions.append(palette['revision'])
            time.sleep(.5)
            screenshot(term_id, 'kitty-fastfetch-' + str(index))
            control = root / ('codex-control-' + str(index) + '.sock')
            codex_proc, codex_id = launch('Codex', codex_args, codex_env, control)
            time.sleep(2)
            run('kitty', '@', '--to', 'unix:' + str(control), 'send-text', '--bracketed-paste=disable', '/theme')
            time.sleep(.3)
            run('kitty', '@', '--to', 'unix:' + str(control), 'send-key', 'enter')
            time.sleep(1)
            screenshot(codex_id, 'codex-' + str(index))
            codex_proc.terminate()
            codex_proc.wait(timeout=6)
        if len(set(native_hashes)) != 2:
            raise RuntimeError('two wallpaper colors did not differ')
    finally:
        for proc in windows:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        if changed:
            run('noctalia', 'msg', 'wallpaper-set', wallpaper)
            restored = wait_theme(source, wallpaper)
            if restored['mode'] != original['mode'] or restored['colors'] != original['colors']:
                raise RuntimeError('original palette restoration mismatch')
            for path, before in config_before.items():
                if path.read_bytes() != before:
                    old, new = tomllib.loads(before.decode()), tomllib.loads(path.read_text())
                    old.pop('wallpaper', None)
                    new.pop('wallpaper', None)
                    if old != new:
                        raise RuntimeError('concurrent preference change; retained for review')
                    with path.open('wb') as stream:
                        stream.write(before)
                        stream.flush()
                        os.fsync(stream.fileno())
        command('rollback')
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != digest for p, digest in hashes.items()):
            raise RuntimeError('protected desktop configuration changed')
    print(json.dumps({'wallpaper_cycles': len(revisions), 'native_kitty_query_matches': len(query_results), 'existing_kitty_theme_parity': len(existing_kitty_parity),
                      'fastfetch_native_exit': 'view screenshots; visual review required',
                      'codex_native_tui': 'view screenshots; syntax preview review required',
                      'protected_configuration_unchanged': True, 'original_palette_restored': changed,
                      'public_adapter_installation': 'isolated HOME only', 'evidence_directory': str(root)}, indent=2))


if __name__ == '__main__':
    main()
