import asyncio
import contextlib
import io
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from noctalia_theme_sync import cli, transaction as tx, xdg
from noctalia_theme_sync.bridge import Bridge
from noctalia_theme_sync.model import MAX_JSON, atomic_json, config, read_json
from test_product import fixture


class InputTests(unittest.TestCase):
    def test_duplicate_oversized_and_symlink_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'p.json'
            p.write_text('{"mode":"dark","mode":"light"}')
            with self.assertRaises(ValueError):
                read_json(p)
            p.write_text('{"value":NaN}')
            with self.assertRaises(ValueError):
                read_json(p)
            p.write_bytes(b' ' * (MAX_JSON + 1))
            with self.assertRaises(ValueError):
                read_json(p)
            real = Path(tmp) / 'real'
            real.write_text('original')
            p.unlink()
            p.symlink_to(real)
            with self.assertRaises(ValueError):
                atomic_json(p, {'value': 'replacement'})
            self.assertEqual(real.read_text(), 'original')

    def test_bridge_install_dryrun_and_busy_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {'HOME': str(root / 'home'), 'NTS_BIN_HOME': str(root / 'bin'), **{'XDG_' + k.upper() + '_HOME': str(root / k) for k in ('config', 'state', 'data', 'cache')}}
            with patch.dict(os.environ, env), patch('noctalia_theme_sync.cli.noctalia_version', return_value=(5, 2, 1)), patch('noctalia_theme_sync.cli.run') as command:
                command.return_value.returncode = 3  # no existing active systemd bridge
                (root / 'config/noctalia').mkdir(parents=True)
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    port = sock.getsockname()[1]
                    atomic_json(root / 'config/noctalia/theme-sync/bridge.json', {'port': port})
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(cli.main(['install', '--adapters', 'btop', '--bridge', '--dry-run']), 1)
                    self.assertFalse(xdg.state().exists())
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(['install', '--adapters', 'btop', '--bridge']), 0)
                    self.assertEqual(cli.main(['service', 'start', '--dry-run']), 0)
                unit = root / 'config/systemd/user/noctalia-theme-sync-bridge.service'
                self.assertIn(b'NoNewPrivileges=true', unit.read_bytes())
                self.assertTrue(tx.load()['bridge'])


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_start_health_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'state'
            atomic_json(state / 'current.json', fixture())
            configuration = root / 'bridge.json'
            atomic_json(configuration, {'port': 0, 'token_file': str(root / 'token'), 'wallpaper_roots': []})
            process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'noctalia_theme_sync', 'bridge', '--config', str(configuration), '--state', str(state), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                port = None
                for _ in range(5):
                    line = await asyncio.wait_for(process.stdout.readline(), 5)
                    event = json.loads(line)
                    if event.get('event') == 'listening':
                        port = event['port']
                        break
                self.assertIsNotNone(port)
                reader, writer = await asyncio.open_connection('127.0.0.1', port)
                writer.write(b'GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n')
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), 3)
                self.assertIn(b'200 OK', response)
                self.assertEqual(json.loads(response.split(b'\r\n\r\n')[1])['revision'], 1)
                writer.close()
                await writer.wait_closed()
                process.terminate()
                self.assertEqual(await asyncio.wait_for(process.wait(), 5), 0)
                with self.assertRaises(OSError):
                    await asyncio.open_connection('127.0.0.1', port)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

    async def test_failed_start_closes_inotify(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = config(root / 'missing')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                sock.listen()
                settings.update(port=sock.getsockname()[1], token_file=str(root / 'token'))
                bridge = Bridge(root / 'state', settings)
                with self.assertRaises(OSError):
                    await bridge.start()
                with self.assertRaises(OSError):
                    os.fstat(bridge.watcher.fd)
