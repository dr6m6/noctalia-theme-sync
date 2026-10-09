import json
import unittest
from pathlib import Path

from noctalia_theme_sync import adoption, transaction as tx, xdg
import test_product as product


class AdoptionTests(unittest.TestCase):
    setUp = product.ProductTests.setUp
    tearDown = product.ProductTests.tearDown
    call = product.ProductTests.call
    snapshot = product.ProductTests.snapshot

    def plan(self, names='neovim', *extra):
        path = str(self.root / 'reviewed.json')
        self.assertEqual(self.call('plan', '--adapters', names, '--consume-existing',
                                   '--adopt-existing', '--write-plan', path, *extra), 0)
        return path

    def guarded_install(self, path):
        return self.call('install', '--adapters', 'neovim', '--consume-existing',
                         '--adopt-existing', '--from-plan', path)

    def test_adoption_requires_review_and_restores_mode_bytes(self):
        p = xdg.base('config') / 'nvim/colors/noctalia.lua'
        xdg.write(p, b'-- custom before\n', 0o640)
        before = self.snapshot()
        self.assertEqual(self.call('install', '--adapters', 'neovim', '--consume-existing', '--adopt-existing'), 1)
        self.assertEqual(self.snapshot(), before)
        plan = self.plan()
        self.assertEqual(Path(plan).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.guarded_install(plan), 0)
        self.assertFalse(tx.load()['bridge'])
        self.assertFalse((xdg.base('config') / 'noctalia/noctalia-theme-sync.toml').exists())
        self.assertEqual(self.call('rollback'), 0)
        self.assertEqual(p.read_bytes(), b'-- custom before\n')
        self.assertEqual(p.stat().st_mode & 0o777, 0o640)

    def test_output_drift_after_plan_refuses_without_writes(self):
        plan = self.plan()
        p = xdg.base('config') / 'nvim/colors/noctalia.lua'
        xdg.write(p, b'-- external edit\n')
        before = self.snapshot()
        self.assertEqual(self.guarded_install(plan), 1)
        self.assertEqual(self.snapshot(), before)

    def test_mode_drift_after_plan_refuses_without_writes(self):
        p = xdg.base('config') / 'nvim/colors/noctalia.lua'
        xdg.write(p, b'-- original\n')
        plan = self.plan()
        p.chmod(0o640)
        before = self.snapshot()
        self.assertEqual(self.guarded_install(plan), 1)
        self.assertEqual(self.snapshot(), before)

    def test_new_fragment_after_plan_is_drift(self):
        plan = self.plan()
        xdg.write(xdg.base('config') / 'noctalia/new.toml', b'[theme]\nmode="light"\n')
        before = self.snapshot()
        self.assertEqual(self.guarded_install(plan), 1)
        self.assertEqual(self.snapshot(), before)

    def test_palette_drift_after_plan_is_drift(self):
        plan = self.plan()
        p = xdg.canonical() / 'current.json'
        d = json.loads(p.read_text())
        d['revision'] += 1
        p.write_text(json.dumps(d))
        before = self.snapshot()
        self.assertEqual(self.guarded_install(plan), 1)
        self.assertEqual(self.snapshot(), before)

    def test_personal_writer_different_filename_blocked_even_with_adoption(self):
        fragment = xdg.base('config') / 'noctalia/local.toml'
        fragment.write_text('[theme.templates.user.custom]\ninput_path="/templates/tmux.conf"\n'
                            'output_path="$XDG_CONFIG_HOME/tmux/themes/noctalia.conf"\n')
        before = self.snapshot()
        self.assertEqual(self.call('plan', '--adapters', 'tmux', '--consume-existing', '--adopt-existing'), 1)
        self.assertEqual(self.snapshot(), before)

    def test_braced_absolute_publisher_detected_and_preserved(self):
        p = xdg.base('config') / 'noctalia/local.toml'
        p.write_text('[theme.templates.user.published]\noutput_path="${XDG_STATE_HOME}/noctalia/theme-sync/palette.json"\n'
                     'post_hook="python local-publisher.py"\n')
        self.assertEqual(self.call('plan', '--adapters', 'neovim', '--adopt-existing'), 1)
        inv = adoption.inventory(['neovim'], True)
        self.assertEqual(len(inv['publishers']), 1)
        self.assertEqual(len(inv['hooks']), 1)
        plan = self.plan()
        original = p.read_bytes()
        self.assertEqual(self.guarded_install(plan), 0)
        self.assertEqual(p.read_bytes(), original)

    def test_orphan_rendered_palette_is_not_replaced_by_second_publisher(self):
        xdg.write(xdg.canonical() / 'palette.json', b'{}')
        self.assertEqual(self.call('plan', '--adapters', 'neovim'), 1)
        self.assertEqual(self.call('plan', '--adapters', 'neovim', '--consume-existing'), 0)

    def test_plan_never_overwrites_existing_or_follows_link(self):
        plan = self.plan()
        before = Path(plan).read_bytes()
        self.assertEqual(self.call('plan', '--adapters', 'neovim', '--write-plan', plan), 1)
        self.assertEqual(Path(plan).read_bytes(), before)
        link = self.root / 'link.json'
        link.symlink_to(plan)
        self.assertEqual(self.guarded_install(str(link)), 1)
        self.assertFalse(xdg.state().exists())

    def test_broken_output_symlink_fails_without_replacing_it(self):
        p = xdg.base('config') / 'nvim/colors/noctalia.lua'
        p.parent.mkdir(parents=True)
        p.symlink_to('missing.lua')
        self.assertEqual(self.call('install', '--adapters', 'neovim', '--consume-existing', '--adopt-existing'), 1)
        self.assertTrue(p.is_symlink())
        self.assertFalse(xdg.state().exists())

    def test_reviewed_blocked_plan_cannot_install(self):
        plan = str(self.root / 'blocked.json')
        p = xdg.base('config') / 'noctalia/local.toml'
        p.write_text('[theme.templates.user.neovim]\noutput_path="$XDG_CONFIG_HOME/nvim/colors/noctalia.lua"\n')
        self.assertEqual(self.call('plan', '--adapters', 'neovim', '--consume-existing',
                                   '--adopt-existing', '--write-plan', plan), 1)
        p.unlink()
        self.assertEqual(self.guarded_install(plan), 1)
        self.assertFalse(xdg.state().exists())

    def test_transaction_precondition_checks_read_inputs(self):
        p = xdg.base('config') / 'nvim/colors/noctalia.lua'
        xdg.write(p, b'original')
        expected = {str(p): adoption.signature(p)}
        p.chmod(0o640)
        with self.assertRaises(ValueError):
            tx.commit(tx.load(), {str(p): b'new'}, expected=expected)
        self.assertEqual(p.read_bytes(), b'original')
        self.assertFalse(xdg.state().exists())

    def test_consuming_requires_valid_snapshot(self):
        (xdg.canonical() / 'current.json').unlink()
        before = self.snapshot()
        self.assertEqual(self.call('install', '--adapters', 'neovim', '--consume-existing'), 1)
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_canonical_writers_are_blocked_in_consume_mode(self):
        for name in ('first', 'second'):
            p = xdg.base('config') / ('noctalia/' + name + '.toml')
            p.write_text('[theme.templates.user.' + name + ']\n'
                         'output_path="${XDG_STATE_HOME}/noctalia/theme-sync/palette.json"\n')
        before = self.snapshot()
        self.assertEqual(self.call('install', '--adapters', 'neovim', '--consume-existing'), 1)
        self.assertEqual(self.snapshot(), before)

    def test_publisher_path_alias_and_unknown_relative_output(self):
        p = xdg.base('config') / 'noctalia/local.toml'
        alias = str(xdg.canonical() / '../theme-sync/palette.json')
        p.write_text('[theme.templates.user.export]\noutput_path="' + alias + '"\n')
        self.assertEqual(len(adoption.inventory([], True)['publishers']), 1)
        p.write_text('[theme.templates.user.export]\noutput_path="relative/output"\n')
        self.assertTrue(adoption.inventory([], True)['blockers'])

    def test_pending_journal_is_a_plan_blocker(self):
        xdg.write(xdg.state() / 'pending.json', b'{}')
        before = self.snapshot()
        self.assertEqual(self.call('plan', '--adapters', 'neovim', '--consume-existing'), 1)
        self.assertEqual(self.snapshot(), before)

    def test_managed_mode_drift_is_preserved(self):
        plan = self.plan()
        self.assertEqual(self.guarded_install(plan), 0)
        p = xdg.base('config') / 'nvim/colors/noctalia.lua'
        p.chmod(0o640)
        before = self.snapshot()
        for args in [('apply',), ('update', '--dry-run'), ('rollback',)]:
            self.assertEqual(self.call(*args), 1)
            self.assertEqual(self.snapshot(), before)
