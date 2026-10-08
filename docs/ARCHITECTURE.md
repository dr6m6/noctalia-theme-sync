# Architecture

Noctalia v5 is the only palette authority. A user template exports its resolved
semantic and terminal tokens to `palette.json`; an earlier template records the
wallpaper as plain text. A synchronous final hook calls `noctalia-theme-sync sync`.
No wallpaper path is interpolated into a shell command.

The existing publisher validates input, holds a file lock, reserves a monotonic
revision and atomically replaces `current.json`. Unchanged semantic state keeps
its revision. A checkpoint can restore a missing export without inventing a new
revision. The 48 Material roles and v1 schema remain compatible with the earlier
local bridge. Terminal roles are additive optional roles needed by Kitty.

The product layer loads data-driven adapter definitions. It substitutes only
validated `colors.<role>.default.hex` and `mode` expressions. It never evaluates
shell, arbitrary expressions, remote code or a second color extraction algorithm.
New file-only adapters need a JSON definition and a template, not engine edits.
Application activation with unusual formats can be added as a reviewed native
configuration operation; no untrusted plugin execution system is provided.

## Components

| Path | Responsibility |
| --- | --- |
| `src/noctalia_theme_sync/model.py` | v1 validation, bounded reads, atomic JSON, wallpaper checks |
| `publisher.py` | Existing revision/checkpoint algorithm, adapted imports and XDG |
| `adapters.py`, `assets/adapters/` | Native color files and activation operations |
| `cli.py` | Compatibility, selection, planning, lifecycle and optional consumer |
| `transaction.py`, `xdg.py` | Conflict detection, private baseline backup, durable journal |
| `bridge.py` | Existing asyncio HTTP/SSE + inotify implementation |
| `nix/`, `flake.nix` | Pinned package/dev shell and optional user service module |
| `tests/`, `scripts/` | Contract, isolated CLI, packaging and desktop smoke checks |

## Installation transactions

1. Resolve XDG paths and inspect Noctalia config/overlapping producers.
2. Reject symlink ancestors, hardlinks, non-owned files and unknown outputs.
3. Load the ownership manifest; verify every affected managed file's hash.
4. Preflight the full change set. No writes for `plan` or `--dry-run`.
5. Serialize writers with a per-user installation lock.
6. Record originals and a durable write-ahead journal, mode 0600 in private state.
7. Write/fsync/replace each changed file, then commit the manifest.
8. Remove the journal. On failure, restore files only if their contents still
   match the before/after state. External edits stop recovery.

Backups preserve original bytes and permissions. Uninstall restores the baseline
and retains an archived manifest; it stops on user edits rather than discarding
them. Empty directories, canonical state and private backups may remain. Rollback
is to the original installation baseline, not to an arbitrary prior software
version. After a crash, `rollback --recover` uses the journal.

The project does not resolve Home Manager symlink ownership or rewrite
`/etc/nixos`. A declarative package is compatible with imperative per-user
activation; wholly declarative dotfiles need writable theme destinations/includes.

## Bridge and consumers

The optional bridge watches the canonical file, not the wallpaper. It serves a
latest-state snapshot with bounded SSE queues and retains last valid state across
malformed writes/restarts. It never produces palettes. Default localhost only;
non-loopback bearer authentication is mandatory. Wallpaper bytes are opt-in and
restricted to current allowlisted regular raster images. There is no mutation API.

`--consume-existing` installs no second publisher. Its users can invoke `apply`
or run the optional inotify `watch` consumer. It does not modify existing hooks.
Bridge and consumer service lifecycles are separate from application installation.

## Technical choice

Reuse the stdlib bridge/publisher and licensed native Noctalia templates. Adding
Matugen/pywal would create another palette authority; a web framework or installer
framework would add dependencies without improving this small local pipeline.
The CLI and transaction layer solve gaps in the existing machine-specific scripts.

References: [Noctalia v5 template contract](https://docs.noctalia.dev/noctalia/theming/templates/),
[app theming](https://docs.noctalia.dev/noctalia/theming/app-theming/),
[XDG specification](https://specifications.freedesktop.org/basedir-spec/latest/),
[asyncio streams](https://docs.python.org/3/library/asyncio-stream.html).
