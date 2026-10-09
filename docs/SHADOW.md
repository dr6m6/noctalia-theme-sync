# Neovim Shadow Mode

Shadow Mode renders a separate `noctalia-nts.lua` in an explicit private root.
The personal writer can keep generating `colors/noctalia.lua`; neither output
is adopted or overwritten by the other. No Noctalia fragment, native init/plugin,
publisher hook, service, bridge, wallpaper or default theme selection is changed.
Only Neovim is supported initially. This is a preview workflow inside the existing
CLI/renderer/transaction system, not another palette source or installer framework.

## Why render in the public core

The existing canonical v1 export is an envelope with `schema_version`, revision,
timestamp, mode, wallpaper and `colors`. Noctalia's documented
`theme --theme-json` accepts precomputed **dark/light token maps**, or fixed
palette keys such as `mPrimary`; these formats are different. For an independent
reference render, extract `{ "dark": palette.colors }` or `{ "light": palette.colors }`
and pass the same mode via `--default-mode`. Do not supply current.json directly
or invent the missing opposite-mode colors. The installed 5.2.1 rejects the
unconverted canonical fixture with “theme json contained no token maps”.

The public adapter already renders validated canonical roles without subprocesses.
Shadow reuses that renderer and template, changing only `vim.g.colors_name` to
`noctalia-nts`. The official offline CLI remains the independent reference.
`--render in:out` is suitable for isolated parity checks. `-c`, `--builtin-config`
and live `templates-apply` can execute hooks and are unnecessary here.

On Noctalia 5.2.1, even an atomic edit of templates.toml triggers the config
watcher, re-resolves the theme and queues all enabled templates because the
whole template configuration changed. Unchanged output bytes avoid the write,
but do not suppress successful templates' post_hooks. Therefore Shadow Mode
does not edit that file or ask Noctalia to reload.

Research sources: the installed `noctalia theme --help` and exact installed
Noctalia 5.2.1 source (`src/theme/cli.cpp`, `template_apply_service.cpp`,
`template_engine.cpp`, `src/config/config_service.cpp`). See the upstream
[Noctalia repository](https://github.com/noctalia-dev/noctalia). File generation,
native highlighting and visual evidence are separate checks.

## Private trial, with no production activation

Choose an absolute root outside your Noctalia/Neovim configurations, canonical
state, normal installation state and runtime. Its directory must be private.
Keep plans and evidence private too. Run namespace isolation when validating
untrusted native tools; changing HOME alone is not an IPC sandbox.

```sh
TRIAL=$(mktemp -d)
REVIEW=$(mktemp -d)/shadow-plan.json
# Explicit --palette is optional if a valid existing current.json is available.
noctalia-theme-sync shadow plan --root "$TRIAL" --palette /absolute/canonical-palette.json --write-plan "$REVIEW"
noctalia-theme-sync shadow install --root "$TRIAL" --palette /absolute/canonical-palette.json --from-plan "$REVIEW" --dry-run
# Inspect the exact private targets/checksums above, then:
noctalia-theme-sync shadow install --root "$TRIAL" --palette /absolute/canonical-palette.json --from-plan "$REVIEW"
noctalia-theme-sync shadow test --root "$TRIAL"
noctalia-theme-sync shadow status --root "$TRIAL"
# Optional separate temporary TUI; quitting closes its timer and test HOME:
noctalia-theme-sync shadow test --root "$TRIAL" --interactive
```

The CLI does not invoke Noctalia on install/apply/test or require its IPC.
The headless test uses a temporary HOME and **all** XDG homes/runtime, `-u NONE`,
no plugins, shada or swaps, and no inherited DBus/Niri/display/session environment.
It copies only the checked theme into its temporary standard colors directory.
This also permits native colorscheme reload after a terminal background response.
The interactive TUI uses your terminal but changes only its own temporary Neovim
session. It has a 1-second timer that accepts output bytes only when they match
the private ownership manifest's SHA256/mode, then refreshes its temporary copy.
Unknown edits retain the last accepted theme. No user init/plugins are loaded.

For another one-shot fixture:

```sh
noctalia-theme-sync shadow apply --root "$TRIAL" --palette /absolute/another-canonical.json
```

A one-shot render is **not live synchronization**. Repeat installation requires a
fresh reviewed plan because the manifest/input checksums have changed. With
unchanged inputs/outputs a repeated install preserves theme bytes and mtime.
Private state is separate from normal CLI ownership; normal apply/sync refuse a
shadow manifest instead of accidentally activating native outputs.

## Foreground live delivery through the existing bridge

```sh
noctalia-theme-sync shadow watch --root "$TRIAL" --events http://127.0.0.1:8765/v1/events
# Bounded probe of the next snapshot/event, then exit:
noctalia-theme-sync shadow watch --root "$TRIAL" --events http://127.0.0.1:8765/v1/events --max-events 1
```

This is one optional passive foreground consumer and one existing bridge
subscription. It makes GET requests only, adds no publisher/listener and creates
no systemd unit, startup command or persistent process. Cost: one Python process,
one SSE slot (the existing bridge has a bounded subscriber pool), and a Neovim
timer only while its preview runs. Installation alone starts none of these.
Stop with Ctrl+C; restart explicitly when needed. A permanent user service is a
separate authorization/deployment decision, not part of shadow install.

Only numeric loopback HTTP `/v1/events` URLs are accepted; queries, URL credentials,
redirects and HTTP proxies are refused. Optional `--token-file` reads an explicit
private existing bridge token; no token is created or printed. Frames are capped
at 64 KiB, canonical validation rejects duplicate keys, and event id must match
revision. Revision regressions/conflicting replays abort while retaining the
last valid theme. Reconnects use Last-Event-ID and back off 2–30 seconds.
HTTP/auth errors abort; unreachable sockets retry. Status reports a consumer
lock and last accepted revision, not proof that an application displays it.

An exclusive consumer lock prevents a second foreground consumer for the same
root; manual install/apply/removal refuse while it is held. Transactions still
serialize each write. Manual fixture application clears the remembered SSE id,
so the next bridge connection requests the current snapshot again. Production
wallpaper changes are neither required nor performed for testing.

The existing Noctalia writer registry is read with its original XDG roots.
Declared claims to the private output, including path aliases, are blockers even
when that output does not exist yet. Plans bind these read-only TOML checksums;
live events recheck writer claims before committing. Opaque third-party scripts
cannot all be discovered automatically: unknown edits still fail ownership checks.

## Files, conflicts and rollback

| Path relative to trial root | Purpose |
| --- | --- |
| `config/nvim/colors/noctalia-nts.lua` | Only managed adapter output, mode 0600 |
| `state/noctalia-theme-sync/installation.json` | Private ownership/original bytes/modes and delivery metadata |
| `state/noctalia-theme-sync/pending.json` | Transient existing transaction journal |
| `state/noctalia-theme-sync/.lock` | Existing transaction lock |
| `state/noctalia-theme-sync/consumer.lock` | Exclusive passive-consumer claim |
| `state/noctalia-theme-sync/backups/original-<sha256>.json` | Retained uninstall baseline |
| `test-*/` | Ephemeral preview HOME/config/cache/state/runtime; removed on exit |

Atomic temporary replacements remain in the same private target directories.
Existing unmanaged shadow outputs, symlink targets/ancestors, normal integration
root overlap, changed checksums/modes and unexpected manifest/journal targets
are blockers. No force/adopt flag bypasses them. The old writer's output is never
registered by shadow. Root/checksum checks narrow races, not a global filesystem
snapshot; keep the root private and do not edit managed files concurrently.

```sh
# Stop the foreground consumer first. Neither command contacts Noctalia:
noctalia-theme-sync shadow uninstall --root "$TRIAL" --dry-run
noctalia-theme-sync shadow uninstall --root "$TRIAL"
# Equivalent removal:
noctalia-theme-sync shadow rollback --root "$TRIAL"
# Interrupted transaction only, preserving unknown edits:
noctalia-theme-sync shadow rollback --root "$TRIAL" --recover
```

Uninstall restores originals and modes from the existing transaction system,
removes only owned shadow output and retains private metadata/backups. It never
recursively deletes the trial root or repairs unknown edits. Quitting a preview
restores the prior terminal session by ending the test process; ordinary Neovim
theme selection was never changed.

## Future per-session adoption; not performed by these commands

After separate approval, an existing Neovim session can temporarily add the
checked trial `config/nvim` to runtimepath and select `:colorscheme noctalia-nts`.
No templates.toml edit or disabling the old writer is needed. Return with
`:colorscheme noctalia` and remove the added runtimepath entry. Keep the old
file/template/plugin and a guarded rollback snapshot.

That temporary selection alone does **not** reload future shadow updates. Keep
the approved foreground SSE consumer running and explicitly reselect the
colorscheme, or approve a session-local guarded reload timer analogous to the
isolated preview. The personal watcher must be checked to reload only while
`colors_name == "noctalia"`; otherwise it could steal the selection back.
Do not edit init.lua/plugins or install a permanent consumer as part of this trial.

## Native verification

`scripts/shadow_smoke.py --output /absolute/fresh/evidence --reference /absolute/trusted/neovim.lua`
compares four fixtures with the real Noctalia offline renderer, native Neovim
RGB/highlights/Markdown/background, and rollback. Run inside an isolated HOME/XDG
namespace. Add `--visual` only in a namespace without `/run/user` or display/session
variables; it starts a private Xvfb/Kitty, validates live RGB and compares native
screenshots. Optional visual tools: Xvfb, Kitty, ImageMagick and Pillow. They are
test dependencies, not shadow runtime dependencies. Keep captures outside Git.

These checks use shipped native syntax, not the user's plugins/Treesitter/UI.
Pixel parity in the isolated sample is evidence for the theme renderer, not
acceptance of an existing production Neovim session or all terminal frontends.
