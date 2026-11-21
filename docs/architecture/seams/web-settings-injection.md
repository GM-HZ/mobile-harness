# Seam: web settings client injection

- Upstream package: `@deepseek-ai/dsh-client-ui-settings-general` (`lib/client.js`), npm `0.2.2-rc.5`.
- Code: `scripts/build/stage-harmonyos.py` (`stage_settings_client`), `runtime/harmonyos/web/settings-recovery.js`.
- Anchor: `function apply(ctx){` must appear exactly once.
- Our assumption (migrated 2026-11-20): the settings client has a single `apply(ctx)` entry; the recovery row is now inserted by `patches/settings-client-recovery.patch` while assembling `dsh-layer.zip`. No stage-time rewrite and no DshEngine override remain.
- Failure mode: build aborts with "The pinned DSH General Settings entry point changed"; or recovery disappears silently if the injection point moves but the literal survives elsewhere.
- Replacement strategy: upstream settings extension point (plugin/slot) if exposed; otherwise `pnpm patch`.
- Gate: G0 (stage-time check), G1 (planned), G2 (recovery acceptance).
- History: 0.2.2-rc.5; previous RC bump changed this entry once.

### Migration (2026-11-20)

Converged to a package patch. Validation: layer contains
`registerMobileHarnessRecovery(ctx);`, `stage-harmonyos.py` has no write and
`DshEngine.ets` has no copy override, HAP contains no `dsh-settings-client.js`,
G1 `host-contracts` passes and G2 recovery passes on the patched build.
