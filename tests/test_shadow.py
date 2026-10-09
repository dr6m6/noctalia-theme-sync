import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import unittest
import threading
from unittest.mock import patch

from noctalia_theme_sync import shadow, transaction as tx, xdg
from noctalia_theme_sync.model import atomic_json
import test_product as product


class ShadowTests(unittest.TestCase):
    setUp = product.ProductTests.setUp
    tearDown = product.ProductTests.tearDown
    call = product.ProductTests.call

    def prepare(self):
        self.shadow_root = self.root / 'shadow'
        self.review = self.root / 'shadow-plan.json'
        self.original = xdg.base('config') / 'nvim/colors/noctalia.lua'
        xdg.write(self.original, b'-- personal theme kept\n', 0o640)
        self.fragment = xdg.base('config') / 'noctalia/templates.toml'
        self.fragment.write_text('[theme.templates.user.neovim]\ninput_path="personal/neovim.lua"\n'
                                 'output_path="$XDG_CONFIG_HOME/nvim/colors/noctalia.lua"\n')
        self.production = {str(p): (p.read_bytes(), p.stat().st_mode & 0o777, p.stat().st_mtime_ns)
                           for p in self.root.rglob('*') if p.is_file()}

    def invoke(self, action, *extra):
        return self.call('shadow', action, '--root', str(self.shadow_root), *extra)

    def install(self):
        self.assertEqual(self.invoke('plan', '--write-plan', str(self.review)), 0)
        self.assertFalse(self.shadow_root.exists())
        self.assertEqual(self.invoke('install', '--from-plan', str(self.review)), 0)

    def unchanged(self):
        for name, before in self.production.items():
            p = Path(name)
            self.assertEqual((p.read_bytes(), p.stat().st_mode & 0o777, p.stat().st_mtime_ns), before)

    def test_personal_writer_coexists_repeat_and_rollback(self):
        self.prepare()
        self.install()
        with shadow.context(self.shadow_root):
            output = shadow.target()
            before = output.stat().st_mtime_ns
            self.assertIn(b'colors_name = "noctalia-nts"', output.read_bytes())
            self.assertEqual(set(tx.load()['files']), {str(output)})
        self.assertEqual(self.invoke('plan', '--write-plan', str(self.root / 'repeat.json')), 0)
        self.assertEqual(self.invoke('install', '--from-plan', str(self.root / 'repeat.json')), 0)
        self.assertEqual(output.stat().st_mtime_ns, before)
        self.assertEqual(self.invoke('status'), 0)
        self.assertEqual(self.invoke('uninstall', '--dry-run'), 0)
        self.assertEqual(self.invoke('rollback'), 0)
        self.assertFalse(output.exists())
        with shadow.context(self.shadow_root):
            self.assertEqual(tx.load()['files'], {})
            self.assertTrue(list((xdg.state() / 'backups').glob('original-*.json')))
        self.unchanged()

    def test_no_install_without_review_no_foreign_adoption(self):
        self.prepare()
        self.assertEqual(self.invoke('install'), 1)
        self.assertFalse(self.shadow_root.exists())
        with shadow.context(self.shadow_root):
            xdg.write(shadow.target(), b'-- another owner\n')
            output = shadow.target()
        self.assertEqual(self.invoke('plan'), 1)
        self.assertEqual(output.read_bytes(), b'-- another owner\n')
        self.unchanged()

    def test_plan_palette_drift_and_mode_drift(self):
        self.prepare()
        self.assertEqual(self.invoke('plan', '--write-plan', str(self.review)), 0)
        atomic_json(xdg.canonical() / 'current.json', product.fixture('light'))
        self.assertEqual(self.invoke('install', '--from-plan', str(self.review)), 1)
        self.assertFalse(self.shadow_root.exists())
        self.review = self.root / 'fresh.json'
        self.install()
        with shadow.context(self.shadow_root):
            output = shadow.target()
            output.chmod(0o640)
        self.assertEqual(self.invoke('apply'), 1)
        self.assertEqual(self.invoke('uninstall'), 1)
        self.assertEqual(output.stat().st_mode & 0o777, 0o640)

    def test_unexpected_manifest_targets_refuse_every_write(self):
        self.prepare()
        self.install()
        with shadow.context(self.shadow_root):
            m = tx.load()
            unknown = xdg.base('config') / 'noctalia/unknown.toml'
            xdg.write(unknown, b'preserve')
            m['files'][str(unknown)] = {'original': None, 'installed_sha256': xdg.digest(b'preserve')}
            xdg.write(tx.manifest_path(), json.dumps(m).encode())
            before = tx.manifest_path().read_bytes()
        for action in ('plan', 'apply', 'uninstall', 'rollback'):
            self.assertEqual(self.invoke(action), 1)
        self.assertEqual(unknown.read_bytes(), b'preserve')
        with shadow.context(self.shadow_root):
            self.assertEqual(tx.manifest_path().read_bytes(), before)
        self.unchanged()

    def test_broken_symlink_and_production_root_refused(self):
        self.prepare()
        for root in (xdg.base('config') / 'noctalia', xdg.base('config') / 'nvim', self.root):
            self.assertEqual(self.call('shadow', 'plan', '--root', str(root)), 1)
        self.shadow_root.symlink_to(self.root / 'absent')
        self.assertEqual(self.invoke('install'), 1)
        self.unchanged()

    def test_interrupted_transaction_recovery_preserves_unknown_edits(self):
        self.prepare()
        self.install()
        with shadow.context(self.shadow_root):
            output = shadow.target()
            original = output.read_bytes()
            journal = {'before': {str(output): {'data': base64.b64encode(original).decode(), 'mode': 0o600}},
                       'after': {str(output): xdg.digest(b'interrupted')},
                       'manifest': base64.b64encode(tx.manifest_path().read_bytes()).decode()}
            xdg.write(output, b'interrupted')
            xdg.write(xdg.state() / 'pending.json', json.dumps(journal).encode())
        self.assertEqual(self.invoke('apply'), 1)
        self.assertEqual(self.invoke('rollback', '--recover'), 0)
        self.assertEqual(output.read_bytes(), original)
        with shadow.context(self.shadow_root):
            xdg.write(output, b'external edit')
            xdg.write(xdg.state() / 'pending.json', json.dumps(journal).encode())
        self.assertEqual(self.invoke('rollback', '--recover'), 1)
        self.assertEqual(output.read_bytes(), b'external edit')
        self.unchanged()

    def test_test_neovim_environment_has_no_real_init_or_ipc(self):
        self.prepare()
        self.install()
        def execute(command, **kw):
            env = kw['env']
            self.assertNotEqual(env['HOME'], os.environ['HOME'])
            self.assertNotIn('DBUS_SESSION_BUS_ADDRESS', env)
            self.assertNotIn('NIRI_SOCKET', env)
            self.assertIn('NONE', command)
            self.assertIn('--headless', command)
            class Result:
                returncode = 0
                stdout = '{"isolated":true}'
            return Result()
        with patch('noctalia_theme_sync.shadow.subprocess.run', side_effect=execute):
            self.assertEqual(self.invoke('test'), 0)
        self.unchanged()

    def test_consumer_lock_excludes_second_writer(self):
        self.prepare()
        self.install()
        with shadow.context(self.shadow_root):
            with shadow.consumer_lock(create=True):
                with self.assertRaises(ValueError):
                    with shadow.consumer_lock():
                        pass

    def test_sse_bounds_invalid_json_ids_and_endpoints(self):
        p = product.fixture()
        event = ('id: 1\nevent: theme\ndata: ' + json.dumps(p) + '\n\n').encode()
        self.assertEqual(list(shadow.frames(io.BytesIO(event))), [p])
        for raw in (event.replace(b'id: 1', b'id: 2'), b'data: '+b'x'*65536+b'\n\n',
                    event.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')):
            with self.assertRaises(ValueError):
                list(shadow.frames(io.BytesIO(raw)))
        for url in ('http://example.invalid/v1/events', 'http://127.0.0.1/v1/theme',
                    'http://127.0.0.1/v1/events?token=secret', 'https://127.0.0.1/v1/events'):
            with self.assertRaises(ValueError):
                shadow.endpoint(url)

    def test_shadow_state_cannot_activate_normal_adapters(self):
        self.prepare()
        self.install()
        with shadow.context(self.shadow_root):
            self.assertEqual(self.call('apply'), 1)
        self.unchanged()

    def stream(self, palettes):
        parent = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parent.assertEqual(self.path, '/v1/events')
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                for p in palettes:
                    self.wfile.write(('id: '+str(p['revision'])+'\nevent: theme\ndata: '+json.dumps(p)+'\n\n').encode())
                self.wfile.flush()

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:'+str(server.server_port)+'/v1/events'

    def test_real_sse_updates_only_shadow_on_two_palettes(self):
        self.prepare()
        self.install()
        p = product.fixture('light', '#44aa77')
        p['revision'] = 2
        url = self.stream([self.p, p])
        with patch('noctalia_theme_sync.cli.run', side_effect=AssertionError('unexpected native activation')):
            self.assertEqual(self.invoke('watch', '--events', url, '--max-events', '2'), 0)
        with shadow.context(self.shadow_root):
            self.assertEqual(shadow.target().read_bytes(), shadow.render(p))
            self.assertEqual(tx.load()['shadow']['event'], {'url': url, 'revision': 2})
        self.unchanged()

    def test_conflicting_sse_replay_stops_preserves_last_valid_output(self):
        self.prepare()
        self.install()
        p = product.fixture('light')  # Deliberately same revision, different semantic colors.
        self.assertEqual(self.invoke('watch', '--events', self.stream([self.p, p]), '--max-events', '2'), 1)
        with shadow.context(self.shadow_root):
            self.assertEqual(shadow.target().read_bytes(), shadow.render(self.p))
        self.unchanged()

    def test_declared_writer_collision_even_when_output_absent(self):
        self.prepare()
        output = self.shadow_root / 'config/nvim/colors/noctalia-nts.lua'
        self.fragment.write_text('[theme.templates.user.foreign]\noutput_path='+json.dumps(str(output))+'\n')
        self.assertEqual(self.invoke('plan'), 1)
        self.assertFalse(self.shadow_root.exists())

    def test_new_writer_collision_during_live_delivery_refuses_update(self):
        self.prepare()
        self.install()
        with shadow.context(self.shadow_root):
            output = shadow.target()
            original = output.read_bytes()
        self.fragment.write_text('[theme.templates.user.foreign]\noutput_path='+json.dumps(str(output))+'\n')
        p = product.fixture('light')
        p['revision'] = 2
        self.assertEqual(self.invoke('watch', '--events', self.stream([p]), '--max-events', '1'), 1)
        self.assertEqual(output.read_bytes(), original)

    def test_manual_fixture_clears_sse_resume_id(self):
        self.prepare()
        self.install()
        self.assertEqual(self.invoke('watch', '--events', self.stream([self.p]), '--max-events', '1'), 0)
        self.assertEqual(self.invoke('apply'), 0)
        with shadow.context(self.shadow_root):
            self.assertNotIn('event', tx.load()['shadow'])


if __name__ == '__main__':
    unittest.main()
