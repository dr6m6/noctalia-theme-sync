# Optional Noctalia v4 → v5 notes

This is a v5 integration project, **not an automatic shell migrator**.
The original migration included personal desktop/app cleanup, NixOS hardware and
session changes, recorder setup, backups and rice operations. They remain in the
original local workspace; none are public core dependencies.

Reusable lessons from that work:

1. Preserve a private backup before a shell migration. Do not publish shell caches,
   notifications, profiles, wallpaper paths or old account configuration.
2. Confirm the running executable with `noctalia --version`. v5 uses the native
   `noctalia` command, TOML configuration and `noctalia msg` IPC. Legacy v4 JSON/
   Quickshell configuration is not a drop-in v5 configuration.
3. Configure templates through `[theme.templates.user.ID]`. Use XDG tokens in
   paths, explicit `index` and `hook_async = false` for dependent/serialized hooks.
4. Validate templates using v5's own `noctalia theme` renderer and apply them with
   `noctalia msg templates-apply`. Matugen Tera control blocks and v5 `<* *>`
   control blocks are not interchangeable.
5. Separate general color adapters from compositor/session, system package and
   account operations. Retain Noctalia as the palette authority.
6. Validate dark/light modes, repeat application, normal app reload/startup and
   rollback before replacing a working pipeline. A native theme file alone does
   not prove live reload.

Read the current [v5 template reference](https://docs.noctalia.dev/noctalia/theming/templates/)
and [legacy v4 docs](https://docs.noctalia.dev/noctalia-shell-legacy/theming/user-templates/)
for version-specific configuration. Migrate your shell with its upstream guidance
first, then install this project. No v4 dependencies or personal automatic
migration/rollback scripts are shipped here.
