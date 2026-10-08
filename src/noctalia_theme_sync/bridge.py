#!/usr/bin/env python3
"""Small asyncio HTTP/SSE bridge for the canonical Noctalia export (Linux)."""
import argparse
import asyncio
import ctypes
import errno
import hmac
import ipaddress
import json
import os
import secrets
import signal
import stat
import struct
import time
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .model import atomic_json, config, paths, read_json, semantic, validate, wallpaper_file


def log(event, **fields):
    print(json.dumps({'time': time.time(), 'event': event, **fields}), flush=True)


def token(path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_urlsafe(32) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o600 or st.st_uid != os.getuid():
            raise ValueError('token must be an owned regular file with mode 0600')
        value = os.read(fd, 256).decode().strip()
        if len(value) < 32 or len(value) > 128 or not all(c.isascii() and (c.isalnum() or c in '-_') for c in value):
            raise ValueError('invalid bearer token file')
        return value
    finally:
        os.close(fd)


class Watcher:
    """Watch directory chain, including missing/replaced parents and queue overflow."""
    MASK = 0x2 | 0x4 | 0x8 | 0x40 | 0x80 | 0x100 | 0x200 | 0x400 | 0x800

    def __init__(self, path, callback):
        self.path, self.callback = Path(path), callback
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.inotify_init1.argtypes = [ctypes.c_int]
        self.libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.libc.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        self.fd = self.libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), 'inotify_init1')
        self.watches = {}
        self.refresh()
        asyncio.get_running_loop().add_reader(self.fd, self.ready)

    def refresh(self):
        # Ancestors catch recreation; watch only next path component at each level.
        wanted = {p: (self.path if p == self.path.parent else next(x for x in self.path.parents if x.parent == p)).name
                  for p in self.path.parents if p != Path('/') and p.is_dir()}
        for wd, (directory, _) in list(self.watches.items()):
            if directory not in wanted:
                self.libc.inotify_rm_watch(self.fd, wd)
                self.watches.pop(wd, None)
        for directory, name in wanted.items():
            wd = self.libc.inotify_add_watch(self.fd, os.fsencode(directory), self.MASK)
            if wd < 0:
                if ctypes.get_errno() in (errno.ENOENT, errno.ENOTDIR):
                    continue
                raise OSError(ctypes.get_errno(), 'inotify_add_watch')
            self.watches[wd] = (directory, name)

    def ready(self):
        relevant = False
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            offset = 0
            while offset < len(data):
                wd, mask, _, length = struct.unpack_from('iIII', data, offset)
                name = os.fsdecode(data[offset + 16:offset + 16 + length].split(b'\0', 1)[0])
                offset += 16 + length
                if mask & 0x4000:  # overflow: reconcile from disk
                    relevant = True
                    log('inotify_overflow')
                item = self.watches.get(wd)
                if item and (name == item[1] or not name):
                    relevant = True
                if mask & (0x8000 | 0x400 | 0x800):
                    self.watches.pop(wd, None)
                    self.libc.inotify_rm_watch(self.fd, wd)
        if relevant:
            self.refresh()
            self.callback()

    def close(self):
        asyncio.get_running_loop().remove_reader(self.fd)
        os.close(self.fd)


class Bridge:
    def __init__(self, state, settings):
        self.state, self.settings = Path(state), settings
        self.snapshot = None
        self.source_status = 'waiting'
        self.last_error = None
        self.last_check = None
        self.clients = set()
        self.connections = 0
        self.writers = set()
        self.wallpaper_lock = asyncio.Lock()
        self.pending = None
        self.reload_lock = asyncio.Lock()
        self.reload_tasks = set()
        self.started = time.monotonic()
        self.secret = token(settings['token_file'])
        self.auth_required = not (ipaddress.ip_address(settings['bind']).is_loopback and settings['trusted_loopback'])

    def schedule(self):
        if self.pending:
            self.pending.cancel()
        self.pending = asyncio.get_running_loop().call_later(
            self.settings['debounce_ms'] / 1000, self.launch_reload)

    def launch_reload(self):
        self.pending = None
        task = asyncio.create_task(self.reload())
        self.reload_tasks.add(task)
        task.add_done_callback(self.reload_tasks.discard)

    async def reload(self):
        async with self.reload_lock:
            self.last_check = time.time()
            try:
                p = validate(await asyncio.to_thread(read_json, self.state / 'current.json'))
                if self.snapshot:
                    same = semantic(p) == semantic(self.snapshot)
                    if p['revision'] < self.snapshot['revision'] or (not same and p['revision'] == self.snapshot['revision']):
                        raise ValueError('revision regression or reuse')
                    if same:
                        if p['revision'] != self.snapshot['revision']:
                            raise ValueError('revision changed without semantic change')
                        self.source_status, self.last_error = 'valid', None
                        return  # Timestamps alone never emit events.
                await asyncio.to_thread(atomic_json, self.state / 'bridge-last-valid.json', p)
                self.snapshot = p
                self.source_status, self.last_error = 'valid', None
                for queue in self.clients:
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(p)
                log('theme_changed', revision=p['revision'], subscribers=len(self.clients))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                reason = 'missing' if isinstance(exc, FileNotFoundError) else 'invalid'
                if self.source_status != reason or self.last_error != str(exc):
                    log('source_unavailable', reason=reason, error=str(exc), retained=self.snapshot is not None)
                self.source_status, self.last_error = reason, str(exc)

    async def start(self):
        self.state.mkdir(parents=True, exist_ok=True)
        try:
            self.snapshot = validate(read_json(self.state / 'bridge-last-valid.json'))
            log('cache_restored', revision=self.snapshot['revision'])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.watcher = Watcher(self.state / 'current.json', self.schedule)
        await self.reload()  # watch before read: no startup race
        try:
            self.server = await asyncio.start_server(self.handle, self.settings['bind'], self.settings['port'], limit=16384)
        except BaseException:
            if self.pending:
                self.pending.cancel()
            self.watcher.close()
            raise
        log('listening', bind=self.settings['bind'], port=self.server.sockets[0].getsockname()[1],
            authentication=self.auth_required)

    async def close(self):
        if self.pending:
            self.pending.cancel()
        self.watcher.close()
        for task in tuple(self.reload_tasks):
            task.cancel()
        await asyncio.gather(*self.reload_tasks, return_exceptions=True)
        self.server.close()
        for writer in tuple(self.writers):
            writer.close()
        await self.server.wait_closed()

    async def response(self, writer, code, body, mime='application/json', headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, separators=(',', ':')).encode()
        lines = [f'HTTP/1.1 {code} {HTTPStatus(code).phrase}', f'Content-Type: {mime}',
                 f'Content-Length: {len(body)}', 'Connection: close', 'Cache-Control: no-store',
                 'X-Content-Type-Options: nosniff']
        lines += [f'{k}: {v}' for k, v in (headers or {}).items()]
        writer.write(('\r\n'.join(lines) + '\r\n\r\n').encode() + body)
        await asyncio.wait_for(writer.drain(), 10)

    async def handle(self, reader, writer):
        self.connections += 1
        self.writers.add(writer)
        try:
            if self.connections > 32:
                await self.response(writer, 503, {'error': 'connection_limit'})
                return
            try:
                raw = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
                if len(raw) > 16384:
                    raise ValueError('headers too large')
                lines = raw.decode('ascii').split('\r\n')
                method, target, version = lines[0].split(' ')
                if version not in ('HTTP/1.0', 'HTTP/1.1') or not target.startswith('/'):
                    raise ValueError('invalid request')
                headers = {}
                for line in lines[1:-2]:
                    key, value = line.split(':', 1)
                    key = key.lower()
                    if key in headers:
                        raise ValueError('duplicate header')
                    headers[key] = value.strip()
            except (ValueError, UnicodeError, asyncio.LimitOverrunError, asyncio.IncompleteReadError):
                await self.response(writer, 400, {'error': 'bad_request'})
                return
            host = headers.get('host', '')
            allowed_hosts = {self.settings['bind'], 'localhost', '127.0.0.1', '::1'}
            if host.startswith('['):
                hostname = host[1:].split(']', 1)[0]
            else:
                hostname = host.split(':', 1)[0]
            if (not self.auth_required and hostname not in allowed_hosts) or 'origin' in headers:
                await self.response(writer, 403, {'error': 'origin_or_host_rejected'})
                return
            if self.auth_required and not hmac.compare_digest(headers.get('authorization', ''), 'Bearer ' + self.secret):
                await self.response(writer, 401, {'error': 'unauthorized'}, headers={'WWW-Authenticate': 'Bearer'})
                return
            if method != 'GET':
                await self.response(writer, 405, {'error': 'method_not_allowed'}, headers={'Allow': 'GET'})
                return
            url = urlsplit(target)
            if url.path == '/health' and not url.query:
                await self.response(writer, 200 if self.snapshot else 503,
                                    {'status': 'ok' if self.source_status == 'valid' else 'degraded' if self.snapshot else 'waiting',
                                     'source_status': self.source_status, 'schema_version': 1,
                                     'revision': self.snapshot['revision'] if self.snapshot else None,
                                     'uptime_seconds': round(time.monotonic() - self.started, 1),
                                     'subscribers': len(self.clients), 'auth_required': self.auth_required,
                                     'last_source_check': self.last_check})
            elif url.path == '/v1/theme' and not url.query:
                if self.snapshot:
                    await self.response(writer, 200, self.snapshot, headers={'ETag': f'"theme-{self.snapshot["revision"]}"'})
                else:
                    await self.response(writer, 503, {'error': 'theme_not_ready'}, headers={'Retry-After': '1'})
            elif url.path == '/v1/events' and not url.query:
                await self.events(reader, writer, headers.get('last-event-id'))
            elif url.path == '/v1/wallpaper/current':
                async with self.wallpaper_lock:
                    await self.wallpaper(writer, url.query)
            else:
                await self.response(writer, 404, {'error': 'not_found'})
        except (TimeoutError, ConnectionError, BrokenPipeError):
            pass
        except Exception as exc:
            # Never log raw requests, headers, URLs or tokens.
            log('request_error', error=type(exc).__name__)
        finally:
            self.connections -= 1
            self.writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async def events(self, reader, writer, last_id):
        if len(self.clients) >= 16:
            await self.response(writer, 503, {'error': 'subscriber_limit'})
            return
        queue = asyncio.Queue(maxsize=1)
        self.clients.add(queue)
        if self.snapshot and str(self.snapshot['revision']) != last_id:
            queue.put_nowait(self.snapshot)
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nConnection: close\r\nX-Accel-Buffering: no\r\n\r\nretry: 2000\n\n')
        eof = asyncio.create_task(reader.read(1))
        try:
            while not eof.done():
                await asyncio.wait_for(writer.drain(), 10)
                item = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({item, eof}, timeout=15, return_when=asyncio.FIRST_COMPLETED)
                if eof in done:
                    item.cancel()
                    await asyncio.gather(item, return_exceptions=True)
                    break
                if item in done:
                    p = item.result()
                    writer.write(f'id: {p["revision"]}\nevent: theme\ndata: {json.dumps(p, separators=(",", ":"))}\n\n'.encode())
                else:
                    item.cancel()
                    await asyncio.gather(item, return_exceptions=True)
                    writer.write(b': keepalive\n\n')
        finally:
            eof.cancel()
            await asyncio.gather(eof, return_exceptions=True)
            self.clients.discard(queue)

    async def wallpaper(self, writer, query):
        args = parse_qs(query, keep_blank_values=True)
        if set(args) - {'id'} or ('id' in args and len(args['id']) != 1):
            await self.response(writer, 400, {'error': 'only_id_query_allowed'})
            return
        p = self.snapshot
        if not p or not p.get('wallpaper_asset'):
            await self.response(writer, 404, {'error': 'wallpaper_unavailable'})
            return
        if 'id' in args and args['id'][0] != p['wallpaper_asset']['id']:
            await self.response(writer, 409, {'error': 'wallpaper_changed'})
            return
        try:
            asset, data = await asyncio.to_thread(wallpaper_file, p['wallpaper'], self.settings['wallpaper_roots'])
            if asset != p['wallpaper_asset'] or self.snapshot['revision'] != p['revision']:
                await self.response(writer, 409, {'error': 'wallpaper_changed'})
                return
        except (OSError, ValueError):
            await self.response(writer, 404, {'error': 'wallpaper_unavailable'})
            return
        await self.response(writer, 200, data, asset['content_type'], {'ETag': '"' + asset['id'] + '"'})


async def main(args):
    settings = config(args.config)
    _, state = paths()
    bridge = Bridge(args.state or state, settings)
    await bridge.start()
    stopped = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
    await stopped.wait()
    await bridge.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--state')
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as exc:
        log('fatal', error=str(exc))
        raise SystemExit(1)
