"""Practical contract, real filesystem notification and HTTP/SSE tests."""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from noctalia_theme_sync.bridge import Bridge, token
from noctalia_theme_sync.model import ROLES, atomic_json, config, validate, wallpaper_file


def fixture(revision=1, primary='#112233'):
    return {'schema_version': 1, 'revision': revision, 'generated_at': '2026-10-07T20:00:00Z',
            'mode': 'dark', 'wallpaper': '', 'wallpaper_asset': None,
            'colors': {k: primary if k == 'primary' else '#000000' for k in ROLES}}


class Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.settings = config(self.root / 'missing.json')
        self.settings.update(port=0, debounce_ms=100, token_file=str(self.root / 'token'), wallpaper_roots=[str(self.root / 'walls')])
        self.bridge = Bridge(self.state, self.settings)
        await self.bridge.start()
        self.port = self.bridge.server.sockets[0].getsockname()[1]
        self.writers = []

    async def asyncTearDown(self):
        for w in self.writers:
            w.close()
            await w.wait_closed()
        await self.bridge.close()
        self.tmp.cleanup()

    async def request(self, route, auth=None, extra=''):
        r, w = await asyncio.open_connection('127.0.0.1', self.port)
        self.writers.append(w)
        headers = f'Authorization: Bearer {auth}\r\n' if auth else ''
        w.write(f'GET {route} HTTP/1.1\r\nHost: 127.0.0.1\r\n{headers}{extra}\r\n'.encode())
        await w.drain()
        header = await asyncio.wait_for(r.readuntil(b'\r\n\r\n'), 2)
        status = int(header.split()[1])
        if route == '/v1/events' and status == 200:
            return status, r
        body = await asyncio.wait_for(r.read(), 2)
        return status, body

    async def settle(self, bridge=None):
        # Wait for a real completed inotify reload, not a guessed fsync duration.
        bridge = bridge or self.bridge
        previous = bridge.last_check
        async def completed():
            while bridge.last_check == previous or bridge.pending is not None or bridge.reload_tasks:
                await asyncio.sleep(.01)
        await asyncio.wait_for(completed(), 5)

    async def event(self, reader):
        async def read():
            while True:
                line = await reader.readline()
                if line.startswith(b'data: '):
                    return validate(json.loads(line[6:]))
        return await asyncio.wait_for(read(), 2)

    async def test_notifications_recovery_coalescing_sse(self):
        self.assertEqual((await self.request('/health'))[0], 503)
        self.assertEqual((await self.request('/v1/theme'))[0], 503)
        atomic_json(self.state / 'current.json', fixture())
        await self.settle()
        self.assertEqual(self.bridge.snapshot['revision'], 1)
        status, data = await self.request('/v1/theme')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), fixture())
        status, events = await self.request('/v1/events')
        self.assertEqual(status, 200)
        self.assertEqual((await self.event(events))['revision'], 1)
        q = asyncio.Queue(maxsize=10)
        self.bridge.clients.add(q)
        for rev in (2, 3, 4):
            atomic_json(self.state / 'current.json', fixture(rev, f'#00000{rev}'))
            # A single burst, without yielding past the debounce window on a
            # heavily loaded runner; inotify observes the final atomic replace.
        await self.settle()
        self.assertEqual(q.qsize(), 1)
        self.assertEqual(q.get_nowait()['revision'], 4)
        self.assertEqual((await self.event(events))['revision'], 4)
        atomic_json(self.state / 'current.json', fixture(4, '#000004'))
        await self.settle()
        self.assertTrue(q.empty())
        (self.state / 'current.json').write_text('{broken')
        await self.settle()
        self.assertEqual(self.bridge.snapshot['revision'], 4)
        self.assertEqual(json.loads((await self.request('/health'))[1])['status'], 'degraded')
        (self.state / 'current.json').unlink()
        await self.settle()
        self.assertEqual(self.bridge.source_status, 'missing')
        atomic_json(self.state / 'current.json', fixture(5, '#123456'))
        await self.settle()
        self.assertEqual(self.bridge.snapshot['revision'], 5)
        # A fresh service process retains last valid state even with broken source.
        (self.state / 'current.json').write_text('{')
        await self.settle()
        other = Bridge(self.state, self.settings)
        await other.start()
        try:
            self.assertEqual(other.snapshot['revision'], 5)
            self.assertEqual(other.source_status, 'invalid')
        finally:
            await other.close()
        self.bridge.clients.discard(q)

    async def test_slow_cache_write_notifications(self):
        # Reproduce the loaded-runner race: the real cache write completes
        # later than the former fixed 250 ms sleep. Notification must still arrive.
        original = atomic_json
        def delayed(path, value):
            time.sleep(.4)
            return original(path, value)
        updates = asyncio.Queue(maxsize=10)
        self.bridge.clients.add(updates)
        with patch('noctalia_theme_sync.bridge.atomic_json', side_effect=delayed):
            atomic_json(self.state / 'current.json', fixture())
            await self.settle()
            self.assertEqual(updates.get_nowait()['revision'], 1)
            self.assertTrue(updates.empty())
        self.bridge.clients.discard(updates)

    async def test_missing_directory_recreation(self):
        # Remove the watched directory itself, not just the file.
        self.state.rmdir()
        await self.settle()
        self.state.mkdir()
        atomic_json(self.state / 'current.json', fixture())
        await self.settle()
        self.assertEqual(self.bridge.snapshot['revision'], 1)

    async def test_sse_reconnect_last_event_id(self):
        atomic_json(self.state / 'current.json', fixture())
        await self.settle()
        status, reader = await self.request('/v1/events', extra='Last-Event-ID: 1\r\n')
        self.assertEqual(status, 200)
        self.assertEqual(await reader.readline(), b'retry: 2000\n')
        self.assertEqual(await reader.readline(), b'\n')
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(reader.readline(), .15)
        atomic_json(self.state / 'current.json', fixture(2, '#aabbcc'))
        self.assertEqual((await self.event(reader))['revision'], 2)
        status, stale = await self.request('/v1/events', extra='Last-Event-ID: 1\r\n')
        self.assertEqual((await self.event(stale))['revision'], 2)

    async def test_revision_and_metadata_suppression(self):
        atomic_json(self.state / 'current.json', fixture())
        await self.settle()
        altered = fixture(1, '#abcdef')
        atomic_json(self.state / 'current.json', altered)
        await self.settle()
        self.assertEqual(self.bridge.snapshot, fixture())
        atomic_json(self.state / 'current.json', fixture(2))
        await self.settle()
        self.assertEqual(self.bridge.source_status, 'invalid')
        altered = fixture()
        altered['generated_at'] = '2026-10-07T21:00:00Z'
        atomic_json(self.state / 'current.json', altered)
        await self.settle()
        self.assertEqual(self.bridge.snapshot, fixture())

    async def test_auth_remote_policy_and_origin(self):
        settings = dict(self.settings, bind='0.0.0.0', trusted_loopback=True)
        remote = Bridge(self.state, settings)
        original_start = asyncio.start_server
        async def loopback_test_server(callback, host, port, **kwargs):
            return await original_start(callback, '127.0.0.1', port, **kwargs)
        # Exercise non-loopback policy without actually exposing the test to LAN.
        with patch('noctalia_theme_sync.bridge.asyncio.start_server', loopback_test_server):
            await remote.start()
        oldport = self.port
        self.port = remote.server.sockets[0].getsockname()[1]
        try:
            self.assertTrue(remote.auth_required)
            self.assertEqual((await self.request('/health'))[0], 401)
            self.assertEqual((await self.request('/v1/events', 'bad'))[0], 401)
            self.assertEqual((await self.request('/health', remote.secret))[0], 503)
            atomic_json(self.state / 'current.json', fixture())
            await self.settle(remote)
            self.assertEqual((await self.request('/v1/theme', remote.secret))[0], 200)
            self.assertEqual((await self.request('/v1/events', remote.secret))[0], 200)
            self.assertEqual((await self.request('/health', remote.secret, 'Origin: http://evil.invalid\r\n'))[0], 403)
            self.assertEqual(os.stat(settings['token_file']).st_mode & 0o777, 0o600)
            os.chmod(settings['token_file'], 0o644)
            with self.assertRaises(ValueError):
                token(settings['token_file'])
        finally:
            self.port = oldport
            await remote.close()

    async def test_wallpaper_path_safety(self):
        walls = self.root / 'walls'
        walls.mkdir()
        image = walls / 'current.png'
        image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'image fixture')
        p = fixture()
        p['wallpaper'] = str(image)
        p['wallpaper_asset'], data = wallpaper_file(image, self.settings['wallpaper_roots'])
        atomic_json(self.state / 'current.json', p)
        await self.settle()
        status, body = await self.request('/v1/wallpaper/current')
        self.assertEqual((status, body), (200, data))
        self.assertEqual((await self.request('/v1/wallpaper/current?id=wrong'))[0], 409)
        self.assertEqual((await self.request('/v1/wallpaper/current?path=/etc/passwd'))[0], 400)
        self.assertEqual((await self.request('/v1/wallpaper/current/../../etc/passwd'))[0], 404)
        outside = self.root / 'secret.png'
        outside.write_bytes(data)
        image.unlink()
        image.symlink_to(outside)
        self.assertEqual((await self.request('/v1/wallpaper/current'))[0], 404)
        image.unlink()
        image.write_bytes(data + b'changed')
        self.assertEqual((await self.request('/v1/wallpaper/current'))[0], 409)
        with self.assertRaises(ValueError):
            wallpaper_file(outside, self.settings['wallpaper_roots'])

    async def test_publisher_monotonic_and_validation(self):
        from noctalia_theme_sync import publisher as pub
        env = {'XDG_STATE_HOME': str(self.root / 'xdgstate'), 'XDG_CONFIG_HOME': str(self.root / 'config')}
        with patch.dict(os.environ, env):
            state = Path(env['XDG_STATE_HOME']) / 'noctalia/theme-sync'
            state.mkdir(parents=True)
            p = fixture()
            atomic_json(state / 'palette.json', {'mode': p['mode'], 'colors': p['colors']})
            (state / 'palette-wallpaper.txt').write_text('\n')
            first = pub.publish()
            self.assertEqual(first['revision'], 1)
            self.assertEqual(pub.publish(), first)
            p['colors']['primary'] = '#abcdef'
            atomic_json(state / 'palette.json', {'mode': p['mode'], 'colors': p['colors']})
            self.assertEqual(pub.publish()['revision'], 2)
            recovery = Bridge(state, self.settings)
            await recovery.start()
            try:
                updates = asyncio.Queue(maxsize=10)
                recovery.clients.add(updates)
                (state / 'current.json').write_text('{')
                await self.settle(recovery)
                self.assertEqual(recovery.source_status, 'invalid')
                self.assertEqual(pub.publish()['revision'], 2)
                await self.settle(recovery)
                self.assertEqual(recovery.source_status, 'valid')
                self.assertTrue(updates.empty())
            finally:
                await recovery.close()
            (state / 'current.json').write_text('{')
            self.assertEqual(pub.publish()['revision'], 2)
            (state / 'current.json').unlink()
            self.assertEqual(pub.publish()['revision'], 2)
            p['colors']['primary'] = '#123456'
            atomic_json(state / 'palette.json', {'mode': p['mode'], 'colors': p['colors']})
            self.assertEqual(pub.publish()['revision'], 3)
            p['colors']['primary'] = 'invalid'
            atomic_json(state / 'palette.json', {'mode': p['mode'], 'colors': p['colors']})
            with self.assertRaises(ValueError):
                pub.publish()
            self.assertEqual(json.loads((state / 'current.json').read_text())['revision'], 3)


if __name__ == '__main__':
    unittest.main()
