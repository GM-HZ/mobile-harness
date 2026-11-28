# Seam: web settings client injection

- Upstream package: `@deepseek-ai/dsh-client-ui-settings-general` (`lib/client.js`), npm `0.2.2-rc.5`.
- Code: `patches/settings-client-recovery.patch`, `runtime/harmonyos/web/settings-recovery.js`, and `apps/harmonyos/entry/src/main/ets/pages/Index.ets`.
- Anchor: `function apply(ctx){` must appear exactly once.
- The package patch registers the recovery and copyright rows through the `settings.general.item` slot. AppGallery adds its privacy row through its variant overlay. The native app opens the copyright page for either variant and displays the licensed texts from raw resources.
- Failure mode: the module fails to load or a row is missing or registered twice. The host contract asserts that the bundled copyright row has one registration and one navigation target.
- Replacement strategy: upstream settings extension point (plugin/slot) if exposed; otherwise `pnpm patch`.
- Gate: G1 (upstream anchors and host contracts), G2 (recovery acceptance), G4 (packaged license resources).
- History: 0.2.2-rc.5; previous RC bump changed this entry once.

### Migration (2026-11-20)

Converged to a package patch. Validation: layer contains
`registerMobileHarnessRecovery(ctx);`, `stage-harmonyos.py` has no write and
`DshEngine.ets` has no copy override, HAP contains no `dsh-settings-client.js`,
G1 `host-contracts` passes and G2 recovery passes on the patched build.
