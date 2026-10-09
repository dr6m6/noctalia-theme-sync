import json
from pathlib import Path
import unittest
from unittest.mock import patch

from noctalia_theme_sync import transaction as tx, xdg
import test_product as product


class TransactionSafetyTests(unittest.TestCase):
    setUp = product.ProductTests.setUp
    tearDown = product.ProductTests.tearDown

    def interrupted(self):
        p = xdg.base('config') / 'nvim/colors/noctalia.lua'
        xdg.write(p, b'old', 0o640)
        original = xdg.write
        def crash(path, data, mode=0o600, **kwargs):
            if Path(path) == tx.manifest_path():
                raise OSError('power loss before manifest')
            return original(path, data, mode, **kwargs)
        with patch.object(xdg, 'write', side_effect=crash), patch.object(tx, 'recover', side_effect=OSError('power loss')):
            with self.assertRaises(OSError):
                tx.commit(tx.load(), {str(p): b'new'}, modes={str(p): 0o600})
        return p

    def test_recovery_preserves_mode_only_edit_and_manifest_edit(self):
        p = self.interrupted()
        p.chmod(0o644)
        with self.assertRaises(ValueError):
            tx.recover()
        self.assertEqual(p.read_bytes(), b'new')
        self.assertEqual(p.stat().st_mode & 0o777, 0o644)
        p.chmod(0o600)
        xdg.write(tx.manifest_path(), b'{"foreign":true}\n')
        with self.assertRaises(ValueError):
            tx.recover()
        self.assertEqual(p.read_bytes(), b'new')
        self.assertEqual(tx.manifest_path().read_bytes(), b'{"foreign":true}\n')
        self.assertTrue((xdg.state() / 'pending.json').exists())

    def test_recovery_restores_bytes_permissions_and_published_manifest(self):
        p = self.interrupted()
        journal = json.loads((xdg.state() / 'pending.json').read_text())
        # A crash after publishing the expected manifest must also recover.
        m = {'version': 1, 'files': {}, 'adapters': []}
        raw = json.dumps(m).encode()
        journal['manifest_after'] = {'sha256': xdg.digest(raw), 'mode': 0o600}
        xdg.write(tx.manifest_path(), raw)
        xdg.write(xdg.state() / 'pending.json', json.dumps(journal).encode())
        self.assertTrue(tx.recover())
        self.assertEqual(p.read_bytes(), b'old')
        self.assertEqual(p.stat().st_mode & 0o777, 0o640)
        self.assertFalse(tx.manifest_path().exists())
        self.assertFalse((xdg.state() / 'pending.json').exists())

    def test_atomic_write_preserves_edit_during_temp_fsync(self):
        p = xdg.base('config') / 'original'
        xdg.write(p, b'old')
        expected = xdg.signature(p)
        original = xdg.os.fsync
        def change(fd):
            p.chmod(0o640)
            original(fd)
        with patch.object(xdg.os, 'fsync', side_effect=change):
            with self.assertRaises(ValueError):
                xdg.write(p, b'new', expected=expected)
        self.assertEqual(p.read_bytes(), b'old')
        self.assertEqual(p.stat().st_mode & 0o777, 0o640)

    def test_stale_manifest_refused_before_journal(self):
        m = tx.load()
        xdg.write(tx.manifest_path(), b'foreign')
        with self.assertRaises(ValueError):
            tx.commit(m, {str(xdg.base('config') / 'output'): b'new'})
        self.assertFalse((xdg.state() / 'pending.json').exists())
        self.assertEqual(tx.manifest_path().read_bytes(), b'foreign')

    def test_corrupt_shapes_fail_without_recovery_writes(self):
        xdg.write(tx.manifest_path(), b'[]')
        with self.assertRaises(ValueError):
            tx.load()
        xdg.write(xdg.state() / 'pending.json', b'[]')
        with self.assertRaises(ValueError):
            tx.recover()
        self.assertEqual(tx.manifest_path().read_bytes(), b'[]')
