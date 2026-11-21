# Release runbook

Two paths produce the same release record: a local dry run and the CI tag flow.
Both end with `scripts/adaptation/release_gate.py`, which refuses to pass without
green evidence for the exact commit.

## Local dry run

```sh
./scripts/adaptation/release_dry_run.sh 0.4.69
```

This builds the store variant, builds the self variant, runs
`release_evidence.py` (hashes/sizes + store shape + variant assertions) and then
`release_gate.py`. Evidence lands in
`docs/evidence/release/<version>-<commit>.json`.

## CI tag flow (`gate-release.yml`)

Triggered by a `v*` tag (or manual dispatch) on the self-hosted macOS/DevEco lab:

1. G0 + G1 gates;
2. build store → `store_build_check.py` + `variant_check --variant store`;
3. build self → `variant_check --variant self` + `release_evidence.py`;
4. `release_gate.py` (fails if evidence is missing or red);
5. upload `gate-evidence-release` artifact.

## Requirements

- store HAP: no `mh-exec`/`mh-install`, no exec shim, no overlay libraries,
  `signedExecBypass=false`; size within `variants/store.json` maxBytes.
- self HAP: contains the loader tools/shim/overlay and
  `signedExecBypass=true`; size within `variants/self.json` maxBytes.
- evidence for the tagged commit exists under `docs/evidence/release/`;
- the evidence embeds the current RSI scoreboard hash
  (`docs/evidence/rsi/scoreboard.md`) and the release gate fails if it drifted.

## Rollback / checks

- The store artifact is the distributable; self builds stay lab-only.
- If `release_gate.py` fails, do not tag: rebuild, re-run `release_dry_run.sh`,
  then inspect `docs/evidence/gates/**` and the RSI ledger
  (`python3 scripts/adaptation/rsi_ledger.py report`).


## Plugin recovery (bad plugin)

The App keeps a **last-known-good plugin snapshot** of the `web` profile
(`cordis.patch.yml`, `cordis.yml`, `package.json`, `pnpm-lock.yaml`) after every
successful Host boot (`files/plugin-snapshot/`). A plugin that crashes the Host
leaves the boot marker pending; the next launch enters safe mode. From the
recovery page ("运行时恢复"), use **回滚插件配置并正常重开** to restore the
snapshot (rolling the plugin set back to the last successful boot) and restart
in normal mode. If no snapshot exists the action reports an error; use safe mode
and remove the plugin manually.

Preconditions: the snapshot is written only by the native Host boot path; a
failed boot never overwrites it. E2E UI test requires an unlocked screen.
