#!/usr/bin/env python3
"""Run a real Noctalia v5 template→publisher→adapters pipeline in isolated XDG."""
import json
import os
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='nts-native-smoke-') as tmp:
        root = Path(tmp)
        env = dict(os.environ, GSETTINGS_BACKEND='memory', DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(root / 'absent-bus'), XDG_RUNTIME_DIR=str(root / 'runtime'), HOME=str(root / 'home'), NTS_BIN_HOME=str(root / 'bin'),
                   **{'XDG_' + k.upper() + '_HOME': str(root / k) for k in ('config', 'state', 'data', 'cache')})
        (root / 'runtime').mkdir(mode=0o700)
        (root / 'config/noctalia').mkdir(parents=True)
        def run(*args):
            r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
            if r.returncode:
                raise RuntimeError(r.stderr + r.stdout)
            return r.stdout
        run(str(ROOT / 'bin/noctalia-theme-sync'), 'install', '--adapters', 'kitty,gtk,qt,neovim,btop,cava')
        fragment = root / 'config/noctalia/noctalia-theme-sync.toml'
        entries = tomllib.loads(fragment.read_text())['theme']['templates']['user']
        # Offline -c uses [templates], live Noctalia uses [theme.templates.user].
        standalone = root / 'standalone.toml'
        standalone.write_text('\n'.join('[templates.' + name + ']\n' + '\n'.join(k + ' = ' + (str(v).lower() if isinstance(v, bool) else json.dumps(v)) for k, v in values.items()) for name, values in entries.items()))
        revisions = []
        for name in ('dark-purple', 'dark-green', 'light-purple', 'light-green'):
            palette = json.loads((ROOT / 'tests/fixtures' / (name + '.json')).read_text())
            native = root / 'native.json'
            native.write_text(json.dumps({'dark': palette['colors'], 'light': palette['colors']}))
            run('noctalia', 'theme', '--theme-json', str(native), '--default-mode', palette['mode'], '-c', str(standalone))
            current = json.loads((root / 'state/noctalia/theme-sync/current.json').read_text())
            assert current['colors']['primary'] == palette['colors']['primary']
            assert current['mode'] == palette['mode']
            revisions.append(current['revision'])
            kitty = root / 'config/kitty/themes/noctalia-theme-sync.conf'
            assert palette['colors']['primary'] in kitty.read_text()
            run('noctalia', 'theme', '--theme-json', str(native), '--default-mode', palette['mode'], '-c', str(standalone))
            assert json.loads((root / 'state/noctalia/theme-sync/current.json').read_text())['revision'] == revisions[-1]
        assert revisions == [1, 2, 3, 4]
        run(str(root / 'bin/noctalia-theme-sync'), 'uninstall')
        print('Native Noctalia v5 smoke: PASS (export/hook/revision/idempotence/adapters/dark/light/uninstall)')


if __name__ == '__main__':
    main()
