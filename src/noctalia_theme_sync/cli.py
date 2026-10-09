"""Conservative per-user installation and lifecycle CLI."""
import argparse
from contextlib import nullcontext
import asyncio
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

from . import __version__, adapters, adoption, diagnostics, native, transaction as tx, xdg
from .model import config, read_json, validate


def run(argv):
    return subprocess.run(argv, text=True, capture_output=True, timeout=10)


def noctalia_version():
    if not shutil.which('noctalia'):
        return None
    result = run(['noctalia', '--version'])
    match = re.search(r'\bv(\d+)\.(\d+)\.(\d+)', result.stdout)
    return tuple(map(int, match.groups())) if match and result.returncode == 0 else None


def emit(value):
    print(json.dumps(value, indent=2))


def selection(args, m):
    catalog = adapters.registry()
    if args.adapters:
        names = list(dict.fromkeys(re.split(r'[,\s]+', args.adapters.strip())))
    elif args.auto:
        names = [name for name, item in catalog.items() if item['status'] == 'supported' and adapters.available(item)]
    else:
        names = m['adapters']
    if not names and args.command in ('install', 'plan'):
        raise ValueError('choose --adapters kitty,tmux,... or --auto; use list to see choices')
    for name in names:
        if name not in catalog:
            raise ValueError('unknown adapter: ' + name)
        if catalog[name]['status'] != 'supported' and not args.experimental and name not in m['adapters']:
            raise ValueError(name + ' requires --experimental')
    return names


def inspect_noctalia(selected, consume_existing=False):
    return adoption.inventory(selected, consume_existing)['blockers']


def config_fragment(command):
    source = xdg.base('data') / 'noctalia-theme-sync/runtime/noctalia_theme_sync/assets'
    state = xdg.canonical()
    # JSON strings are valid TOML basic strings; shlex.quote protects paths in hooks.
    import shlex
    return ('# Managed by noctalia-theme-sync; Noctalia remains the palette producer.\n'
            '[theme.templates.user.nts_wallpaper]\n'
            'input_path = ' + json.dumps(str(source / 'wallpaper.txt')) + '\n'
            'output_path = ' + json.dumps(str(state / 'palette-wallpaper.txt')) + '\nindex = 1899\n'
            '[theme.templates.user.nts_palette]\n'
            'input_path = ' + json.dumps(str(source / 'palette.json')) + '\n'
            'output_path = ' + json.dumps(str(state / 'palette.json')) + '\n'
            'index = 1900\nhook_async = false\npost_hook = ' + json.dumps(shlex.quote(str(command)) + ' sync') + '\n').encode()


def runtime_files():
    source = Path(__file__).parent
    runtime = xdg.base('data') / 'noctalia-theme-sync/runtime/noctalia_theme_sync'
    result = {}
    for file in source.rglob('*'):
        if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
            result[str(runtime / file.relative_to(source))] = file.read_bytes()
    command = xdg.base('bin') / 'noctalia-theme-sync'
    script = ('#!' + sys.executable + '\nimport sys\nsys.path.insert(0, ' + repr(str(runtime.parent)) + ')\nfrom noctalia_theme_sync.cli import main\nraise SystemExit(main())\n')
    result[str(command)] = script.encode()
    return result, command


def install_plan(args, m):
    names = selection(args, m)
    consume = (args.consume_existing or m['consume_existing']) if args.command == 'install' else m['consume_existing']
    if args.command == 'plan':
        consume = args.consume_existing or m['consume_existing']
    if m['adapters'] and set(names) != set(m['adapters']):
        names = sorted(set(names) | set(m['adapters']))  # install adds; disable removes
    version = noctalia_version()
    issues = inspect_noctalia(names, consume)
    if xdg.read(xdg.state() / 'pending.json') is not None:
        issues.append('interrupted transaction: run rollback --recover')
    if version is None or version[0] != 5:
        issues.append('Noctalia v5 executable required')
    if not (xdg.base('config') / 'noctalia').is_dir():
        issues.append('Noctalia configuration directory missing')
    for name, probe in (('codex', native.codex_version), ('fastfetch', native.fastfetch_version)):
        if name in names:
            capability = probe()
            if not capability['compatible']:
                issues.append(capability['reason'])
    changes, command = runtime_files()
    if not consume:
        changes[str(xdg.base('config') / 'noctalia/noctalia-theme-sync.toml')] = config_fragment(command)
    mode = 'dark'
    snapshot = None
    try:
        snapshot = validate(read_json(xdg.canonical() / 'current.json'))
        mode = snapshot['mode']
    except FileNotFoundError:
        pass
    except (ValueError, OSError):
        issues.append('existing canonical snapshot invalid; inspect before installing')
    if consume and snapshot is None:
        issues.append('--consume-existing requires a valid existing canonical snapshot')
    try:
        changes.update(adapters.activation(names, lambda p: tx.check(m, p), mode, snapshot))
    except (OSError, ValueError) as exc:
        issues.append(str(exc))
    registrations = {str(adapters.target(o['path'])): 'generated' for name in names for o in adapters.registry()[name]['outputs']}
    if 'codex' in names:
        registrations[str(adapters.target('codex/config.toml'))] = 'codex-theme'
    if snapshot:
        try:
            changes.update(adapters.generate(names, snapshot))
        except ValueError as exc:
            issues.append(str(exc))
    bridge = args.bridge or m.get('bridge', False)
    if bridge:
        unit = xdg.base('config') / 'systemd/user/noctalia-theme-sync-bridge.service'
        unit_text = ('[Unit]\nDescription=Noctalia theme JSON/SSE bridge\nAfter=graphical-session.target\nPartOf=graphical-session.target\n'
                     '[Service]\nType=simple\nExecStart=' + json.dumps(str(command)) + ' bridge\nRestart=on-failure\nRestartSec=2\n'
                     'UMask=0077\nNoNewPrivileges=true\nRestrictSUIDSGID=true\nLockPersonality=true\n'
                     'RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\nTasksMax=32\nMemoryMax=256M\n'
                     '[Install]\nWantedBy=graphical-session.target\n')
        changes[str(unit)] = unit_text.encode()
        if not m.get('bridge'):
            if shutil.which('systemctl') and run(['systemctl', '--user', 'is-active', 'theme-sync-bridge.service']).returncode == 0:
                issues.append('existing theme-sync-bridge service active; do not install a duplicate')
            settings = config()
            if settings['bind'] not in ('127.0.0.1', '::1'):
                issues.append('existing bridge configuration is not loopback; review explicitly')
            with socket.socket(socket.AF_INET6 if ':' in settings['bind'] else socket.AF_INET) as sock:
                try:
                    sock.bind((settings['bind'], settings['port']))
                except OSError:
                    issues.append('bridge port occupied; preserve running service')
    for path in sorted(set(changes) | set(registrations)):
        try:
            current = tx.check(m, path)
            if path not in m['files'] and current is not None and (registrations.get(path) == 'generated' or path in runtime_files()[0] or path.endswith('noctalia-theme-sync.toml') or path.endswith('noctalia-theme-sync-bridge.service')) and not args.adopt_existing:
                issues.append('unmanaged output already exists; --adopt-existing backs it up: ' + path)
        except (OSError, ValueError) as exc:
            issues.append(str(exc))
    report = {'adapters': names, 'native_context': native.target_context(names), 'consume_existing': consume, 'bridge': bridge,
              'changes': [{'path': p, 'action': 'unchanged' if xdg.read(p) == data else 'update' if Path(p).exists() else 'create'} for p, data in sorted(changes.items())],
              'reserved_outputs': sorted(registrations), 'blockers': sorted(set(issues)),
              'notes': ['Backups persist in private XDG state. No services are started automatically.',
                        'Enable Neovim/Vencord/Telegram/Steam using the documented native controls.',
                        'Apply Noctalia templates after installation: noctalia msg templates-apply.']}
    for change in report['changes']:
        path = change['path']
        before = adoption.signature(path)
        change.update(before_sha256=before['sha256'], after_sha256=xdg.digest(changes[path]),
                      before_mode=before['mode'],
                      ownership='managed' if path in m['files'] else 'unmanaged' if before['sha256'] else 'absent')
    report['existing_pipeline'] = adoption.inventory(names, consume)
    adoption.bind(report, changes, registrations)
    return report, changes, registrations


def reload_apps(names):
    outcomes = {}
    for name in names:
        if name == 'firefox':
            outcomes[name] = run(['noctalia', 'firefox-theme', 'update']).returncode if shutil.which('noctalia') else 'Noctalia native host unavailable'
        elif name == 'tmux':
            outcomes[name] = run(['tmux', 'source-file', str(adapters.target('config/tmux/themes/noctalia-theme-sync.conf'))]).returncode if shutil.which('tmux') else 'tmux unavailable'
        elif name in ('kitty', 'cava'):
            # Explicit --reload only; PID ownership and exact comm are checked.
            expected, sig = ('kitty', signal.SIGUSR1) if name == 'kitty' else ('cava', signal.SIGUSR1)
            count = 0
            for path in Path('/proc').iterdir():
                if not path.name.isdigit():
                    continue
                try:
                    if path.stat().st_uid == os.getuid() and (path / 'comm').read_text().strip() == expected:
                        os.kill(int(path.name), sig)
                        count += 1
                except (OSError, ProcessLookupError):
                    pass
            outcomes[name] = {'signaled': count}
        elif name == 'qt':
            for version in ('5', '6'):
                root = xdg.base('config') / f'qt{version}ct'
                if root.is_dir():
                    os.utime(root)
            outcomes[name] = 'qtct directory notification; app behavior varies'
    return outcomes


def apply(args, publish=False):
    with (nullcontext() if args.dry_run else tx.locked()):
        m = tx.load()
        if not m['adapters']:
            raise ValueError('no installation; run install first')
        if publish and args.dry_run:
            emit({'would_publish': not m['consume_existing'], 'would_apply': m['adapters']})
            return 0
        if publish and not m['consume_existing']:
            from .publisher import publish as publisher
            palette = publisher()
        else:
            palette = validate(read_json(args.palette or xdg.canonical() / 'current.json'))
        changes = adapters.generate(m['adapters'], palette)
        # Update GTK dark/light settings while preserving all other settings.
        activation = adapters.activation(m['adapters'], lambda p: tx.check(m, p), palette['mode'], palette)
        changes.update(activation)
        for path in changes:
            tx.check(m, path)
        if args.dry_run:
            emit({'revision': palette['revision'], 'would_update': sorted(changes)})
            return 0
        tx.commit(m, changes)
    outcomes = reload_apps([n for n in m['adapters'] if n in ('tmux', 'firefox')]) if publish else {}
    if args.reload:
        outcomes.update(reload_apps(m['adapters']))
    emit({'revision': palette['revision'], 'applied': m['adapters'], 'reload': outcomes})
    return 0


async def watch(args):
    """Optional file consumer for an already configured canonical publisher."""
    from .bridge import Watcher
    stopped = asyncio.Event()
    changed = asyncio.Event()
    watcher = Watcher(xdg.canonical() / 'current.json', changed.set)
    changed.set()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    try:
        while not stopped.is_set():
            update = asyncio.create_task(changed.wait())
            stop = asyncio.create_task(stopped.wait())
            done, pending = await asyncio.wait({update, stop}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if stop in done:
                break
            await asyncio.sleep(.25)
            changed.clear()
            try:
                apply(args)
            except (OSError, ValueError) as exc:
                print('watch: retained adapter files (' + type(exc).__name__ + ')', file=sys.stderr, flush=True)
    finally:
        watcher.close()


def remove(args):
    with (nullcontext() if args.dry_run else tx.locked()):
        m = tx.load()
        names = selection(args, m) if args.command == 'disable' else list(m['adapters'])
        remaining = [n for n in m['adapters'] if n not in names]
        catalog = adapters.registry()
        output_paths = {str(adapters.target(o['path'])) for name in names for o in catalog[name]['outputs']}
        # Activation files are restored only for removed integrations.
        activation_paths = set(adapters.activation(names, lambda p: tx.check(m, p)))
        selected_paths = output_paths | activation_paths if remaining else set(m['files'])
        restored = {p: tx.decode(m['files'][p]['original']) for p in selected_paths if p in m['files']}
        for path in restored:
            current = tx.check(m, path)
            if m['files'][path].get('kind') == 'codex-theme':
                restored[path] = native.codex_restore(current, restored[path], tx.decode(m['files'][path].get('owned_initial')))
        if not remaining and m.get('bridge'):
            result = run(['systemctl', '--user', 'is-active', 'noctalia-theme-sync-bridge.service']) if shutil.which('systemctl') else None
            if result and result.returncode == 0:
                raise ValueError('stop the owned bridge first: service stop; uninstall will not remove a running unit')
            # Do not leave enabled unit symlinks to a removed service.
            wants = xdg.base('config') / 'systemd/user/graphical-session.target.wants/noctalia-theme-sync-bridge.service'
            if wants.is_symlink():
                raise ValueError('disable the owned bridge first: service disable')
        emit({'remove_adapters': names, 'restore_originals': sorted(restored), 'retained_backups': str(xdg.state())})
        if args.dry_run:
            return 0
        # Keep an immutable baseline copy of the manifest as the uninstall backup.
        if not remaining and m['files']:
            backup = xdg.state() / 'backups' / ('original-' + xdg.digest(xdg.read(tx.manifest_path())) + '.json')
            if xdg.read(backup) is None:
                xdg.write(backup, xdg.read(tx.manifest_path()))
        modes = {p: m['files'][p]['original_mode'] for p in restored}
        m['adapters'] = remaining
        m['native_context'] = native.target_context(remaining)
        if not remaining:
            m.update(bridge=False, consume_existing=False, native_context={})
        tx.commit(m, restored, modes=modes, forget=restored)
    return 0


def doctor():
    version = noctalia_version()
    info = {'version': __version__, 'platform': sys.platform, 'python': list(sys.version_info[:3]), 'noctalia': version,
            'xdg': {k: str(xdg.base(k)) for k in ('config', 'state', 'data', 'cache', 'bin')},
            'adapters': {n: {'detected': adapters.available(a), 'status': a['status'], 'dependencies': a['dependencies']} for n, a in adapters.registry().items()},
            'canonical': 'missing', 'issues': []}
    if sys.platform != 'linux' or version is None or version[0] != 5:
        info['issues'].append('Linux + Noctalia v5 required')
    if not (xdg.base('config') / 'noctalia').is_dir():
        info['issues'].append('Noctalia configuration missing')
    try:
        p = validate(read_json(xdg.canonical() / 'current.json'))
        info['canonical'] = {'valid': True, 'revision': p['revision'], 'mode': p['mode']}
    except FileNotFoundError:
        pass
    except (ValueError, OSError):
        info['issues'].append('canonical export invalid')
    if xdg.read(xdg.state() / 'pending.json'):
        info['issues'].append('interrupted transaction; rollback --recover')
    palette = None
    try:
        palette = validate(read_json(xdg.canonical() / 'current.json'))
    except (OSError, ValueError):
        pass
    info['adapter_states'] = diagnostics.states(tx.load(), palette)
    emit(info)
    return 1 if info['issues'] else 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='noctalia-theme-sync', description=__doc__)
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True)
    shadow_parser = sub.add_parser('shadow', help='private Neovim preview, no production activation')
    actions = shadow_parser.add_subparsers(dest='shadow_command', required=True)
    for action in ('plan', 'install', 'apply', 'test', 'status', 'uninstall', 'rollback', 'watch'):
        p = actions.add_parser(action)
        p.add_argument('--root', required=True, help='absolute private root, separate from production integrations')
        p.add_argument('--palette', help='canonical v1 JSON (read only); defaults to existing current.json')
        p.set_defaults(from_plan=None, write_plan=None, dry_run=False)
        if action in ('plan', 'install', 'apply'):
            p.add_argument('--write-plan')
            p.add_argument('--from-plan')
            p.add_argument('--dry-run', action='store_true')
        if action in ('uninstall', 'rollback'):
            p.add_argument('--dry-run', action='store_true')
        if action == 'rollback':
            p.add_argument('--recover', action='store_true')
        if action == 'test':
            p.add_argument('--interactive', action='store_true', help='temporary isolated TUI; no default theme change')
        if action == 'watch':
            p.add_argument('--events', required=True, help='existing numeric loopback bridge /v1/events URL')
            p.add_argument('--token-file', help='optional private existing bridge bearer token file')
            p.add_argument('--max-events', type=int, help='bounded foreground verification; otherwise run until stopped')
    sub.add_parser('doctor')
    sub.add_parser('list')
    sub.add_parser('status')
    for name in ('plan', 'install', 'update', 'disable'):
        p = sub.add_parser(name)
        p.add_argument('--adapters', help='comma separated adapter ids')
        p.add_argument('--auto', action='store_true', help='detect supported adapters only')
        p.add_argument('--experimental', action='store_true')
        p.add_argument('--consume-existing', action='store_true', help='use existing canonical publisher without installing another hook')
        p.add_argument('--bridge', action='store_true', help='stage optional systemd user unit; do not start it')
        p.add_argument('--adopt-existing', action='store_true', help='back up existing generated output before managing it')
        p.add_argument('--dry-run', action='store_true')
        if name in ('plan', 'install', 'update'):
            p.add_argument('--write-plan', help='save a private checksum-bound plan; does not authorize installation')
            p.add_argument('--from-plan', help='require the exact previously reviewed plan, including input checksums')
    for name in ('apply', 'sync'):
        p = sub.add_parser(name)
        p.add_argument('--palette', help='explicit canonical v1 JSON; useful for isolated validation')
        p.add_argument('--reload', action='store_true', help='reload owned Kitty/cava processes and notify Qt')
        p.add_argument('--dry-run', action='store_true')
    for name in ('uninstall', 'rollback'):
        p = sub.add_parser(name)
        p.add_argument('--dry-run', action='store_true')
        if name == 'rollback':
            p.add_argument('--recover', action='store_true', help='recover an interrupted transaction only')
    p = sub.add_parser('validate')
    p.add_argument('file')
    p = sub.add_parser('bridge')
    p.add_argument('--config')
    p.add_argument('--state')
    p = sub.add_parser('watch')
    p.add_argument('--reload', action='store_true')
    p.set_defaults(palette=None, dry_run=False)
    p = sub.add_parser('service')
    p.add_argument('action', choices=['start', 'stop', 'status', 'enable', 'disable'])
    p.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'shadow':
            from .shadow import dispatch as shadow_dispatch
            emit(shadow_dispatch(args))
            return 0
        if tx.load().get('shadow'):
            raise ValueError('shadow state requires shadow commands; normal activation refused')
        with native.installation_context(tx.load()):
            return dispatch(args)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print('noctalia-theme-sync: ' + str(exc), file=sys.stderr)
        return 1


def dispatch(args):
    try:
        if args.command == 'doctor':
            return doctor()
        if args.command == 'list':
            emit([{**a, 'detected': adapters.available(a)} for a in adapters.registry().values()] + [{'id': 'affine', 'status': 'unavailable', 'limitations': 'No supported production palette API.'}, {'id': 'icons', 'status': 'unavailable', 'limitations': 'Artwork redistribution and symbolic recoloring excluded from initial release.'}])
        elif args.command == 'status':
            m = tx.load()
            palette = None
            try:
                palette = validate(read_json(xdg.canonical() / 'current.json'))
            except (OSError, ValueError):
                pass
            emit({'adapter_states': diagnostics.states(m, palette), 'adapters': m['adapters'], 'bridge_unit': m['bridge'], 'consume_existing': m['consume_existing'],
                  'files': [{'path': p, 'modified': xdg.digest(xdg.read(p)) != e['installed_sha256']} for p, e in m['files'].items()]})
        elif args.command in ('plan', 'install', 'update'):
            m = tx.load()
            report, changes, registrations = install_plan(args, m)
            if args.from_plan:
                adoption.check(args.from_plan, report)
            if args.write_plan:
                if args.command != 'plan' and not args.dry_run:
                    raise ValueError('--write-plan requires plan or --dry-run')
                adoption.save(args.write_plan, report)
            emit(report)
            if args.command == 'plan' or args.dry_run:
                return 1 if report['blockers'] else 0
            if report['blockers']:
                return 1
            if args.adopt_existing and not args.from_plan:
                raise ValueError('--adopt-existing requires a reviewed --from-plan; use plan --write-plan first')
            with tx.locked():
                # Recompute under the installation lock to avoid stale preflight.
                m = tx.load()
                report, changes, registrations = install_plan(args, m)
                if report['blockers']:
                    raise ValueError('; '.join(report['blockers']))
                if args.from_plan:
                    adoption.check(args.from_plan, report)
                m.update(adapters=report['adapters'], consume_existing=report['consume_existing'], bridge=report['bridge'], native_context=report['native_context'])
                command = str(xdg.base('bin') / 'noctalia-theme-sync')
                tx.commit(m, changes, registrations, modes={command: 0o755},
                          expected=report['reviewed_plan']['inputs'] if args.from_plan else None)
        elif args.command in ('apply', 'sync'):
            return apply(args, publish=args.command == 'sync')
        elif args.command == 'rollback' and args.recover:
            if args.dry_run:
                emit({'pending': xdg.read(xdg.state() / 'pending.json') is not None})
            else:
                # Recovery has its own lock path because locked() rejects pending journals.
                import fcntl
                xdg.safe(xdg.state() / '.lock')
                if xdg.state().is_dir():
                    with (xdg.state() / '.lock').open('a') as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX)
                        emit({'recovered': tx.recover()})
        elif args.command in ('uninstall', 'rollback', 'disable'):
            return remove(args)
        elif args.command == 'validate':
            p = validate(read_json(args.file))
            emit({'valid': True, 'schema_version': p['schema_version'], 'revision': p['revision']})
        elif args.command == 'bridge':
            from .bridge import main as bridge_main
            asyncio.run(bridge_main(args))
        elif args.command == 'watch':
            asyncio.run(watch(args))
        elif args.command == 'service':
            if not tx.load()['bridge']:
                raise ValueError('optional bridge unit is not installed')
            argv = ['systemctl', '--user', args.action, 'noctalia-theme-sync-bridge.service']
            if args.dry_run:
                emit({'command': argv})
            else:
                if args.action in ('start', 'enable', 'disable'):
                    result = run(['systemctl', '--user', 'daemon-reload'])
                    if result.returncode:
                        raise ValueError('systemd user manager unavailable')
                if args.action == 'start':
                    settings = config()
                    with socket.socket(socket.AF_INET6 if ':' in settings['bind'] else socket.AF_INET) as sock:
                        sock.bind((settings['bind'], settings['port']))
                return subprocess.run(argv, check=False).returncode
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print('noctalia-theme-sync: ' + str(exc), file=sys.stderr)
        return 1
