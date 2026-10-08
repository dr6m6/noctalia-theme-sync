# Theme Sync Protocol v1

The existing protocol is retained. UTF-8 JSON, at most 64 KiB. Noctalia is the
only palette producer. JSON API and SSE theme events carry the full canonical
snapshot without an envelope. [Machine-readable schema](../src/noctalia_theme_sync/assets/schema-v1.json).

## Snapshot

Required fields: `schema_version` (integer 1), `revision` (positive integer at most
2^53−1), `generated_at` (timezone-aware RFC3339), `mode` (`dark`/`light`),
`wallpaper` (absolute local path or empty string), `colors` (semantic names and
opaque `#RRGGBB` values). The schema requires 48 Material roles. `hover`,
`on_hover`, terminal tokens and future roles are additive; ignore unknown roles.
Color hex case is insignificant. Consumers should use matching foreground and
background semantic roles, not invent an independent dark/light palette.

Optional `source`, `palette_sha256`, `updated_at` and `wallpaper_asset` are
compatibility/diagnostic fields. `wallpaper_asset` is null when unavailable or
not allowed. Otherwise it contains a SHA-256 content `id`, relative URL
`/v1/wallpaper/current`, filename, raster MIME type and byte size.

Revisions are scoped to the persistent state directory. Mode, color roles,
wallpaper path or content metadata changes are semantic changes. Rewriting the
same state keeps the revision/timestamp; missing export recovery uses the
checkpoint's original revision. Gaps are possible after crashes. Compare `>`,
not `+1`. Retain the state directory; clearing it establishes a new source history.

## Endpoints

| Route | Behavior |
| --- | --- |
| `/health` | 200 with valid/retained snapshot; 503 before first valid state. `ok`, `degraded` or `waiting`, plus revision/source status. |
| `/v1/theme` | Latest full snapshot, 200 and ETag `"theme-REV"`; 503 if absent. |
| `/v1/events` | SSE named `theme` events, decimal revision as `id`, full snapshot as `data`. |
| `/v1/wallpaper/current` | Current allowlisted raster image only; optional `?id=sha256:…`. 404 unavailable, 409 changed. |

GET only. No CORS or mutation API. SSE sends the current snapshot on connection,
unless `Last-Event-ID` equals the current revision. Other/stale ids receive the
latest state; there is no history replay. Heartbeat every 15 seconds and
`retry: 2000`. Each client's queue holds one latest state; slow clients can skip
intermediate changes. Maximum 32 connections, 16 SSE subscribers, bounded
headers and read/write timeouts. Treat reconnect as snapshot reconciliation.

The daemon watches the directory chain with Linux inotify, including atomic
replacements, parent recreation and queue overflow. Debounce defaults to 250 ms.
Malformed/missing sources retain last valid state in memory and a private cache
across restart. Regressing/reused revisions and semantic-equivalent revision
bumps are rejected. Metadata-only rewrites do not emit an event.

## Configuration and authentication

Configuration: `$XDG_CONFIG_HOME/noctalia/theme-sync/bridge.json`, or `bridge
--config PATH`. Example safe config:

```json
{
  "bind": "127.0.0.1",
  "port": 8765,
  "trusted_loopback": true,
  "debounce_ms": 250,
  "wallpaper_roots": []
}
```

Numeric bind addresses only. Default is localhost. A random bearer token is
created in `$XDG_STATE_HOME/noctalia/theme-sync/bridge-token`, user-owned mode
0600; unsafe ownership/permissions/format prevent startup. Explicit `token_file`
may select another absolute file. Non-loopback always requires authentication,
even with `trusted_loopback: true`. Set that field false to protect loopback too.
The token is never logged; every route uses the same authorization policy.

Headers must contain `Authorization: Bearer TOKEN` when authentication is
required. Browser Origin requests are rejected and trusted-loopback Host is
checked to resist DNS rebinding. Query-string tokens are rejected. Remote access,
firewall rules and TLS termination are not configured. Plain bearer HTTP must
not be exposed over an untrusted network; use an explicitly configured encrypted
transport outside this project. Restart after token/config changes.

Wallpaper bytes are **opt-in**, unlike the source desktop's preconfigured roots.
Set `wallpaper_roots` to specific absolute directories you intend to expose.
Only the current canonical wallpaper is eligible: opened with `O_NOFOLLOW`,
regular file, inside an allowlisted root, at most 64 MiB, matching hash/type/size.
PNG/JPEG/WebP/GIF are recognized from magic bytes; SVG/HTML are rejected.
No arbitrary file-path endpoint exists. Snapshot metadata still includes the
wallpaper path; consider this when explicitly granting remote access.

## Operation

```sh
noctalia-theme-sync validate path/to/snapshot.json
noctalia-theme-sync bridge --config path/to/bridge.json --state path/to/state
curl --noproxy '*' http://127.0.0.1:8765/v1/theme
curl --noproxy '*' -N http://127.0.0.1:8765/v1/events
```

For a test instance, use a separate state/token/config and `port: 0` (ephemeral
loopback port). Do not start it over the desktop's existing bridge. No cloud,
telemetry, threads per client or recurring palette polling are introduced.

References: [inotify](https://man7.org/linux/man-pages/man7/inotify.7.html),
[SSE](https://html.spec.whatwg.org/multipage/server-sent-events.html).
