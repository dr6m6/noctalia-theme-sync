# noctalia-theme-sync

[![CI](https://github.com/dr6m6/noctalia-theme-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/dr6m6/noctalia-theme-sync/actions/workflows/ci.yml)

Bring your **Noctalia v5 palette** to Linux applications, with selective installation,
private backups, conflict checks and a reversible per-user CLI. An optional local
bridge exposes versioned JSON and server-sent events for other consumers.

Independent community project. Not affiliated with or endorsed by Noctalia.
No cloud account, telemetry, remote server, compositor configuration or Home Manager required.

```text
Noctalia v5 → canonical palette → theme-sync core → selected app adapters
                                    └→ optional localhost JSON/SSE bridge
```

Noctalia generates the colors. This project exports those colors, writes native
application theme files and manages their installation. It does not extract a
second palette or require the author's NixOS configuration.

## Requirements

- Linux, Python **3.11+**, Noctalia **v5** (verified with **5.2.1**).
- Your own working Noctalia configuration and palette/wallpaper setup.
- Applications and their optional theme dependencies installed separately.
- Writable per-user XDG configuration. Nix/Home Manager symlinks are rejected;
  use writable includes or declare the equivalent files yourself.

NixOS is the primary development platform. The dependency-free CLI also runs on
other Linux distributions with these requirements; distro packaging, Flatpak
paths and every application version have not been certified.

## Supported applications

| Adapter | Status | Reload / activation |
| --- | --- | --- |
| GTK3 / GTK4 | Supported | Restart; GTK3 requires adw-gtk3 |
| Qt5 / Qt6 | Supported | qt5ct/qt6ct platform theme; restart, optional notification |
| Kitty | Supported | Managed include; Ctrl+Shift+F5 or explicit `--reload` |
| Firefox | Supported | Pywalfox extension + Noctalia native host; sync pushes live |
| Neovim | Supported | `:colorscheme noctalia`; add to your init yourself |
| tmux | Supported | Managed include; sync reloads default server |
| btop | Supported | Restart or reselect theme |
| cava | Supported | Native theme selection; explicit `--reload` or restart |
| Vesktop | Experimental | Enable local Vencord theme in the GUI |
| Telegram | Experimental | Import native theme in GUI; next normal start |
| Steam / Millennium | Experimental | Existing Material-Theme + manual CSS import |
| AFFiNE, icons | Unavailable | Excluded from this release |

“Supported” means a tested file generation and installation contract, using
native formats and established local integrations. CI does **not** verify rendered
application pixels. Detailed dependencies, tested scope and limitations:
[adapter guide](docs/ADAPTERS.md). Experimental adapters are opt-in.

## Quick start

Inspect the plan before applying it. Example for two independent integrations:

```sh
git clone https://github.com/dr6m6/noctalia-theme-sync.git && cd noctalia-theme-sync
./bin/noctalia-theme-sync doctor && ./bin/noctalia-theme-sync plan --adapters kitty,btop
```

```sh
./bin/noctalia-theme-sync install --adapters kitty,btop
noctalia msg templates-apply
```

The installed CLI is `$HOME/.local/bin/noctalia-theme-sync` by default. Add that
directory to `PATH` if needed. Generated themes update through one Noctalia
publisher hook. An initial installation without an existing export waits for
Noctalia to apply its templates. Kitty reload is a separate application action.

`--auto` selects detected supported applications; explicit `--adapters` is more
predictable. `--experimental` permits named experimental integrations.

```sh
noctalia-theme-sync list
noctalia-theme-sync install --auto --dry-run
noctalia-theme-sync status
noctalia-theme-sync update --dry-run
noctalia-theme-sync apply --reload
noctalia-theme-sync disable --adapters btop --dry-run
```

Updates refresh integrations from the version of the CLI you invoke; they do not
download code. After updating your checkout, run its `./bin/noctalia-theme-sync update`.

## NixOS

Install a persistent per-user package from the pinned flake:

```sh
nix profile install github:dr6m6/noctalia-theme-sync
noctalia-theme-sync install --adapters kitty,btop
```

The flake provides a package, dev shell and optional NixOS module. Declarative
package/service example: [installation guide](docs/INSTALL.md#nixos).
No `nixos-rebuild` is needed for wallpaper or palette changes.

## Configuration and existing installations

All runtime files use `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `XDG_DATA_HOME` and
`XDG_CACHE_HOME`, with their standard defaults. Optional `NTS_BIN_HOME` relocates
the CLI. See the [path table](docs/INSTALL.md#files-and-xdg).

The installer stops on existing producers, enabled overlapping Noctalia builtins,
unmanaged outputs, symlinks and edited managed files. Disable an overlapping
integration yourself before installing its replacement. `--adopt-existing`
explicitly backs up a pre-existing generated file; it does not suppress producer
or symlink conflicts.

An existing canonical publisher can be retained with `--consume-existing`.
That mode installs **no publisher hook**. Run `apply` manually or opt into
`watch` to consume its atomic updates. The existing export must satisfy the v1
schema; Kitty also needs Noctalia terminal tokens.

## Optional bridge

```sh
noctalia-theme-sync install --adapters btop --bridge
noctalia-theme-sync service start
curl --noproxy '*' http://127.0.0.1:8765/health
```

Service start and persistent enablement are explicit. The installer does not
start another daemon. The default listener is `127.0.0.1:8765`; non-loopback
configuration always requires a bearer token. Wallpaper **bytes are disabled by
default** and need an explicit directory allowlist. Theme JSON retains the
wallpaper path as protocol metadata. Read [the protocol](docs/PROTOCOL.md) before
exposing it beyond localhost. No firewall or remote access is configured.

## Uninstall and rollback

```sh
noctalia-theme-sync uninstall --dry-run
noctalia-theme-sync uninstall
```

`rollback` restores the original installation baseline, like `uninstall`.
`rollback --recover` only recovers an interrupted transaction. For a bridge,
stop it and disable its persistent unit first. Edited managed files stop removal
so your changes can be preserved. Private backups and canonical state remain in
XDG state; accounts, Firefox profiles, Telegram tdata, documents and wallpapers
are never removed. [Recovery instructions](docs/TROUBLESHOOTING.md#rollback).

## Troubleshooting and limitations

Start with `doctor`, `status` and [troubleshooting](docs/TROUBLESHOOTING.md).
Qt needs its platform theme configured before launch. GTK live reload depends on
application/toolkit support; this project deliberately does not toggle global
portal settings. Firefox requires its extension/native host. Neovim and Vencord
need native activation. Steam, Telegram, Flatpak and application version coverage
remain limited. No binary patches, Electron debugging/injection or automatic
application restarts are used.

Safe installation screenshots are not bundled: the source desktop contains
personal content. The release includes synthetic palette fixtures and a
reproducible [desktop smoke procedure](docs/DEVELOPMENT.md#real-desktop-smoke).

## Development and contributions

```sh
nix develop --command python -m unittest discover -s tests -v
nix develop --command ruff check src tests scripts bin
```

Also run `python scripts/smoke.py` and `nix flake check`.
[Development](docs/DEVELOPMENT.md), [architecture](docs/ARCHITECTURE.md),
[contributing](CONTRIBUTING.md), [provenance](docs/PROVENANCE.md) and
[license notices](NOTICE) explain the contracts and validation scope.

For coding agents: [AGENTS.md](AGENTS.md) and the
[paste-ready installation request](docs/AI-INSTALL.md).
Optional migration notes: [v4 → v5](docs/migration/v4-to-v5.md).

## Быстрый старт по-русски

Нужны Linux, Python 3.11+ и уже работающая Noctalia v5. Сначала проверьте систему
и план; выбирайте только нужные приложения:

```sh
./bin/noctalia-theme-sync doctor
./bin/noctalia-theme-sync plan --adapters kitty,btop
./bin/noctalia-theme-sync install --adapters kitty,btop
noctalia msg templates-apply
```

CLI устанавливается в `~/.local/bin`. Откат: `noctalia-theme-sync rollback`.
При конфликте не перезаписывайте конфиги вслепую: смотрите сообщения и
[инструкцию](docs/TROUBLESHOOTING.md). Экспериментальные адаптеры требуют
`--experimental`. Проект не меняет `/etc/nixos`, compositor, аккаунты и профили.

## License

MIT for project code. The redistributed Noctalia templates retain their MIT
copyright notice. See [LICENSE](LICENSE), [NOTICE](NOTICE) and
[upstream notices](licenses/Noctalia-MIT.txt).
