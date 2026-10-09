"""Opt-in, private adapter previews; no native activation, publisher or service."""
from contextlib import contextmanager
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from . import adapters, adoption, transaction as tx, xdg
from .model import MAX_JSON, parse_json, semantic, validate

NAME = 'noctalia-nts'


def pipeline_roots():
    return {kind: str(xdg.base(kind)) for kind in ('config', 'state', 'data', 'cache', 'bin')}


def inspect_pipeline(roots, output):
    """Read the existing writer registry with its original XDG expansion rules."""
    variables = {'XDG_' + k.upper() + '_HOME': v for k, v in roots.items() if k != 'bin'}
    variables['NTS_BIN_HOME'] = roots['bin']
    previous = {key: os.environ.get(key) for key in variables}
    os.environ.update(variables)
    try:
        inventory = adoption.inventory([], True)
        if inventory['blockers']:
            raise ValueError('cannot safely inspect existing pipeline: ' + '; '.join(inventory['blockers']))
        if any(Path(p).resolve() == Path(output).resolve() for writer in inventory['writers'] for p in writer['outputs']):
            raise ValueError('existing Noctalia writer claims the shadow output')
        return {str(p): adoption.signature(p) for p in (Path(roots['config']) / 'noctalia').glob('*.toml')}
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def consumer_lock(create=False):
    path = xdg.safe(xdg.state() / 'consumer.lock')
    if not create and not path.exists():
        yield
        return
    if create:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, (os.O_RDWR | os.O_CREAT if create else os.O_RDONLY) | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+' if create else 'r') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('shadow consumer already running; stop it before another writer/removal') from exc
        yield


@contextmanager
def context(root):
    root = Path(root)
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('shadow root must be absolute without traversal')
    for path in (root, *root.parents):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError('shadow root must not traverse symlinks or files')
    protected = [xdg.base('config') / n for n in ('noctalia', 'nvim')]
    protected += [xdg.canonical(), xdg.state(), xdg.base('data') / 'noctalia-theme-sync/runtime']
    if any(root.is_relative_to(p) or p.is_relative_to(root) for p in protected):
        raise ValueError('shadow root overlaps a production integration')
    if root.exists() and (root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077):
        raise ValueError('existing shadow root must be owned and private (0700)')
    values = {'XDG_' + k.upper() + '_HOME': str(root / k) for k in ('config', 'state', 'data', 'cache')}
    values['NTS_BIN_HOME'] = str(root / 'bin')
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield root
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def target():
    return xdg.safe(xdg.base('config') / ('nvim/colors/' + NAME + '.lua'))


def load():
    m = tx.load()
    if set(m['files']) - {str(target())} or m.get('bridge') or m.get('adapters'):
        raise ValueError('unexpected shadow manifest targets; refusing writes')
    if m.get('shadow') and m['shadow'].get('adapter') != 'neovim':
        raise ValueError('unsupported shadow adapter')
    return m


def render(palette):
    # Reuse the public adapter renderer; only the colorscheme identity changes.
    text = adapters.assets().joinpath('adapters/neovim.lua').read_text()
    identity = 'vim.g.colors_name = "noctalia"'
    if text.count(identity) != 1:
        raise ValueError('unexpected Neovim template identity')
    return adapters.render(text.replace(identity, 'vim.g.colors_name = "' + NAME + '"'), palette)


def source(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError('palette source must be an absolute regular file')
    if path.stat().st_size > MAX_JSON:
        raise ValueError('palette source exceeds 64 KiB')
    raw = path.read_bytes()
    return validate(parse_json(raw)), {'path': str(path), 'sha256': xdg.digest(raw),
                                      'mode': stat.S_IMODE(path.stat().st_mode)}


def plan(args, palette_path):
    palette, signature = source(palette_path)
    roots = pipeline_roots()
    with context(args.root):
        m = load()
        roots = m.get('shadow', {}).get('pipeline_roots', roots)
        with consumer_lock():
            pass
        path = str(target())
        inputs = inspect_pipeline(roots, path)
        current = tx.check(m, path)
        if current is not None and path not in m['files']:
            raise ValueError('unmanaged shadow output exists; preserve it, choose a fresh root')
        if xdg.read(xdg.state() / 'pending.json') is not None:
            raise ValueError('interrupted shadow transaction; use shadow rollback --recover')
        data = render(palette)
        payload = {'format': 1, 'adapter': 'neovim', 'root': str(Path(args.root)), 'source': signature,
                   'pipeline_roots': roots, 'read_only_pipeline': inputs,
                   'inputs': {p: adoption.signature(p) for p in (path, str(tx.manifest_path()),
                                                               str(xdg.state() / 'pending.json'))},
                   'outputs': {path: xdg.digest(data)}}
        report = {'shadow': True, 'changes': [{'path': path, 'action': 'unchanged' if current == data else
                  'update' if current is not None else 'create', 'mode': 0o600}],
                  'metadata': [str(xdg.state() / p) for p in ('.lock', 'consumer.lock', 'installation.json', 'pending.json')],
                  'blockers': [], 'reviewed_plan': payload,
                  'plan_sha256': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()}
        return report, palette, data


def apply_palette(m, palette, delivery):
    path = str(target())
    if set(m['files']) != {path} or not m.get('shadow'):
        raise ValueError('shadow installation required')
    tx.check(m, path)
    inspect_pipeline(m['shadow']['pipeline_roots'], path)
    if delivery != 'sse':
        m['shadow'].pop('event', None)  # A manual fixture must not suppress the next bridge snapshot.
    m['shadow'].update(palette=semantic(palette), revision=palette['revision'], delivery=delivery)
    tx.commit(m, {path: render(palette)})


def remove(args):
    with context(args.root):
        m = load()
        for path in m['files']:
            tx.check(m, path)
        if args.dry_run:
            return {'would_restore': sorted(m['files'])}
        with consumer_lock(create=True), tx.locked():
            m = load()
            for path in m['files']:
                tx.check(m, path)
            if m['files']:
                backup = xdg.state() / 'backups' / ('original-' + xdg.digest(xdg.read(tx.manifest_path())) + '.json')
                if xdg.read(backup) is None:
                    xdg.write(backup, xdg.read(tx.manifest_path()))
            originals = {p: tx.decode(e['original']) for p, e in m['files'].items()}
            modes = {p: e['original_mode'] for p, e in m['files'].items()}
            m.pop('shadow', None)
            tx.commit(m, originals, modes=modes, forget=originals)
        return {'restored': sorted(originals), 'retained_metadata': str(xdg.state())}


def preview(args):
    with context(args.root) as root:
        m = load()
        if str(target()) not in m['files']:
            raise ValueError('shadow installation required')
        initial = tx.check(m, target())
        output = str(target())
        manifest = str(tx.manifest_path())
    # No normal init/plugins, shada, swaps, user RPC or desktop/session IPC.
    root.mkdir(exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='test-', dir=root) as temporary:
        env = {'PATH': os.environ.get('PATH', ''), 'LANG': 'C.UTF-8', 'TERM': os.environ.get('TERM', 'xterm-256color'),
               'HOME': temporary, 'NTS_SHADOW_OUTPUT': output, 'NTS_SHADOW_MANIFEST': manifest}
        for kind in ('CONFIG', 'STATE', 'DATA', 'CACHE', 'RUNTIME'):
            env['XDG_' + kind + ('_DIR' if kind == 'RUNTIME' else '_HOME')] = temporary + '/' + kind.lower()
        copied = Path(temporary) / ('config/nvim/colors/' + NAME + '.lua')
        copied.parent.mkdir(parents=True, mode=0o700)
        copied.write_bytes(initial)
        env['NTS_SHADOW_COPY'] = str(copied)
        script = adapters.assets().joinpath('shadow-neovim.lua').read_text()
        lua = Path(temporary) / 'test.lua'
        lua.write_text(script)
        command = ['nvim', '-u', 'NONE', '-i', 'NONE', '-n', '--cmd', 'set loadplugins=false',
                   '-c', 'lua dofile(' + json.dumps(str(lua)) + ')']
        if args.interactive:
            env['NTS_SHADOW_INTERACTIVE'] = '1'
            code = subprocess.call(command, env=env)
            return {'exit_code': code, 'isolated': True, 'persistent_activation': False}
        command.insert(1, '--headless')
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise ValueError('isolated Neovim test failed: ' + result.stderr[:300])
        return json.loads(result.stdout)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('bridge redirects refused')


def endpoint(value):
    url = urllib.parse.urlsplit(value)
    if (url.scheme != 'http' or url.path != '/v1/events' or url.query or url.fragment
            or url.username or url.password or not ipaddress.ip_address(url.hostname).is_loopback):
        raise ValueError('events URL must be numeric loopback HTTP /v1/events without credentials/query')
    return value


def frames(stream):
    fields, size = {}, 0
    while True:
        line = stream.readline(MAX_JSON + 1)
        if not line:
            return
        size += len(line)
        if size > MAX_JSON:
            raise ValueError('SSE frame exceeds 64 KiB')
        line = line.decode('utf-8').rstrip('\r\n')
        if not line:
            if fields.get('event') == 'theme' and 'data' in fields:
                p = validate(parse_json(fields['data'].encode()))
                if fields.get('id') != str(p['revision']):
                    raise ValueError('SSE id does not match revision')
                yield p
            fields, size = {}, 0
        elif line.startswith(':'):
            continue
        elif ':' in line:
            key, value = line.split(':', 1)
            value = value.removeprefix(' ')
            if key == 'data' and key in fields:
                fields[key] += '\n' + value
            else:
                fields[key] = value


def watch(args):
    endpoint(args.events)
    if args.max_events is not None and args.max_events < 1:
        raise ValueError('max-events must be positive')
    with context(args.root):
        m = load()
        if not m.get('shadow') or set(m['files']) != {str(target())}:
            raise ValueError('shadow installation required')
        tx.check(m, target())
        with consumer_lock(create=True):
            return consume_events(args)


def consume_events(args):
    url = endpoint(args.events)
    if args.max_events is not None and args.max_events < 1:
        raise ValueError('max-events must be positive')
    headers = {'Accept': 'text/event-stream'}
    if args.token_file:
        token = Path(args.token_file)
        if token.is_symlink() or not token.is_file() or token.stat().st_mode & 0o077 or token.stat().st_size > 4096:
            raise ValueError('token file must be private, regular and <=4096 bytes')
        headers['Authorization'] = 'Bearer ' + token.read_text().strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    count, delay = 0, 2
    while True:
        m = load()
        tx.check(m, target())
        previous = m['shadow'].get('event')
        if previous and previous['url'] == url:
            headers['Last-Event-ID'] = str(previous['revision'])
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=30) as response:
                if response.headers.get_content_type() != 'text/event-stream':
                    raise ValueError('bridge did not return text/event-stream')
                for palette in frames(response):
                    with tx.locked():
                        m = load()
                        previous = m['shadow'].get('event')
                        if previous and previous['url'] == url:
                            if palette['revision'] < previous['revision'] or (palette['revision'] == previous['revision']
                                    and semantic(palette) != m['shadow']['palette']):
                                raise ValueError('bridge revision regression or conflicting replay')
                        m['shadow']['event'] = {'url': url, 'revision': palette['revision']}
                        apply_palette(m, palette, 'sse')
                    count += 1
                    delay = 2
                    if args.max_events and count >= args.max_events:
                        return {'received': count, 'persistent_service': False}
        except urllib.error.HTTPError as exc:
            raise ValueError('bridge HTTP failure: ' + str(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            pass
        time.sleep(delay)
        delay = min(delay * 2, 30)


def dispatch(args):
    # Capture the real canonical read path before entering private XDG roots.
    palette_path = args.palette or str(xdg.canonical() / 'current.json')
    action = args.shadow_command
    if action in ('plan', 'install', 'apply'):
        report, palette, data = plan(args, palette_path)
        if args.from_plan:
            adoption.check(args.from_plan, report)
        if args.write_plan:
            if action != 'plan' and not args.dry_run:
                raise ValueError('write-plan requires shadow plan or --dry-run')
            adoption.save(args.write_plan, report)
        if action == 'plan' or args.dry_run:
            return report
        if action == 'install' and not args.from_plan:
            raise ValueError('shadow install requires checksum-bound --from-plan')
        with context(args.root) as root:
            root.mkdir(exist_ok=True, mode=0o700)
            with consumer_lock(create=True), tx.locked():
                # Read the input again before committing; do not accept palette drift.
                if source(palette_path)[1] != report['reviewed_plan']['source']:
                    raise ValueError('palette changed before shadow transaction')
                m = load()
                if inspect_pipeline(report['reviewed_plan']['pipeline_roots'], target()) != report['reviewed_plan']['read_only_pipeline']:
                    raise ValueError('existing pipeline changed before shadow transaction')
                if action == 'apply':
                    apply_palette(m, palette, 'file-once')
                else:
                    m['shadow'] = {'adapter': 'neovim', 'palette': semantic(palette),
                                   'pipeline_roots': report['reviewed_plan']['pipeline_roots'],
                                   'revision': palette['revision'], 'delivery': 'file-once'}
                    tx.commit(m, {str(target()): data}, expected=report['reviewed_plan']['inputs'])
        return {'applied': 'neovim', 'shadow': True, 'revision': palette['revision'], 'output': report['changes'][0]['path']}
    if action in ('uninstall', 'rollback'):
        if getattr(args, 'recover', False):
            with context(args.root):
                load()  # Validate allowed manifest targets before recovery.
                journal = xdg.read(xdg.state() / 'pending.json')
                if journal and set(parse_json(journal)['before']) - {str(target())}:
                    raise ValueError('unexpected recovery targets')
                if args.dry_run:
                    return {'pending': journal is not None}
                # locked() rejects pending journals; use its own lock for recovery.
                lock = xdg.safe(xdg.state() / '.lock')
                if not lock.parent.exists():
                    return {'recovered': False}
                with consumer_lock(), lock.open('a') as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX)
                    return {'recovered': tx.recover()}
        return remove(args)
    if action == 'test':
        return preview(args)
    if action == 'watch':
        return watch(args)
    with context(args.root):
        m = load()
        installed = str(target()) in m['files']
        if installed:
            tx.check(m, target())
        try:
            with consumer_lock():
                active = False
        except ValueError:
            active = True
        return {'installed': installed, 'output': str(target()), 'metadata': str(tx.manifest_path()),
                'shadow': m.get('shadow'), 'persistent_service': False,
                'consumer_lock_held': active, 'running_application_palette': 'unverified'}
