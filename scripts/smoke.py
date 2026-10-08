#!/usr/bin/env python3
"""Reproducible source/wheel CLI smoke test in a fresh HOME and relocated XDG."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='nts-smoke-') as tmp:
        root = Path(tmp)
        env = dict(os.environ, HOME=str(root / 'home'), NTS_BIN_HOME=str(root / 'bin'),
                   **{'XDG_' + k.upper() + '_HOME': str(root / k) for k in ('config', 'state', 'data', 'cache')})
        fake = root / 'tools'
        fake.mkdir()
        binary = fake / 'noctalia'
        binary.write_text('#!' + sys.executable + '\nimport sys\nprint("noctalia v5.2.1 (fixture)")\n')
        binary.chmod(0o755)
        env['PATH'] = str(fake) + ':' + env.get('PATH', '')
        (root / 'config/noctalia').mkdir(parents=True)
        palette = root / 'state/noctalia/theme-sync/current.json'
        palette.parent.mkdir(parents=True)
        palette.write_bytes((ROOT / 'tests/fixtures/dark-purple.json').read_bytes())
        command = [sys.executable, '-m', 'noctalia_theme_sync'] if '--installed' in sys.argv else [str(ROOT / 'bin/noctalia-theme-sync')]
        def call(*args, installed=False):
            argv = [str(root / 'bin/noctalia-theme-sync')] if installed else command
            result = subprocess.run([*argv, *args], env=env, text=True, capture_output=True, timeout=30)
            if result.returncode:
                raise RuntimeError(result.stderr + result.stdout)
            return result.stdout
        call('doctor')
        call('list')
        call('plan', '--adapters', 'kitty,gtk,qt,neovim,btop,cava')
        call('install', '--adapters', 'kitty,gtk,qt,neovim,btop,cava', '--dry-run')
        assert not (root / 'state/noctalia-theme-sync').exists()
        call('install', '--adapters', 'kitty,gtk,qt,neovim,btop,cava')
        call('install', '--adapters', 'kitty,gtk,qt,neovim,btop,cava', installed=True)
        call('update', installed=True)
        for name in ('dark-green', 'light-purple', 'light-green'):
            call('apply', '--palette', str(ROOT / 'tests/fixtures' / (name + '.json')), installed=True)
        assert json.loads(call('status', installed=True))['adapters']
        call('rollback', '--dry-run', installed=True)
        call('uninstall', installed=True)
        assert not (root / 'bin/noctalia-theme-sync').exists()
        call('uninstall')
        print('Isolated CLI smoke: PASS (doctor/plan/install/repeat/update/dark/light/rollback/uninstall)')


if __name__ == '__main__':
    main()
