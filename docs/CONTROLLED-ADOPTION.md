# Controlled adoption

An existing desktop can contain custom templates, hooks, native theme selections,
wrappers and runtime patches that these adapters do not reproduce. File generation
tests do not establish visual or live reload parity. Preserve those integrations
until their specific replacement has passed a separate acceptance check.

The CLI reports existing Noctalia publishers and hooks. It rejects known native
and personal writers for selected adapters, including legacy templates whose
output filenames differ from the public adapter. Unknown third-party writers and
opaque scripts still require an independent inventory. This is conservative
detection, not proof that every external process has been discovered.

Keep the existing compatible canonical publisher and bridge. Use
`--consume-existing` to avoid adding a publisher hook; do not select `--bridge`
when another bridge is active. Consuming requires a valid existing snapshot.
Keep disabled personal templates/scripts as rollback assets rather than deleting
them. Do not disable a writer until its replacement and rollback are reviewed.
The CLI never removes personal writers or changes their hook configuration.

For an explicitly approved, compatible output, prepare a private plan:

```sh
noctalia-theme-sync plan --adapters neovim --consume-existing --adopt-existing \
  --write-plan /absolute/private/reviewed-plan.json
noctalia-theme-sync install --adapters neovim --consume-existing --adopt-existing \
  --from-plan /absolute/private/reviewed-plan.json --dry-run
# Run only after the desktop owner approves this exact change:
noctalia-theme-sync install --adapters neovim --consume-existing --adopt-existing \
  --from-plan /absolute/private/reviewed-plan.json
```

`--adopt-existing` now requires `--from-plan` for a real installation. It does not
bypass writer conflicts or user modifications. Plans include target ownership,
before/after checksums, modes, native target roots and runtime bytes. They bind
Noctalia TOML inputs, the installation manifest, pending transaction and canonical
snapshot. Changes to these inputs, selected targets or permissions refuse the
installation. Canonical updates invalidate a plan even when only its revision
changed: inspect again and create a fresh plan. A new plan file never overwrites
an old one; files created by `--write-plan` have mode 0600. They contain local paths
and hook strings, so keep them outside public Git history.

The plan is checked again under the installation lock and its input preconditions
are checked immediately before the transaction. Each target is checked again
before replacement. These checks narrow races; they do not lock unrelated apps
or promise a global filesystem snapshot. An independent external checksum guard
must cover personal scripts and dependencies outside this CLI's read set when
preparing a desktop cutover. Reviewed plans are not cryptographically signed:
protect their directory and treat the file as a local approval artifact.

Install/update/apply use the existing private transaction journal and original
backups. `rollback` restores adopted originals and modes and refuses managed file
drift. After a crash use `rollback --recover`; recovery preserves external edits.
Personal fragment edits are outside the CLI transaction and need their own
independent backup/rollback and guarded activation ordering.

Consume mode adds no persistent consumer service. After approval, use an existing
publisher's callback to invoke `apply`, or use a separately reviewed `watch`
consumer. Both consume the same export; neither generates a new palette or needs
another HTTP bridge. Verify app activation separately. Never use overwrite flags,
delete a manifest, or substitute a simpler theme merely to make a plan pass.
