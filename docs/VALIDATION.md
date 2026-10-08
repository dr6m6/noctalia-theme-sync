# Initial validation record

Validated on 2026-10-08 before public publication. The source was a working
NixOS/Niri/Noctalia v5.2.1 session. Raw desktop snapshots/logs remain private,
outside Git; no source profiles, wallpapers, account data or old history are included.

| Check | Local result |
| --- | --- |
| Python stdlib/unit/HTTP/SSE/inotify/lifecycle tests | 29 passed in pinned devShell, including schema validation |
| Lint | ruff passed |
| Four synthetic palettes, all adapters | Passed; purple/green, dark/light |
| Isolated source CLI installation | Doctor/list/plan/dry-run/install/repeat/update/apply/rollback preview/uninstall passed |
| Native Noctalia pipeline | Real renderer → exported tokens → installed hook → publisher → selected adapters, four semantic revisions and unchanged-repeat suppression passed |
| Source desktop parity | GTK3/GTK4/Qt/btop/cava/Neovim/tmux output bytes matched existing implementation |
| Live wallpaper change | Temporary synthetic wallpaper changed canonical colors and isolated selected adapters; original wallpaper, mode, colors and persisted TOML restored |
| Active desktop replacement | Not performed; original hooks/bridge/configuration retained |
| Existing bridge collision | No new bridge started on its port |
| Optional bridge lifecycle | Real child process on ephemeral localhost port, health check and graceful SIGTERM passed |
| Nix package/checks | x86_64-linux build passed; aarch64-linux output exists but was not locally built |
| Privacy/secret scans | New tree clean; publication also checks every commit blob and gitleaks history |

The workflow in `.github/workflows/ci.yml` runs Python 3.11/3.13, source and wheel
installation, Nix checks and secret/history scans. See the repository's actual
Actions runs for remote results; this document does not substitute for a CI run.

Scope limits: no pixel-level CI, logout/login test, full bespoke Telegram/Steam/
Vesktop/icon rice parity, external security audit or all-distro certification.
Experimental adapters remain opt-in. Native GUI activation/reload still needs the
corresponding applications; generating correct files alone does not certify pixels.
