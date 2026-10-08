# Installation

## Before installing

Use an ordinary user account, never `sudo`. Start from a working Noctalia v5
session. Install the target applications separately. Inspect:

```sh
./bin/noctalia-theme-sync doctor
./bin/noctalia-theme-sync list
./bin/noctalia-theme-sync plan --adapters kitty,btop
./bin/noctalia-theme-sync install --adapters kitty,btop --dry-run
```

`doctor` checks Linux, Python/Noctalia and paths, lists detected apps/dependencies
and validates an existing export. It does not promise to detect every native
host, GTK theme, sandboxed application or runtime GUI preference.

A nonzero plan means a blocker. Existing builtin/community adapters should be
removed from your own enabled Noctalia adapter list before installing a replacement.
Keep the remaining adapters enabled. The CLI does not change that list for you.
An existing user template writer must likewise be resolved. A symlink is not made
writable by `--adopt-existing`.

## Linux checkout, no package manager

```sh
git clone https://github.com/dr6m6/noctalia-theme-sync.git
cd noctalia-theme-sync
./bin/noctalia-theme-sync install --adapters kitty,btop
noctalia msg templates-apply
```

Only Python 3.11+ is needed for this CLI. Install the dependencies for your selected
apps through your distro. The installer copies its standalone runtime into XDG
data and creates a CLI in `~/.local/bin`; no checkout dependency remains. The
interpreter used for installation must remain available. Add that bin directory
to `PATH`, or invoke the path directly. No root, downloaded shell script or
`curl | sudo bash` installation is used.

Alternative package build:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/noctalia-theme-sync doctor
```

This needs setuptools as a build dependency; runtime has no third-party Python
dependencies. Keep that virtualenv while its interpreter is used by the installed
CLI, or reinstall using your permanent Python interpreter. PyPI publishing is
not part of this release.

## NixOS

The committed flake lock pins nixpkgs. Quick per-user install:

```sh
nix profile install github:dr6m6/noctalia-theme-sync
noctalia-theme-sync doctor
noctalia-theme-sync install --adapters kitty,btop
noctalia msg templates-apply
```

For a read-only trial you can use `nix run github:dr6m6/noctalia-theme-sync -- doctor`.
Keep the installed Nix profile or module package while integrations use its Python
interpreter; a transient `nix run` alone is not a persistent installation across GC.
Uninstall integrations before removing the corresponding Nix package.

For a declarative package and optional service, add an input and module to your
own flake. Example fragments, not a replacement for your configuration:

```nix
# flake inputs
inputs.noctalia-theme-sync.url = "github:dr6m6/noctalia-theme-sync";

# Within your nixosSystem module list
modules = [
  inputs.noctalia-theme-sync.nixosModules.default
  {
    programs.noctalia-theme-sync.enable = true;
    # Optional, after confirming no existing theme bridge is running:
    # programs.noctalia-theme-sync.bridge.enable = true;
  }
];
```

You own any system activation/rebuild. This project never edits `/etc/nixos`.
The module installs the CLI and, only when opted into, one systemd **user** bridge
unit. It does not install Noctalia, applications, GTK themes or compositor config.
Use the CLI to install chosen writable user integrations. Home Manager is optional.

Choose the module service **or** `install --bridge`; avoid managing the same unit
from both. For the module service use ordinary `systemctl --user` commands. Its
restart/enablement is controlled by your declaration, not the CLI manifest.
Normal palette changes never require a rebuild.

## Files and XDG

| Purpose | Path relative to XDG home |
| --- | --- |
| Noctalia user fragment | CONFIG: `noctalia/noctalia-theme-sync.toml` |
| Installed runtime/assets | DATA: `noctalia-theme-sync/runtime/` |
| CLI | `NTS_BIN_HOME`, default `$HOME/.local/bin` |
| Installation manifest/journal/backups | STATE: `noctalia-theme-sync/` |
| Canonical palette/checkpoint/token/cache | STATE: `noctalia/theme-sync/` |
| Bridge configuration | CONFIG: `noctalia/theme-sync/bridge.json` |
| Optional staged user unit | CONFIG: `systemd/user/noctalia-theme-sync-bridge.service` |
| Native app theme/config files | Listed in `plan`, per adapter |

Unset or empty XDG variables use spec defaults. Relative XDG paths are rejected.
Relocate config/data/state/cache/bin **consistently** and use the same environment
for Noctalia, CLI and services. The installation manifest records resolved paths;
do not move a live installation between homes without uninstall/reinstall.
Backups may contain your original app configuration: keep them private.

## Existing canonical pipeline

If `current.json` is already produced by a trusted local Noctalia v5 publisher:

```sh
./bin/noctalia-theme-sync validate "${XDG_STATE_HOME:-$HOME/.local/state}/noctalia/theme-sync/current.json"
./bin/noctalia-theme-sync install --adapters neovim --consume-existing
noctalia-theme-sync apply
# Optional continuous file consumer, no HTTP listener or additional publisher:
noctalia-theme-sync watch
```

Use `watch --reload` to explicitly notify owned apps. This mode preserves existing
hooks and does not add a persistent consumer service. An export without terminal
roles cannot generate the upstream Kitty template. Do not invent those colors;
upgrade your export through Noctalia or select other adapters.

## Updates, disable and uninstall

Run the **new version's** CLI from a refreshed checkout or Nix package:

```sh
./bin/noctalia-theme-sync update --dry-run
./bin/noctalia-theme-sync update
noctalia-theme-sync disable --adapters btop
```

`install` adds adapters; `disable` removes selected adapters. Removing the last
adapter restores the whole installation. `update` refreshes installed integrations
without downloading source. Experimental opt-in persists for installed adapters.
There is no unattended self-updater.

For a CLI-managed bridge:

```sh
noctalia-theme-sync service stop
noctalia-theme-sync service disable
noctalia-theme-sync uninstall --dry-run
noctalia-theme-sync uninstall
```

Omit service commands if no bridge unit was installed. Restore GUI-selected
Telegram/Vencord/Steam preferences yourself after removing the generated theme;
those preferences and account files were never changed by this project. Remove
Neovim's manually added colorscheme command from your init if desired. Canonical
state and private backups are retained so uninstall does not erase user data.
