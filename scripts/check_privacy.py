#!/usr/bin/env python3
"""Check the complete tracked tree/history without printing sensitive values."""
import argparse
import hashlib
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
# Exact manually reviewed native screenshots; all other binary images remain blocked.
REVIEWED_IMAGES = {'docs/screenshots/kitty-fastfetch-purple.png': '07364f437ac7c887ad777d70ec0f2d821704e853eca1302e8dc164a8c99b5089', 'docs/screenshots/kitty-fastfetch-green.png': '0f3ceb5bd8ff94500a95c28880a5f57d1c6667bba8bf262e2b0f4aee4cbd4f98', 'docs/screenshots/codex-purple.png': '497a4904a4186d146db4c061129d28164f07a932cd539a501cd1f8c1eaa9dbf1', 'docs/screenshots/codex-green.png': 'd0bd1dfbfee70900a3b087d7d243654a1c138725e3271b180ef199caae459c60'}

FORBIDDEN = {'tdata', 'profiles.ini', 'logins.json', 'key4.db', 'cookies.sqlite', 'current.json', 'installation.json', 'pending.json', 'bridge-token', '.env'}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def scan(name, data):
    errors = []
    if set(Path(name).parts) & FORBIDDEN:
        errors.append('forbidden filename')
    if Path(name).suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.sqlite', '.db', '.zip', '.xpi'):
        if REVIEWED_IMAGES.get(name) != hashlib.sha256(data).hexdigest():
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
