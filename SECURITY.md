# Security

The default bridge listens on localhost. Non-loopback requires bearer authentication;
no remote bind, firewall rule, cloud service or telemetry is installed automatically.
Wallpaper bytes are disabled by default. Canonical JSON may contain a local wallpaper
path: treat remote sharing as an explicit privacy decision.

Installation rejects symlinks, hardlinks, unmanaged outputs and changed managed
files. Backups/journals are private user state, never public diagnostic attachments.
Keep dependency/Noctalia updates current and scan every public commit.

For a suspected vulnerability use GitHub's private vulnerability reporting if
available on the repository. Do not post secrets, exploitable account data or raw
backups in a public issue. Public reports should be sanitized and reproducible in
an isolated HOME. This initial release has local tests, not an independent external
security assessment.
