# Contributing

Keep Noctalia as the only palette source. Prefer small native-format adapters over
frameworks, remote assets or application patches. Read AGENTS.md and
[development instructions](docs/DEVELOPMENT.md).

For an adapter contribution include its license/provenance, dependencies, supported
app versions, native activation, reload behavior and limitations. Start experimental
until real application behavior is checked. Tests must cover dark/light and at least
two palettes, isolation, idempotence, conflicts and rollback. Preserve existing
configuration bytes and permission modes.

Do not submit rendered desktop state, wallpaper metadata, screenshots containing
private content, profiles, account storage, backups or credentials. Run privacy
and history scanning before opening a PR. A clean secret scan is not permission
to redistribute code with unknown licensing. Include required attribution.

Report bugs with OS/app/Noctalia/Python versions, selected adapters, the failing
command and sanitized error. Do not paste raw manifests, tokens or account paths.
CI verifies files, protocol and lifecycle; visual claims need explicit real-app
verification. Describe the concrete before/after behavior and tests in your PR.
