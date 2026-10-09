import copy
import json
import os
import tempfile
import plistlib
import unittest
from unittest.mock import patch

from noctalia_theme_sync import adapters, diagnostics, jsonc, native, xdg
from noctalia_theme_sync.model import atomic_json
import test_product
from test_product import fixture


class NativeLifecycleTests(test_product.ProductTests):
    # Reuse the isolated transaction harness without duplicating inherited tests.
    def setUp(self):
        super().setUp()
        self.codex_env = patch.dict(os.environ, {'CODEX_HOME': str(self.root / 'custom-codex')})
        self.codex_env.start()
        self.codex_version = patch('noctalia_theme_sync.native.codex_version', return_value={'version': (0, 160, 1), 'compatible': True, 'reason': 'native'})
        self.codex_version.start()
        self.ff_version = patch('noctalia_theme_sync.native.fastfetch_version', return_value={'version': (2, 63, 1), 'compatible': True})
        self.ff_version.start()

    def tearDown(self):
        self.ff_version.stop()
        self.codex_version.stop()
        self.codex_env.stop()
        super().tearDown()

    def test_native_lifecycle_preserves_configs_pet_auth_and_modes(self):
        for name in ('fastfetch', 'codex', 'fastfetch,codex,kitty'):
            ff = native.fastfetch_path()
            cx = adapters.target('codex/config.toml')
            ff_original = b'{//keep comment\n"logo":{"source":"custom.txt","padding":{"left":4}},"display":{"separator":" => "},"modules":["os", {"type":"memory","keyColor":"red"}],}\n'
            cx_original = b'model="custom"\nsandbox_mode="workspace-write"\n[tui]\npet="custom:unchanged"\ntheme="old" # keep comment\n[other]\nvalue=12\n'
            xdg.write(ff, ff_original, 0o640)
            xdg.write(cx, cx_original)
            # Sentinel data are never read/written by the adapter.
            auth = xdg.codex_home() / 'auth.json'
            pet = xdg.codex_home() / 'pets/original/asset.txt'
            auth.write_bytes(b'private sentinel')
            pet.parent.mkdir(parents=True, exist_ok=True)
            pet.write_bytes(b'pet sentinel')
            self.install(name, '--experimental')
            first = self.snapshot()
            self.install(name, '--experimental')
            self.assertEqual(self.snapshot(), first)
            for mode in ('dark', 'light'):
                for accent in ('#bb88dd', '#33aa77'):
                    palette = fixture(mode, accent)
                    atomic_json(xdg.canonical() / 'current.json', palette)
                    self.assertEqual(self.call('apply'), 0)
                    if 'fastfetch' in name:
                        parsed = jsonc.parse(ff.read_text()).value
                        self.assertEqual(parsed['display']['color']['keys'], accent)
                        self.assertEqual(parsed['modules'], jsonc.parse(ff_original.decode()).value['modules'])
                        self.assertIn(b'//keep comment', ff.read_bytes())
                        self.assertEqual(parsed['logo']['source'], 'custom.txt')
                    if 'codex' in name:
                        value = plistlib.loads(adapters.target('codex/themes/noctalia-theme-sync.tmTheme').read_bytes())
                        self.assertEqual(value['settings'][0]['settings']['foreground'], palette['colors']['on_surface'])
                        self.assertIn(b'pet="custom:unchanged"', cx.read_bytes())
                        self.assertIn(b'# keep comment', cx.read_bytes())
            self.assertEqual(auth.read_bytes(), b'private sentinel')
            self.assertEqual(pet.read_bytes(), b'pet sentinel')
            self.assertEqual(self.call('rollback'), 0)
            self.assertEqual(ff.read_bytes(), ff_original)
            self.assertEqual(cx.read_bytes(), cx_original)
            self.assertEqual(ff.stat().st_mode & 0o777, 0o640)

    def test_custom_fastfetch_path_and_edited_config_conflict(self):
        custom = xdg.base('config') / 'fastfetch/custom.jsonc'
        with patch.dict(os.environ, {'NTS_FASTFETCH_CONFIG': str(custom)}):
            self.install('fastfetch')
            custom.write_bytes(custom.read_bytes() + b'//user change\n')
            before = self.snapshot()
            self.assertEqual(self.call('apply'), 1)
            self.assertEqual(self.call('uninstall'), 1)
            self.assertEqual(before, self.snapshot())

    def test_no_config_and_independent_disable(self):
        self.install('fastfetch,codex', '--experimental')
        self.assertTrue(native.fastfetch_path().exists())
        self.assertEqual(self.call('disable', '--adapters', 'codex'), 0)
        self.assertFalse(adapters.target('codex/config.toml').exists())
        self.assertTrue(native.fastfetch_path().exists())
        self.assertEqual(self.call('uninstall'), 0)
        self.assertFalse(native.fastfetch_path().exists())

    def test_codex_native_config_edits_preserved_on_apply_uninstall(self):
        path = adapters.target('codex/config.toml')
        original = b'model="original"\n[tui]\npet="original"\ntheme="old"\n'
        xdg.write(path, original)
        self.install('codex', '--experimental')
        path.write_bytes(path.read_bytes().replace(b'model="original"', b'model="changed-by-user"') + b'\n[features]\nnew_setting=true\n')
        self.assertEqual(self.call('apply'), 0)
        self.assertEqual(self.call('uninstall'), 0)
        self.assertIn(b'model="changed-by-user"', path.read_bytes())
        self.assertIn(b'new_setting=true', path.read_bytes())
        self.assertIn(b'theme="old"', path.read_bytes())
        self.install('codex', '--experimental')
        path.write_bytes(path.read_bytes().replace(b'noctalia-theme-sync', b'another-choice'))
        before = self.snapshot()
        self.assertEqual(self.call('apply'), 1)
        self.assertEqual(self.call('rollback'), 1)
        self.assertEqual(before, self.snapshot())

    def test_codex_user_comments_survive_apply_and_uninstall(self):
        path = adapters.target('codex/config.toml')
        xdg.write(path, b'[tui]\ntheme="old"\n')
        self.install('codex', '--experimental')
        path.write_bytes(path.read_bytes() + b'# new user comment\n')
        self.assertEqual(self.call('apply'), 0)
        self.assertEqual(self.call('rollback'), 0)
        self.assertIn(b'# new user comment', path.read_bytes())
        self.assertIn(b'theme="old"', path.read_bytes())

    def test_codex_new_preferences_after_absent_config_are_kept(self):
        self.install('codex', '--experimental')
        path = adapters.target('codex/config.toml')
        path.write_bytes(path.read_bytes() + b'pet="added-later"\n')
        self.assertEqual(self.call('rollback'), 0)
        self.assertIn(b'pet="added-later"', path.read_bytes())
        self.assertNotIn(b'theme', path.read_bytes())

    def test_native_targets_survive_hook_environment(self):
        self.install('fastfetch,codex', '--experimental')
        root = xdg.codex_home()
        ff = native.fastfetch_path()
        with patch.dict(os.environ, {'CODEX_HOME': str(self.root / 'other-codex'), 'NTS_FASTFETCH_CONFIG': str(self.root / 'config/other-fetch.jsonc')}):
            self.assertEqual(self.call('apply'), 0)
            self.assertFalse((self.root / 'other-codex').exists())
            self.assertFalse((self.root / 'config/other-fetch.jsonc').exists())
            self.assertEqual(self.call('rollback'), 0)
        self.assertFalse((root / 'config.toml').exists())
        self.assertFalse(ff.exists())

    def test_native_install_before_export_then_apply(self):
        (xdg.canonical() / 'current.json').unlink()
        self.install('fastfetch,codex', '--experimental')
        self.assertEqual(jsonc.parse(native.fastfetch_path().read_text()).value['display']['color']['keys'], 'blue')
        self.assertFalse(adapters.target('codex/themes/noctalia-theme-sync.tmTheme').exists())
        atomic_json(xdg.canonical() / 'current.json', self.p)
        self.assertEqual(self.call('apply'), 0)
        self.assertEqual(jsonc.parse(native.fastfetch_path().read_text()).value['display']['color']['keys'], self.p['colors']['primary'])
        self.assertTrue(adapters.target('codex/themes/noctalia-theme-sync.tmTheme').exists())
        self.assertEqual(self.call('rollback'), 0)

    def test_codex_incompatible_plan_no_writes(self):
        before = self.snapshot()
        with patch('noctalia_theme_sync.native.codex_version', return_value={'compatible': False, 'reason': 'unsupported version'}):
            self.assertEqual(self.call('plan', '--adapters', 'codex', '--experimental'), 1)
        self.assertEqual(before, self.snapshot())

    def test_codex_scope_and_symlinks(self):
        for relative in ('auth.json', 'pets/pet.json', 'themes/personal.tmTheme'):
            with self.assertRaises(ValueError):
                xdg.safe(xdg.codex_home() / relative)
        with patch.dict(os.environ, {'CODEX_HOME': 'relative'}):
            with self.assertRaises(ValueError):
                xdg.codex_home()
        root = xdg.codex_home()
        root.mkdir()
        (root / 'themes').symlink_to(self.root)
        with self.assertRaises(ValueError):
            adapters.target('codex/themes/noctalia-theme-sync.tmTheme')

    def test_kitty_effective_overrides_are_reported(self):
        self.install('kitty')
        path = adapters.target('config/kitty/kitty.conf')
        path.write_bytes(path.read_bytes() + b'foreground #010203\n')
        report = diagnostics.states(__import__('noctalia_theme_sync.transaction', fromlist=['load']).load(), self.p)['kitty']
        self.assertTrue(report['active'])
        self.assertFalse(report['palette_applied'])
        self.assertEqual(report['running_palette'], 'unverified')


# Only new lifecycle tests; avoid re-running the inherited baseline suite.
for name in list(vars(test_product.ProductTests)):
    if name.startswith('test_'):
        setattr(NativeLifecycleTests, name, None)


class NativeFormatTests(unittest.TestCase):
    def test_jsonc_nested_comments_trailing_and_ambiguous_inputs(self):
        text = '{"a":{"b": [1,2,], /* retained */}, "modules":[{"type":"custom", "format":"// hi \\\""}],}'
        result = jsonc.set_value(text, ('a', 'color'), '#123456')
        self.assertIn('/* retained */', result)
        self.assertIn('"modules":[{"type":"custom"', result)
        self.assertEqual(jsonc.parse(result).value['a']['color'], '#123456')
        for bad in ('{"a":1,"a":2}', '{/*broken}', '{"a":1 garbage}', '{"a":01}', '[1]', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                jsonc.parse(bad)
        with self.assertRaises(ValueError):
            jsonc.set_value('{"display":false}', ('display', 'color'), {})

    def test_native_theme_only_preservation(self):
        import tomllib
        for text in ('', '#keep\nmodel="custom"\n', '[tui]\npet="old"\n', '[tui]', '[tui]\ntheme="old" # keep\n[features]\nfoo=true\n'):
            old = tomllib.loads(text)
            expected = copy.deepcopy(old)
            expected.setdefault('tui', {})['theme'] = native.THEME
            out = native.codex_theme(text.encode()).decode()
            self.assertEqual(tomllib.loads(out), expected)
            self.assertEqual(native.codex_theme(out.encode()), out.encode())
        for bad in ('tui={theme="old",pet="x"}', 'tui.theme="old"', '[tui]\ntheme="""old"""'):
            with self.assertRaises(ValueError):
                native.codex_theme(bad.encode())

    def test_codex_capability_old_version_and_privileged_wrapper(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            binary = __import__('pathlib').Path(temporary) / 'codex'
            binary.write_bytes(b'\x7fELFfixture')
            with patch.dict(os.environ, {'NTS_CODEX_BIN': str(binary)}):
                for version, supported in [('0.159.0', False), ('0.160.1', True), ('invalid', False)]:
                    with patch('noctalia_theme_sync.native.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'codex-cli ' + version, '')):
                        self.assertEqual(native.codex_version()['compatible'], supported)
                binary.write_text('#!/bin/sh\nexec sudo codex-vpn --version\n')
                with patch('noctalia_theme_sync.native.subprocess.run') as execute:
                    self.assertFalse(native.codex_version()['compatible'])
                    execute.assert_not_called()

    def test_fastfetch_disabled_and_string_logo(self):
        for logo in (None, 'my-braille.txt'):
            source = json.dumps({'logo': logo, 'modules': ['os']}).encode()
            result = jsonc.parse(native.fastfetch_config(source, fixture()).decode()).value
            self.assertEqual(result['modules'], ['os'])
            if logo is None:
                self.assertIsNone(result['logo'])
            else:
                self.assertEqual(result['logo']['source'], logo)


if __name__ == '__main__':
    unittest.main()
