# AI-assisted installation

Give an agent access to your local terminal and the checked-out repository. Paste:

> Install noctalia-theme-sync from this repository for my already working Noctalia
> v5 desktop. Read AGENTS.md and docs/INSTALL.md first. Identify my distro, Noctalia/
> Python versions, XDG paths and installed supported apps. Run doctor/list, show a
> concrete plan and dry-run for the apps I specify; if I have not named apps, ask
> which I want before changing their config. Use guarded CLI installation with
> private backups. Preserve my current compositor, NixOS configuration, accounts,
> Firefox profiles, Telegram tdata and wallpapers. Resolve conflicts without force
> overwrites or breaking symlinks. Do not enable experimental adapters or a bridge
> without my request. Apply the current Noctalia templates and verify generated
> files plus the selected apps' native activation/reload. Report what actually
> passed, any manual GUI activation, and the exact uninstall/rollback command.
> Do not publish my configuration or test artifacts.

Agent behavior is defined in [AGENTS.md](../AGENTS.md). Installation is local;
GitHub publication, system rebuilds and wallpaper cycling are separate actions.

For Fastfetch/Codex, include this in the request: "Select fastfetch and codex
independently, use --experimental for codex, locate the native Codex executable
without running sudo/VPN/pet wrappers, preserve layout/modules and all unrelated
Codex settings/pet assets, and explain Fastfetch next-invocation and Codex restart.
Review adapter_states and perform native checks without treating file hashes as
visual evidence."
