# Troubleshooting

Run `doctor`, `status` and the same `plan` that you intend to install. These report
paths and reasons locally; do not paste raw configuration, theme snapshots,
wallpaper paths, backup manifests or tokens into public issues.

## No generated theme yet

After installing, run `noctalia msg templates-apply` in the live user session.
Check that Noctalia loads `noctalia-theme-sync.toml`, and that Noctalia and the CLI
share the same XDG environment. Noctalia owns wallpaper/mode selection; this CLI
does not generate another palette. `apply` only consumes an already valid v1
snapshot. In `--consume-existing` mode use `watch` or invoke `apply` after changes.

## Conflict or read-only configuration

The installer stops before mutation when an overlapping Noctalia builtin or
publisher is configured, when a generated output already exists, or when a path
contains a symlink/hardlink. Disable only the overlapping adapter in your own
Noctalia config; keep all other preferences. Use `--consume-existing` for a trusted
canonical publisher. `--adopt-existing` can back up an unmanaged generated theme
file; it does not override symlink protection or existing producers.

For Nix/Home Manager dotfiles, declare writable includes/theme destinations or
maintain those paths declaratively. The CLI never breaks a Nix store symlink or
modifies the author's `/etc/nixos` configuration.

## Colors generated but app unchanged

Consult [adapter activation](ADAPTERS.md#activation). GTK/btop may need restart,
Kitty needs reload, Qt needs its platform theme, Firefox needs Pywalfox and its
native host, Neovim needs `colorscheme`, and Vencord needs its local-theme selection.
`apply --reload` explicitly requests native notifications for supported owned
apps. No applications are forcibly restarted. Telegram/Steam are experimental.

## Rollback

`uninstall --dry-run` previews original-file restoration. `rollback` performs the
same baseline restore; it is not a version-manager command. `disable --adapters ID`
removes only chosen integrations. Removing the last adapter removes the core
installation. Stop/disable the CLI-managed bridge first, and stop a foreground
`watch` consumer before uninstalling.

If a managed file was edited, removal stops to preserve it. Copy your edited file
to a private safe location. Inspect the mode-0600 installation manifest under
`$XDG_STATE_HOME/noctalia-theme-sync/`: originals are base64 data and the installed
hash identifies the project-written version. Reconcile the file with that version
or merge your changes into the original before performing a restore. Do not delete
the whole manifest to bypass the check; it is the ownership and recovery record.
There is deliberately no force-overwrite flag.

An interrupted transaction leaves `pending.json`. Use:

```sh
noctalia-theme-sync rollback --recover --dry-run
noctalia-theme-sync rollback --recover
```

If a different process edited the affected file after interruption, recovery stops
as well. Preserve the external edit, inspect the before/after journal and reconcile
it first. Do not publish journal/backup contents. Uninstall archives an original
manifest under private `backups/` and leaves canonical state in place. Remove those
manually only when you no longer need them and understand what they contain.

## Bridge service

A CLI install with `--bridge` only stages the user unit. Start/enable explicitly:

```sh
noctalia-theme-sync service start
noctalia-theme-sync service enable
noctalia-theme-sync service status
journalctl --user -u noctalia-theme-sync-bridge.service
```

A busy port or existing active `theme-sync-bridge.service` blocks duplicate setup.
`/health` is 503 while waiting for a first valid export. Invalid/missing source
retains the last valid snapshot and reports `degraded`; fix the producer and the
inotify watcher will recover. Revisions must increase only for semantic changes.
A corrupted publisher counter fails closed; retain state and investigate rather
than resetting the counter silently.

Non-loopback listeners always require authentication. Do not place tokens in URLs
or logs. Wallpaper bytes are unavailable until explicit allowlisted roots are
configured. Use the module's `systemctl --user` lifecycle if the service is NixOS
module-managed instead of CLI-managed.
