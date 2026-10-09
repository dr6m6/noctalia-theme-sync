# Changelog

## v0.2.0

- Add supported Fastfetch native JSONC color integration with preserved comments,
  modules, layout and custom logo sources; no new startup wrapper or daemon.
- Add opt-in experimental Codex native `.tmTheme` integration and conservative
  capability checks. Only `tui.theme` is owned; unrelated edits survive updates and
  removal. Stock Codex needs restart; no fork, auth, model, sandbox or pet changes.
- Pin native target homes/config paths for Noctalia hooks.
- Retain v0.1 Kitty generation/include/reload behavior; add effective config and
  later-override diagnostics with availability/install/activation/palette/reload
  evidence clearly separated from unobserved running colors.
- Expand isolated lifecycle/format/conflict tests and installation smoke; add
  opt-in two-wallpaper native desktop validation and reviewed screenshots.

## v0.1.0

Initial independent Noctalia v5 adapter CLI, transactional backups/rollback,
optional localhost bridge, Nix package/module, documentation and CI.
