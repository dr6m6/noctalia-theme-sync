#!/usr/bin/env python3
"""Check the complete tracked tree/history without printing sensitive values."""
import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'personal home path': re.compile(rb'/(?:home|Users)/[A-Za-z0-9_.-]+/'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'GitHub credential': re.compile(rb'gh[pousr]_[A-Za-z0-9_]{30,}'),
    'AWS access key': re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}'),
    'bearer literal': re.compile(rb'Bearer [A-Za-z0-9_-]{32,}'),
    'private endpoint': re.compile(rb'https?://(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)'),
}
FORBIDDEN = {'tdata', 'profiles.ini', 'logins.json', 'key4.db', 'cookies.sqlite', 'current.json', 'installation.json', 'pending.json', 'bridge-token', '.env'}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def scan(name, data):
    errors = []
    if set(Path(name).parts) & FORBIDDEN:
        errors.append('forbidden filename')
    if Path(name).suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.sqlite', '.db', '.zip', '.xpi'):
        errors.append('unreviewed binary asset')
    for label, pattern in PATTERNS.items():
        if pattern.search(data):
            errors.append(label)
    return errors


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--history', action='store_true')
    args = p.parse_args()
    failures = []
    seen = set()
    if args.history:
        # Enumerate blobs in each commit's tree, including files later deleted.
        for commit in git('rev-list', '--all').decode().splitlines():
            for item in git('ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
                if not item:
                    continue
                metadata, rawname = item.split(b'\t', 1)
                mode, kind, oid = metadata.split()
                if kind != b'blob':
                    failures.append((commit, 'non-blob tracked entry'))
                    continue
                name = rawname.decode()
                if (name, oid) in seen:
                    continue
                seen.add((name, oid))
                errors = scan(name, git('cat-file', 'blob', oid.decode()))
                if mode == b'120000':
                    errors.append('tracked symlink')
                failures.extend((name, error) for error in errors)
    else:
        for name in git('ls-files', '-z').decode().split('\0'):
            if name:
                file = ROOT / name
                failures.extend((name, error) for error in scan(name, file.read_bytes()))
                if file.is_symlink():
                    failures.append((name, 'tracked symlink'))
    for name, reason in sorted(set(failures)):
        print(f'{name}: {reason}')
    print(f'Privacy scan: {len(failures)} findings')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
