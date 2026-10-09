# Changelog

## v0.3.0

- Add controlled adoption with publisher/writer inventory, normalized output
  aliases and checksum-bound reviewed plans. Existing generated outputs require
  explicit adoption; conflicts and unknown edits are never force-overwritten.
- Add opt-in Neovim Shadow Mode with a private output, checksum-bound plans,
  isolated previews, existing transaction rollback and foreground SSE delivery
  through an already running bridge. No personal writers/hooks are disabled.
- Harden interrupted transactions: bind file and manifest content/permissions,
  preserve foreign edits, reject stale ownership state and fsync deletions.
  Legacy journals with ambiguous states fail closed; recovery is not a global
  filesystem snapshot or a compare-and-swap with external editors.
- Validate private roots and bearer-token files, reject header injection without
  leaking token values, and make screenshot mismatches fail the visual gate.
- Document preview versus adoption, live-delivery limits, rollback and the
  isolated native Neovim/Tree-sitter/UI acceptance scope. Shadow remains explicit
  opt-in: normal installation creates no shadow output or consumer service.

## v0.2.1

- Make bridge inotify/SSE tests wait for completed reloads rather than assuming
  fsync finishes within 250 ms. Perform coalescing writes as one uninterrupted
  burst so a loaded runner cannot accidentally exceed the debounce window.
- Exclude local build/dist/cache directories from Nix sources, so a checkout
  previously used to build a wheel remains reproducibly buildable.
- Adapter/runtime behavior is unchanged from v0.2.0. This patch follows a tag-CI
  timing failure; v0.2.0's main CI passed but its tag Nix job exposed the old race.

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
