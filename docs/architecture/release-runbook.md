# Release runbook

Two paths produce the same release record: a local dry run and the CI tag flow.
Both end with `scripts/adaptation/release_gate.py`, which refuses to pass without
green evidence for the exact commit.

## Local dry run

```sh
./scripts/adaptation/release_dry_run.sh
```

The script uses the version in `apps/harmonyos/AppScope/app.json5`. It builds
store and self HAPs and an AppGallery Release `.app`, then validates their
shapes and sizes. The AppGallery check opens the HAP inside the `.app`.
Artifacts are copied to `.build/release-check/<version>/`. The record in
`docs/evidence/release/<version>-<commit>.json` includes each SHA-256 and the RSI
scoreboard hash. The record points to the report captured for that release in
`docs/evidence/release/rsi-<sha256>.md`. Refreshing the weekly scoreboard leaves
previous release snapshots available for verification. CI uploads the snapshots
with the release records.

The tag workflow runs the same script. The release gate requires green evidence
for the exact commit. AppGallery signing and submission use the steps in the
[AppGallery release guide](../appgallery-release.md).

## Build variants

- `store` is the regular HarmonyOS package. Its checks require the default
  build flags and prohibit the self-build loader, shim and overlay.
- `self` includes the self-build tools. `lab` uses the same source baseline and
  pins the overlay groups used in developer verification.
- `appgallery` is the native distribution package. Its HAP must contain the
  native image and search adapters and the AppGallery archive. Its package
  assertions rule out Alpine/PRoot and self-build tools.

G3 `exec` and `overlay` read the installed entry HAP's signed `selfBuild`
metadata. Self and lab packages run the original execution and overlay checks.
Store packages verify the packaged tools and the absence of self-build tools
and overlay fixtures. A missing or ambiguous flag is a setup failure.
G3 `verify` checks normal mode and authenticated HTTP 200 again after collecting
device diagnostics. A Host that becomes unhealthy after initial startup fails G3.

The emulator gates use separate application identities for the regular and
AppGallery builds. Select the actual AppGallery simulator using
`MH_APPGALLERY_EMULATOR` after installing its HAP and completing privacy consent.

```sh
python3 gates/run.py --tier G2 --only appgallery-images,appgallery-search
```

## Plugin recovery (bad plugin)

After a normal Host boot, the app saves the `web` profile (`cordis.patch.yml`,
`cordis.yml`, `package.json`, `pnpm-lock.yaml`) to `files/plugin-snapshot/`.
A plugin crash leaves the boot marker pending. The next launch opens the
recovery page ("运行时恢复") in safe mode and preserves the snapshot.

Select **回滚插件配置并正常重开** to restore the profile and restart in normal mode.
If the snapshot is unavailable, use safe mode to remove the plugin manually.
The recovery UI test requires an unlocked screen.
