# v0.2.0 validation

## Automated scope

Local result: **44 tests passed**, ruff and compileall passed, Nix flake/package
checks passed on x86_64-linux, source/native/installed smoke passed, privacy tree
and complete-history scans had zero findings, and gitleaks had zero leaks.
GitHub Actions is checked on the published release commit before release promotion.

Full Python unittest suite, ruff, compileall, Nix flake checks/package build,
source and installed-wheel smoke, native Noctalia template smoke, privacy scanning
of tracked tree plus every historical blob, and gitleaks tree/history are release
gates. CI runs Python 3.11/3.13, Nix package/module checks and secret scanning.
The Nix local build is x86_64-linux; aarch64-linux is defined but not locally built.

New coverage: both modes/multiple accents, JSONC comments/trailing commas/errors/
duplicates, custom logo/layout preservation, absent app configs/export, independent
adapter selection/removal, relocated XDG/CODEX_HOME, hook environment drift,
repeat install, scoped Codex native/user edits, conflicts, rollback and uninstall.
Native tests use isolated HOME; no CI check claims to validate app pixels.

## Real desktop acceptance (2026-10-09)

Noctalia 5.2.1, NixOS/Niri, Kitty 0.47.0, Fastfetch 2.63.1, stock Codex 0.160.1.
The public adapters were installed in an isolated HOME using a copy of the real
canonical palette. The original desktop installation/services were retained.

Two synthetic wallpaper changes produced distinct purple/green semantic palettes.
After each change:

- Fastfetch displayed the new native JSONC colors and original minimal logo/layout
  in a real Kitty window. Its screenshots were manually reviewed.
- A running Kitty preview received SIGUSR1; native terminal queries confirmed its
  foreground/background matched Noctalia native rendering. Existing desktop
  `themes/noctalia.conf` bytes matched that rendering in both cycles.
- Stock Codex was restarted with the updated generated theme. Native `/theme`
  displayed `noctalia-theme-sync (custom) (current)` and syntax preview colors
  visibly changed between purple/green. No model requests or login were made.

The original wallpaper, canonical color values/mode and Noctalia TOML bytes were
restored. Hash checks confirmed original Kitty/Fastfetch configs, Codex config/auth
and discovered pet files stayed unchanged. No new service or persistent public
adapter installation was left on the desktop. Session runtime revisions/timestamps
naturally advance when wallpaper changes. Existing running Codex/pet integration
was not replaced or restarted.

Reviewed captures: [Kitty/Fastfetch purple](screenshots/kitty-fastfetch-purple.png),
[green](screenshots/kitty-fastfetch-green.png), [Codex purple](screenshots/codex-purple.png),
[green](screenshots/codex-green.png).

## Limits

Stock Codex external live reload was not verified and is not promised. Its adapter
is experimental and scopes syntax/Markdown, while terminal chrome remains terminal
controlled. The existing local fork/pet patches are not product dependencies.
Visual acceptance covers the demonstrated versions only. Native queries prove
preview terminal state; they do not inspect every pre-existing terminal window.
Personal Braille artwork/animation wrappers were not redistributed or replaced.

## v0.2.1 CI stabilization

The v0.2.0 main workflow passed all jobs. Its separate tag workflow exposed an
existing test race: checking an SSE queue after a fixed 250 ms pause, before a
slow runner completed the background atomic fsync. The patch waits for an actual
completed inotify reload with a bounded timeout, and groups coalescing writes in
one uninterrupted burst. No adapter/bridge runtime code or visual theme changed.
A slow-cache-write regression deliberately exceeds the former pause; the patch
suite contains 45 tests. v0.2.1 is the recommended release; the tag history remains immutable.
