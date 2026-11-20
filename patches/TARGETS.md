# Patch targets

One row per patch in `patches/series.json`. Every patch is rehearsed with
`python3 scripts/adaptation/patch_rehearsal.py` (G1 `patch-rehearsal`) before a
build can use it.

| Patch | Package · file | Anchor / marker | Why | Failure mode | Gate |
| --- | --- | --- | --- | --- | --- |
| `session-persistence-eacces-fallback.patch` | `@deepseek-ai/dsh-session-persistence-jsonl` · `lib/index.js` | anchor `await link(tmp, finalPath);` → marker `globalThis.__dshClientRenameNoReplace(tmp, finalPath)` | HarmonyOS denies `link(2)` (EACCES) for the publish path; fall back to native `renameNoReplace` | session publish fails with errno 13; publish retry loops | G1 anchors/contracts, G2 recovery |
| `bash-local-shell-path.patch` | `@deepseek-ai/dsh-bash-local` · `lib/index.js` | `"bash"` → `"/bin/bash"` in the `-c` argv | guest shell is `/bin/bash`; keeps boot free of module rewriting | bash tool spawn fails (`ENOENT`) or falls back to a different shell | G1 anchors/contracts, G2 exec/recovery |
| `bash-sandbox-shell-path.patch` | `@deepseek-ai/dsh-bash-sandbox` · `lib/index.js` | `"bash"` → `"/bin/bash"` in the `-c` argv | same as above for the confined path | sandboxed bash commands fail to spawn | G1 anchors/contracts, G2 capabilities |
| `settings-client-recovery.patch` | `@deepseek-ai/dsh-client-ui-settings-general` · `lib/client.js` | inserts the recovery row before `function apply(ctx){`; marker `registerMobileHarnessRecovery(ctx);` | phone recovery entry in General Settings without stage-time file rewriting | settings page loses the recovery row or fails to register (module error on settings open) | G1 host-contracts, G2 recovery |

Each row corresponds to a section in `docs/architecture/seams/` or a compat
decision; if upstream changes the anchor, `scripts/adaptation/bump.py` and the
G1 gates fail before a build is attempted.
