# Seam: web settings client injection

- Upstream package: `@deepseek-ai/dsh-client-ui-settings-general` (`lib/client.js`), npm `0.2.2-rc.5`.
- Code: `scripts/build/stage-harmonyos.py` (`stage_settings_client`), `runtime/harmonyos/web/settings-recovery.js`.
- Anchor: `function apply(ctx){` must appear exactly once.
- Our assumption: the settings client has a single `apply(ctx)` entry we can prefix with `registerMobileHarnessRecovery(ctx)`, producing `dsh-settings-client.js` copied over the guest file.
- Failure mode: build aborts with "The pinned DSH General Settings entry point changed"; or recovery disappears silently if the injection point moves but the literal survives elsewhere.
- Replacement strategy: upstream settings extension point (plugin/slot) if exposed; otherwise `pnpm patch`.
- Gate: G0 (stage-time check), G1 (planned), G2 (recovery acceptance).
- History: 0.2.2-rc.5; previous RC bump changed this entry once.
