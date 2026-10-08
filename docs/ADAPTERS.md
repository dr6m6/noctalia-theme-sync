# Application adapters

All selections are independent; installing one does not install other applications.
Supported adapters reuse established local integrations and/or Noctalia's MIT
native templates. Experimental projections are deliberately narrower than the
source desktop's bespoke configuration. “Auto” reload below means a supported
native notification; it still needs the app-side activation/dependencies.

| ID | Status | Dependencies | Reload | Known limitations |
| --- | --- | --- | --- | --- |
| `gtk` | Supported | GTK3: adw-gtk3; GTK4/libadwaita | Restart; toolkit-dependent live updates | Imports color definitions and sets GTK theme/mode in settings.ini. No portal round trip, GTK module or CSS injection. Apps can override colors. |
| `qt` | Supported | qt5ct or qt6ct | Restart; `--reload` touches qtct directory | Set `QT_QPA_PLATFORMTHEME=qt5ct`/`qt6ct` appropriately in your session. KDE's separate color-scheme system is not managed. |
| `kitty` | Supported | Kitty, canonical terminal tokens | Ctrl+Shift+F5 or `apply --reload` | Owned processes only; existing options later in config can override includes. |
| `firefox` | Supported | Pywalfox extension, Noctalia native host | Automatic on `sync`; explicit `apply --reload` | Shared `$XDG_CACHE_HOME/wal/colors.json` can conflict with other palette tools. No profiles, CSS or signed extensions are patched. |
| `vesktop` | Experimental | Vencord local themes | Local theme file watcher | Independently authored minimal native CSS variables. No Material Discord base is bundled. Discord updates can change token coverage. |
| `neovim` | Supported | Neovim | `:colorscheme noctalia` | Color file generated; init files never edited. No RPC socket discovery or automatic session restart. |
| `tmux` | Supported | tmux, config that sources XDG tmux.conf | Automatic on `sync`; explicit reload | Default server only; custom sockets require manual source-file. No scanning all sessions or arbitrary sockets. |
| `btop` | Supported | btop | Restart/reselect | Existing btop sessions may retain cached themes. |
| `cava` | Supported | cava supporting native themes | `apply --reload` sends SIGUSR1, or restart | Native `[color] theme` selection; older distro versions may need manual upgrade. |
| `telegram` | Experimental | Telegram Desktop | Next normal start after native import | Compact 13-role projection, not the source's full 272-role community-derived theme. No watcher/API guarantee. No tdata access. |
| `steam` | Experimental | Millennium + compatible installed Material-Theme | Manual import; upstream dependent | Writes an additional CSS file only. Does not activate, download or modify Steam/Millennium. Store/CSP coverage is not guaranteed. |
| `affine` | Unavailable | Supported production palette API absent | Native System mode only | No palette adapter, flag override, remote debugging or ASAR modification. |
| `icons` | Unavailable | Licensed artwork and distribution integration needed | — | Source artwork/SVG tooling excluded from initial release pending a separately scoped redistributable pack. |

## Activation

- **GTK:** install adw-gtk3 first through your system's package manager. Generated
  GTK4 definitions also apply to applications that load user GTK CSS. Their live
  reload behavior is not uniform.
- **Qt:** configure the correct platform theme for your Qt version before launching
  applications. The CLI updates native qtct appearance and palette paths only.
- **Firefox:** install the Pywalfox browser extension and run
  `noctalia firefox-theme install` yourself (this external command can modify native
  host manifests). The project does not install extensions or change browser
  security preferences. Colors remain in the shared standard wal file.
- **Neovim:** `:colorscheme noctalia` selects it. Add
  `vim.cmd.colorscheme("noctalia")` to your existing Lua init only if desired.
- **tmux:** the installer appends a marked source directive to XDG `tmux/tmux.conf`.
  If your existing `~/.tmux.conf` overrides startup lookup, explicitly source the
  XDG config there yourself. It is never overwritten by the project.
- **Vesktop:** enable `noctalia-theme-sync.theme.css` in Vencord's local themes UI.
  No remote stylesheet imports or debug ports are involved.
- **Telegram:** open the generated `.tdesktop-theme` file through Telegram's
  supported GUI and select it. This is a plain native text theme; user wallpapers
  and backgrounds remain app-owned. Do not edit account storage with external tools.
- **Steam:** after installing a compatible Material-Theme separately, explicitly
  import `css/main/colors/noctalia-theme-sync.css` from your native user customization
  CSS. The project does not guess theme versions or patch existing vendor files.

## Validation scope

The extracted GTK/Qt/Kitty/btop/cava templates are exact files from Noctalia 5.2.1
at the commit in `licenses/provenance.json`. Neovim/tmux derive from the working
local implementation. Firefox uses a small native-host schema projection. CI
checks four synthetic palettes, complete token substitution, installation,
permissions and rollback. The real-desktop smoke checks Noctalia rendering,
source palette changes and extracted output parity in an isolated HOME.
It does not certify every application version or claim pixel-level CI coverage.

## Adding an adapter

Add `<id>.json` to `src/noctalia_theme_sync/assets/adapters/` with a unique `id`,
`status`, `commands`, `detect`, `dependencies`, `reload`, `limitations` and `outputs`.
Each output names a local template and an XDG-relative path, for example
`config/example/themes/noctalia.conf`. Add a template using only
`{{ colors.primary.default.hex }}`-style tokens and `{{ mode }}`. Add attribution
before copying third-party code. A manual native activation is acceptable and
should be documented; start as experimental until generation, install and actual
application behavior have been verified. Never add a downloader or shell evaluator
to the data-driven renderer.
