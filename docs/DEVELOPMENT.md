# Development and verification

Runtime: Python 3.11+, Linux, no third-party Python libraries. The Nix devShell
pins ruff, jsonschema and build tooling through flake.lock. GitHub CI additionally
runs Python 3.11/3.13 on Ubuntu using pinned development package versions.

```sh
nix develop --command ruff check src tests scripts bin
nix develop --command python -m unittest discover -s tests -v
python scripts/smoke.py
nix flake check
```

Without Nix use a venv, install the dev dependencies from CI and set `PYTHONPATH=src`.
All tests use temporary HOME/XDG/state and synthetic palette fixtures. Loopback
HTTP tests need permission to create local sockets. No account/profile data is
needed or read. Do not silently omit protocol tests when a sandbox blocks sockets.

## Coverage

- Four palette fixtures: purple/green, dark/light; every adapter output.
- v1 schema validation, malformed values, duplicate/oversized JSON handling.
- Doctor/list/plan and dry-run behavior; source and installed runtime invocation.
- Selective install, repeat install/update, baseline rollback/uninstall, original
  bytes/modes, independent removal, output adoption and user-edit conflicts.
- Symlink/hardlink/relative-XDG rejection, failure rollback and crash recovery.
- Real atomic replacement, inotify coalescing/parent recreation, degraded recovery.
- HTTP/SSE latest-state semantics, reconnect, revision suppression/regression,
  non-loopback policy, Origin checks, tokens and wallpaper allowlist/hash checks.
- Nix build, wheel/sdist packaging, isolated installation from source and wheel.
- Privacy scan of tracked tree/all history and gitleaks directory/history.

Application GUI rendering is not tested by CI. systemd startup in a real graphical
session is separate from subprocess bridge/protocol tests. Architecture support
other than the checked build platform is declared packaging support, not a claim
of visual certification.

## Build and package smoke

```sh
nix develop --command python -m build
# In a separate clean virtualenv:
python -m pip install dist/*.whl
python scripts/smoke.py --installed
```

The package contains templates, schema and upstream license notices. The checkout
launcher is dependency-free. `scripts/smoke.py` uses a mock Noctalia version and a
fresh relocated XDG environment to verify documented CLI commands. The mock does
not stand in for live Noctalia rendering.

## Native Noctalia pipeline smoke

With a real Noctalia v5 binary, run `python scripts/native_smoke.py`. It invokes
the Noctalia renderer and the installed publisher hook for all four fixtures,
checks sequential/unchanged revisions, and generates/removes selected adapters
including Kitty in isolated XDG. Its GSettings backend is memory-only and its
D-Bus/runtime are isolated. No live wallpaper or services are changed.

## Real desktop smoke

Run on a working Noctalia v5 session **after** ordinary tests:

```sh
python scripts/desktop_smoke.py
# Explicit optional live wallpaper cycle, after authorization:
python scripts/desktop_smoke.py --cycle-wallpaper
```

The script verifies output parity with the existing extracted GTK/Qt/btop/cava/
Neovim/tmux theme files when present, checks the native Noctalia renderer using
precomputed tokens, and installs/applies/uninstalls in an isolated HOME. It never
replaces the active implementation or starts another bridge.

The optional cycle generates a temporary synthetic image, changes the live
Noctalia wallpaper, waits for its existing canonical publisher, verifies changed
colors and isolated adapter output, then restores the original wallpaper and
palette in `finally`. It preserves the original mode. Persisted TOML wallpaper
state is restored to exact original bytes only if unrelated preferences did not
change concurrently. The source bridge/hook and its revision history remain live.
Use on a session with a canonical publisher that matches the active wallpaper.
If a process is killed outside Python's exception handling, restore the initial
wallpaper through Noctalia's native controls; do not delete revision state.

This confirms the source pipeline, export and isolated new implementation. It does
not claim the new project replaced the source desktop, tested a logout/login, or
visually certified experimental Telegram/Steam/Vesktop. Verify selected apps'
native activation and screenshots separately, preserving private desktop content.

## Publication

Use new history only. Never copy a personal migration workspace wholesale.

```sh
python scripts/check_privacy.py
python scripts/check_privacy.py --history
nix develop --command gitleaks dir --redact .
nix develop --command gitleaks git --redact --log-opts=--all .
```

Audit licenses and notices, all tree blobs, commit metadata and README links.
Publish with an intentionally public GitHub identity, never a personal email.
Private desktop evidence must stay outside the repository. See PROVENANCE.md
for extraction boundaries and optional v4 migration notes.
