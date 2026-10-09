# Agent instructions

This independent Linux/Python project consumes Noctalia v5 colors. Noctalia is the
only palette source; the optional bridge is local HTTP/SSE, not a producer.

## Inspect and install

1. Read README, docs/INSTALL.md and docs/ADAPTERS.md. Identify the user's OS,
   Python (`>=3.11`), `noctalia --version`, XDG environment and actual installed apps.
2. Run `./bin/noctalia-theme-sync doctor` and `list`. Select requested adapters,
   then `plan --adapters IDS` and `install --adapters IDS --dry-run`.
3. Resolve reported blockers; do not bypass them by deleting ownership manifests,
   force-copying dotfiles or breaking Nix/Home Manager symlinks. Explain genuine
   conflicts. `--adopt-existing` needs user authorization to manage the old output;
   an explicitly authorized installation request can supply that authorization.
   A real adoption also requires `--from-plan` created by `plan --write-plan`;
   inspect its blockers and exact changes first (docs/CONTROLLED-ADOPTION.md).
4. Install only selected integrations. Experimental adapters require opt-in.
   Do not start or enable services unless requested. Never duplicate an existing
   bridge, hook or compositor/session integration.
5. Apply with `noctalia msg templates-apply`, check `status`, validate canonical
   export and verify the selected applications through documented native activation.
   Obtain authorization before disturbing wallpaper, app processes or session state.
   Never claim file tests prove pixels/live reload.
6. Preview `uninstall --dry-run`. To remove, stop/disable the owned bridge first,
   then `uninstall`/`rollback`. For a crash, use `rollback --recover`.

## What can change

Within the repository: `src/`, adapter assets, tests, docs, packaging and CI.
Within a user's HOME: only planned, backed-up XDG files via CLI, plus the narrowly
scoped Codex `config.toml` theme selection and owned `.tmTheme` under CODEX_HOME.
Preserve non-theme Codex edits, auth, models, sandbox and every pet asset/preference.
Inspect native_context in the private manifest; do not change installed target roots
by exporting new environment variables. Never invoke known VPN/sudo/pet wrappers
for version checks; use explicit NTS_CODEX_BIN pointing to a native executable.
Never modify `/etc/nixos`, compositor config, account files, Firefox profiles,
Telegram tdata, wallpapers, personal migrations or unrelated app configuration.
Do not use sudo, change a system generation, modify binaries/ASAR, open Electron
debug ports or download executable plugins for this project's installation.
NixOS module examples are user-owned declarations, not permission to replace a flake.

## Development and validation

```sh
nix develop --command ruff check src tests scripts bin
nix develop --command python -m unittest discover -s tests -v
python scripts/smoke.py
nix flake check
python scripts/check_privacy.py --history
nix develop --command gitleaks dir --redact .
nix develop --command gitleaks git --redact --log-opts=--all .
```

Without Nix, install dev requirements from `.github/workflows/ci.yml` in a venv,
set `PYTHONPATH=src`, and run the same Python tests/smoke. HTTP/SSE tests require
loopback sockets; use an allowed local executor, never skip their failures silently.
Desktop smoke: `python scripts/desktop_smoke.py`, optionally `--cycle-wallpaper`
only when explicitly authorized; it restores the initial wallpaper in `finally`.
See docs/DEVELOPMENT.md for scope and failure recovery.

New adapters start experimental. Add a JSON definition and bounded native template;
keep explicit dependency/reload/limitation metadata. Validate both modes and
multiple palettes, independent install, repeat install, conflicts and removal.
Record third-party source/commit/license before copying code. Preserve notices in
all distributions. Do not add a second palette generator or execute template data.

Protect the canonical schema, semantic revisions, localhost/authentication policy,
atomic writes, XDG portability and conflict-preserving rollback. No telemetry.
Keep private screenshots, raw snapshots, logs and backups outside Git. Before any
public push, scan tracked tree and all history, then check CI and install docs.
Publish only if specifically requested and provenance/security checks pass.

For v0.2 adapters use `plan --adapters fastfetch,codex --experimental`, then dry-run.
Fastfetch custom layouts need the actual NTS_FASTFETCH_CONFIG during initial install.
Codex native syntax theme requires restart; no fork/live-reload/pet coupling is
allowed. Check `adapter_states` but do not equate configuration `active` with pixels.
Opt-in release desktop verification: `python scripts/release_desktop_smoke.py
--cycle-wallpaper --codex-bin /absolute/native/codex --output /absolute/private/evidence`.
This creates temporary windows and cycles wallpaper twice, restores in finally,
queries live Kitty, and captures native Codex `/theme`. Review images yourself;
CI only validates files. Keep unreviewed captures outside Git.
