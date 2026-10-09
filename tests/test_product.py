import contextlib
import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from noctalia_theme_sync import adapters, cli, transaction as tx, xdg
from noctalia_theme_sync.model import ROLES, atomic_json, config, validate


def fixture(mode='dark', accent='#bb88dd'):
    colors = {role: '#223344' for role in ROLES}
    colors.update(primary=accent, on_primary='#111111', hover=accent, on_hover='#111111', surface='#151515' if mode == 'dark' else '#fafafa',
                  on_surface='#eeeeee' if mode == 'dark' else '#161616')
    import re
    colors.update({role: colors['on_surface'] for role in re.findall(r'colors\.(terminal_\w+)\.default', adapters.assets().joinpath('adapters/kitty.conf').read_text())})
    return {'schema_version': 1, 'revision': 1, 'generated_at': '2026-01-01T00:00:00Z', 'mode': mode, 'wallpaper': '', 'colors': colors}


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {'HOME': str(self.root / 'home'), **{'XDG_' + k.upper() + '_HOME': str(self.root / k) for k in ('config', 'data', 'state', 'cache')}, 'NTS_BIN_HOME': str(self.root / 'bin')}
        self.environ = patch.dict(os.environ, self.env)
        self.environ.start()
        self.version = patch('noctalia_theme_sync.cli.noctalia_version', return_value=(5, 2, 1))
        self.version.start()
        (xdg.base('config') / 'noctalia').mkdir(parents=True)
        self.p = fixture()
        atomic_json(xdg.canonical() / 'current.json', self.p)

    def tearDown(self):
        self.version.stop()
        self.environ.stop()
        self.tmp.cleanup()

    def call(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(argv)

    def install(self, names='kitty,gtk,qt,btop,cava,neovim', *extra):
        self.assertEqual(self.call('install', '--adapters', names, *extra), 0)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mode & 0o777, p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}

    def test_install_repeat_update_apply_uninstall_originals(self):
        original = b'# Keep me\nfont_size 13\n'
        kitty = adapters.target('config/kitty/kitty.conf')
        xdg.write(kitty, original, 0o640)
        self.install()
        self.assertEqual(kitty.read_bytes().count(b'noctalia-theme-sync begin kitty'), 1)
        first = self.snapshot()
        self.install()
        self.assertEqual(self.snapshot(), first)
        self.assertEqual(self.call('update'), 0)
        self.assertEqual(self.snapshot(), first)
        palette = self.root / 'light.json'
        atomic_json(palette, fixture('light', '#447799'))
        self.assertEqual(self.call('apply', '--palette', str(palette)), 0)
        self.assertIn(b'#447799', adapters.target('config/kitty/themes/noctalia-theme-sync.conf').read_bytes())
        self.assertIn(b'gtk-application-prefer-dark-theme=0', adapters.target('config/gtk-3.0/settings.ini').read_bytes())
        self.assertEqual(self.call('uninstall'), 0)
        self.assertEqual(kitty.read_bytes(), original)
        self.assertEqual(kitty.stat().st_mode & 0o777, 0o640)
        self.assertFalse(adapters.target('config/kitty/themes/noctalia-theme-sync.conf').exists())
        self.assertEqual(tx.load()['files'], {})
        self.assertTrue(list((xdg.state() / 'backups').glob('original-*.json')))
        self.assertEqual(self.call('uninstall'), 0)

    def test_dry_run_no_writes(self):
        before = self.snapshot()
        self.assertEqual(self.call('plan', '--adapters', 'kitty'), 0)
        self.assertEqual(self.call('install', '--adapters', 'kitty', '--dry-run'), 0)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(xdg.state().exists())
        self.install('kitty')
        before = self.snapshot()
        for args in [('apply', '--dry-run'), ('sync', '--dry-run'), ('update', '--dry-run'), ('uninstall', '--dry-run'), ('rollback', '--dry-run')]:
            self.assertEqual(self.call(*args), 0)
            self.assertEqual(self.snapshot(), before)

    def test_safe_conflicts_symlink_and_edited_files(self):
        path = adapters.target('config/kitty/kitty.conf')
        external = self.root / 'unowned.conf'
        external.write_text('font_size 12\n')
        path.parent.mkdir(parents=True)
        path.symlink_to(external)
        self.assertEqual(self.call('install', '--adapters', 'kitty'), 1)
        self.assertEqual(external.read_text(), 'font_size 12\n')
        self.assertFalse(xdg.state().exists())
        path.unlink()
        self.install('kitty')
        path.write_bytes(path.read_bytes() + b'# User change\n')
        before = self.snapshot()
        self.assertEqual(self.call('apply'), 1)
        self.assertEqual(self.call('uninstall'), 1)
        self.assertEqual(self.snapshot(), before)

    def test_adoption_restores_existing_generated_file(self):
        p = adapters.target('config/nvim/colors/noctalia.lua')
        xdg.write(p, b'-- previous theme\n')
        self.assertEqual(self.call('install', '--adapters', 'neovim'), 1)
        plan = str(self.root / 'reviewed.json')
        self.assertEqual(self.call('plan', '--adapters', 'neovim', '--adopt-existing', '--write-plan', plan), 0)
        self.install('neovim', '--adopt-existing', '--from-plan', plan)
        self.assertEqual(self.call('rollback'), 0)
        self.assertEqual(p.read_bytes(), b'-- previous theme\n')

    def test_partial_disable_independent_adapters(self):
        self.install('kitty,neovim,btop')
        self.assertEqual(self.call('disable', '--adapters', 'neovim'), 0)
        self.assertEqual(set(tx.load()['adapters']), {'kitty', 'btop'})
        self.assertFalse(adapters.target('config/nvim/colors/noctalia.lua').exists())
        self.assertTrue(adapters.target('config/kitty/themes/noctalia-theme-sync.conf').exists())
        self.assertEqual(self.call('apply'), 0)

    def test_failed_transaction_rolls_back(self):
        self.install('kitty')
        before = self.snapshot()
        original = xdg.write
        def fail(path, data, mode=0o600):
            if str(path).endswith('kitty/kitty.conf') and data == b'new\n':
                raise OSError('injected failure')
            return original(path, data, mode)
        with patch('noctalia_theme_sync.xdg.write', side_effect=fail):
            with self.assertRaises(OSError):
                tx.commit(tx.load(), {str(adapters.target('config/kitty/themes/noctalia-theme-sync.conf')): b'changed\n', str(adapters.target('config/kitty/kitty.conf')): b'new\n'})
        after = self.snapshot()
        self.assertEqual({k: v[:2] for k, v in after.items()}, {k: v[:2] for k, v in before.items()})
        self.assertFalse((xdg.state() / 'pending.json').exists())

    def test_recovery_preserves_external_edits(self):
        p = adapters.target('config/kitty/kitty.conf')
        xdg.write(p, b'old')
        journal = {'before': {str(p): {'data': tx.encode(b'old'), 'mode': 0o600}}, 'after': {str(p): xdg.digest(b'new')}, 'manifest': None}
        atomic_json(xdg.state() / 'pending.json', journal)
        xdg.write(p, b'external')
        with self.assertRaises(ValueError):
            tx.recover()
        self.assertEqual(p.read_bytes(), b'external')
        xdg.write(p, b'new')
        self.assertTrue(tx.recover())
        self.assertEqual(p.read_bytes(), b'old')

    def test_experimental_opt_in_and_no_profile_access(self):
        self.assertEqual(self.call('install', '--adapters', 'telegram'), 1)
        self.install('telegram,vesktop,steam', '--experimental')
        self.assertFalse((xdg.base('data') / 'TelegramDesktop/tdata').exists())
        self.assertFalse((Path.home() / '.mozilla').exists())
        self.assertEqual(self.call('update'), 0)

    def test_builtin_and_publisher_conflicts(self):
        path = xdg.base('config') / 'noctalia/theme.toml'
        path.write_text('[theme.templates]\nenable_builtin_templates = true\nbuiltin_ids = ["kitty"]\n')
        self.assertEqual(self.call('install', '--adapters', 'kitty'), 1)
        path.write_text('[theme.templates.user.original]\noutput_path = "$XDG_STATE_HOME/noctalia/theme-sync/palette.json"\n')
        self.assertEqual(self.call('install', '--adapters', 'btop'), 1)
        self.install('btop', '--consume-existing')
        self.assertFalse((xdg.base('config') / 'noctalia/noctalia-theme-sync.toml').exists())
        self.install('btop')
        self.assertTrue(tx.load()['consume_existing'])

    def test_noctalia_toml_valid_and_runtime_cli(self):
        self.install('kitty')
        import tomllib
        d = tomllib.loads((xdg.base('config') / 'noctalia/noctalia-theme-sync.toml').read_text())
        self.assertFalse(d['theme']['templates']['user']['nts_palette']['hook_async'])
        result = subprocess.run([str(xdg.base('bin') / 'noctalia-theme-sync'), 'status'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['adapters'], ['kitty'])
        self.assertEqual((xdg.base('bin') / 'noctalia-theme-sync').stat().st_mode & 0o777, 0o755)

    def test_install_without_initial_export_and_later_apply(self):
        (xdg.canonical() / 'current.json').unlink()
        self.install('kitty')
        self.assertFalse(adapters.target('config/kitty/themes/noctalia-theme-sync.conf').exists())
        atomic_json(xdg.canonical() / 'current.json', self.p)
        self.assertEqual(self.call('apply'), 0)
        self.assertTrue(adapters.target('config/kitty/themes/noctalia-theme-sync.conf').exists())

    def test_doctor_and_unavailable_adapters(self):
        self.assertEqual(self.call('doctor'), 0)
        self.assertEqual(self.call('install', '--adapters', 'affine'), 1)
        self.assertEqual(self.call('install', '--adapters', 'unknown'), 1)
        with patch('noctalia_theme_sync.cli.noctalia_version', return_value=(4, 5, 0)):
            self.assertEqual(self.call('doctor'), 1)
            self.assertEqual(self.call('install', '--adapters', 'kitty'), 1)

    def test_hardlinks_and_relative_xdg_rejected(self):
        external = self.root / 'external'
        external.write_text('external')
        p = adapters.target('config/kitty/kitty.conf')
        p.parent.mkdir(parents=True)
        os.link(external, p)
        self.assertEqual(self.call('install', '--adapters', 'kitty'), 1)
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': 'relative'}):
            with self.assertRaises(ValueError):
                xdg.base('config')

    def test_ini_preserves_comments_and_unrelated_keys(self):
        old = b'# comment\n[Settings]\nfont=Inter\nfoo=bar\n[Other]\nx=1\n'
        new = adapters.ini(old, 'Settings', {'foo': 'baz'})
        self.assertEqual(new, old.replace(b'foo=bar', b'foo=baz'))
        with self.assertRaises(ValueError):
            adapters.ini(b'[Settings]\nx=1\n[Settings]\nx=2\n', 'Settings', {'x': '3'})


class ContractTests(unittest.TestCase):
    def test_all_adapters_four_palettes(self):
        for mode in ('dark', 'light'):
            for accent in ('#bb88dd', '#33aa77'):
                p = fixture(mode, accent)
                for item in adapters.registry().values():
                    for output in item['outputs']:
                        template = adapters.assets().joinpath('adapters', output['template']).read_text()
                        result = adapters.render(template, p)
                        self.assertNotIn(b'{{', result)
                        self.assertIn(accent.encode(), result)

    def test_schema_compatibility(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('jsonschema is a development dependency (CI installs it)')
        schema = json.loads(adapters.assets().joinpath('schema-v1.json').read_text())
        for mode in ('dark', 'light'):
            jsonschema.validate(fixture(mode), schema)

    def test_malformed_inputs(self):
        good = fixture()
        for key, bad in [('schema_version', True), ('revision', True), ('revision', 0), ('mode', 'auto'), ('wallpaper', '../secret'), ('generated_at', '2026-01-01')]:
            p = copy.deepcopy(good)
            p[key] = bad
            with self.assertRaises(ValueError):
                validate(p)
        p = copy.deepcopy(good)
        p['colors']['primary'] = '#fff; run malicious command'
        with self.assertRaises(ValueError):
            adapters.render('{{ colors.primary.default.hex }}', p)
        with self.assertRaises(ValueError):
            adapters.render('{{ image }}', good)
        with self.assertRaises(ValueError):
            adapters.target('config/../outside')

    def test_wallpaper_opt_in_default(self):
        self.assertEqual(config('/nonexistent-nts-fixture.json')['wallpaper_roots'], [])
        self.assertEqual(config('/nonexistent-nts-fixture.json')['bind'], '127.0.0.1')


if __name__ == '__main__':
    unittest.main()
