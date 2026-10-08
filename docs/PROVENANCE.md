# Source audit and provenance

The public project is a clean extraction with new Git history. The source workspace
was a personal migration/development directory, not a publishable product tree.
No old Git history, whole directory, runtime state or personal configuration was
copied. Paths below identify source components relative to that local workspace;
the workspace itself is neither a dependency nor part of the distribution.

| Public component | Source component | Treatment |
| --- | --- | --- |
| `model.py` | `theme-bridge/model.py` | Preserve v1 validation, atomic IO, safe wallpaper checks; use XDG; disable image sharing by default. |
| `publisher.py` | `theme-bridge/publish-state.py` | Preserve revision/checkpoint semantics; package imports and filesystem safeguards. |
| `bridge.py` | `theme-bridge/bridge.py` | Preserve asyncio/inotify/HTTP/SSE and authentication; package imports/lifecycle fixes. |
| v1 schema | `theme-bridge/schema-v1.json` | Preserve existing machine-readable contract. |
| Canonical export templates | Active local `noctalia/templates/current-theme.json`, `wallpaper.txt` | Code only, no rendered values; additive Noctalia terminal tokens. |
| Neovim/tmux templates | Active local `noctalia/templates/neovim.lua`, `tmux.conf`, originally `pc-theme/prepare-user.py` | Keep the existing locally authored semantic projection. |
| GTK/Qt/Kitty/btop/cava templates | Installed Noctalia 5.2.1 assets | MIT verified at exact upstream commit; notices and hashes retained. |
| Bridge tests | `theme-bridge/tests.py` | Preserve mock palette, real filesystem/HTTP/SSE tests; package adaptation. |
| CLI/transactions/XDG/packaging | New project code | Replace machine-specific installation scripts with guarded per-user lifecycle. |
| Small Firefox/native experimental projections | New project code informed by existing native integration formats | Independently authored; no unlicensed community/base template copied. |
| Migration note | Personal v4→v5 work and upstream v5 docs | General observations only; no configuration dump or automatic migrator. |

## Excluded material

- `baseline/`, `backup/`, `evidence/`, `staged/`, `final/` as whole trees.
- Personal NixOS hardware/modules/flake inputs and `/etc/nixos` snapshots.
- v4 caches, notifications, account settings, wallpapers and migration state.
- Firefox profiles/extensions, Telegram tdata, Steam accounts/games, VPN config.
- `migrate-rice.py`, system activation/rebuild, recorder, poweroff and rice rollback scripts.
- `pc-theme` app cleanup/MIME/system operations and desktop session orchestration.
- `visual-integration` screenshots, custom rice, icon artwork/tooling and base CSS.
- Community Telegram/Steam/Pywalfox templates without established redistribution notices.
- Material Discord base styles and binary/debugging/injection techniques.

`app-theme-sync/REPORT.md` and visual reports were used as local evidence of app
limitations, not included as public documentation or proof of the new package.
AFFiNE's lack of a supported production palette hook does not block this release.
Full bespoke Telegram/Steam/icon visual parity is explicitly not claimed.

## Rights and checks

Project-owned local bridge, publisher and custom projections are released under
MIT with the owner's authorization to create this public project. Redistribution
of native Noctalia templates is covered by their MIT license; exact upstream paths,
commit and SHA-256 hashes are in `licenses/provenance.json`. Their copyright and
license travel in the source, wheel and installed runtime. No external icon pack,
Material base CSS or other uncertain code is relicensed by this project.

Publication checks scan the new tracked tree and **every blob in every commit**,
plus gitleaks on directory/history. This is a reproducible scan, not a guarantee
about all future contributions. Private desktop test artifacts stay outside the
repository. Only sanitized test summaries are recorded publicly.
