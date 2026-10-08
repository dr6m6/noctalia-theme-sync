#!/usr/bin/env python3
"""Publish Noctalia-rendered palette; this is the only revision writer."""
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from .model import atomic_json, config, paths, read_json, semantic, validate, validate_palette, wallpaper_file


def publish():
    _, state = paths()
    from .xdg import safe
    for name in ('.publish.lock', 'palette.json', 'palette-wallpaper.txt', '.revision.json', 'current.json'):
        safe(state / name)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(state / '.publish.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _publish_locked(state)


def _publish_locked(state):
    palette = read_json(state / 'palette.json')
    validate_palette(palette)
    wallpaper = (state / 'palette-wallpaper.txt').read_text().removesuffix('\n')
    asset = None
    if wallpaper:
        try:
            asset, _ = wallpaper_file(wallpaper, config()['wallpaper_roots'])
        except (OSError, ValueError):
            pass  # Theme still publishes if the image is unavailable/unshareable.
    payload = {'schema_version': 1, 'source': 'noctalia-v5', 'mode': palette['mode'],
               'wallpaper': wallpaper, 'colors': palette['colors'], 'wallpaper_asset': asset,
               'palette_sha256': hashlib.sha256(json.dumps(palette, sort_keys=True).encode()).hexdigest()}
    current = state / 'current.json'
    old = None
    try:
        old = validate(read_json(current))
    except (OSError, ValueError):
        pass
    counter = 0
    checkpoint = {}
    try:
        checkpoint = read_json(state / '.revision.json')
        counter = checkpoint['revision']
        if type(counter) is not int or counter < 0:
            raise ValueError('invalid revision counter')
    except FileNotFoundError:
        pass
    # Corrupt counter fails closed: never silently reuse revisions.
    digest = hashlib.sha256(json.dumps(semantic(payload), sort_keys=True).encode()).hexdigest()
    if old is not None:
        counter = max(counter, old['revision'])
        if semantic(old) == semantic(payload):
            meta = {'revision': counter, 'semantic_revision': old['revision'],
                    'semantic_sha256': digest, 'generated_at': old['generated_at']}
            if checkpoint != meta:
                atomic_json(state / '.revision.json', meta)
            return old
    if old is None and checkpoint.get('semantic_sha256') == digest:
        # Recover a missing/corrupt export of identical state without a new revision.
        payload['revision'] = checkpoint['semantic_revision']
        payload['generated_at'] = checkpoint['generated_at']
    else:
        payload['revision'] = counter + 1
        payload['generated_at'] = datetime.now(timezone.utc).isoformat()
    payload['updated_at'] = payload['generated_at']  # existing consumer alias
    validate(payload)
    # Reserve first: a crash can skip a number, but never reuse one.
    atomic_json(state / '.revision.json', {'revision': max(counter, payload['revision']),
                'semantic_revision': payload['revision'], 'semantic_sha256': digest,
                'generated_at': payload['generated_at']})
    atomic_json(current, payload)
    return payload


if __name__ == '__main__':
    publish()
