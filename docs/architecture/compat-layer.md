# HarmonyOS compatibility layer

`runtime/harmonyos/compat/*` contains our implementations of upstream DSH
capabilities that cannot run unchanged on a phone (no native fetch shim, no
libnode, no desktop carriers, device audio/office paths). These are **feature
adapters**, not rewrites of upstream source: they are loaded by our own host
wiring (`packages/dsh-host/dsh-native-web.cjs`, subprocess env) or executed as
guest workers.

Rules:

1. Every module has a row in `adaptation/compat.json` (consumer, upstream
   capability, gate ids, decision, priority) and a section in this document.
2. `scripts/adaptation/compat_check.py` (G1 `compat-inventory`) enforces the
   inventory: no undocumented module, no dangling consumer, no unknown gate id.
3. Decision values: `keep-compat` (no upstream seam exists), `upstream-seam-candidate`
   (watch the upstream provider/bundle), `migrate-patch` (should become
   `patches/`), `converged`.
4. Migrate only when an upstream seam actually exists; otherwise keep the compat
   layer and let the gate suite guard behavior.
5. Behavior contracts: `scripts/adaptation/compat_contracts.py` (G1
   `compat-contracts`) asserts the public behavior of forge (command guard/abort),
   package (registry provenance round-trip), liveshare and sharp export surfaces;
   device-only modules stay covered by their G2/G3 feature gates.

## Modules

### dsh-boot-cache.cjs

Startup module-source cache used by `dsh-client.cjs` (`installBootCache`).
Decision: keep-compat. Gate: `capability-parity-gate`.

### fetch-shim-boot.cjs

Preloads the dshm `fetch-shim.cjs` for guest Node processes and pnpm.
Decision: keep-compat. Gates: `capability-parity-gate`, `emulator-liveshare-relay`.

### dsh-harmony-forge.cjs

Forge/GitHub runner account bridge used by the host web server. Decision:
upstream-seam-candidate (follows the upstream experimental forge bundle surface).
Gates: `emulator-forge-account`, `emulator-forge-github`.

### dsh-harmony-inspector-worker.cjs

Exposes Node internals for the inspector/debug path. Decision: keep-compat.
Gates: `emulator-inspector`, `emulator-inspector-availability`.

### dsh-harmony-liveshare.cjs

LiveShare relay/WebRTC transport adapter for the experimental LiveShare bundle.
Decision: upstream-seam-candidate. Gates: `emulator-liveshare-relay`,
`emulator-liveshare-browser`.

### dsh-harmony-package.cjs

Package-manager (pnpm) bridge used by the plugin market/install path. Decision:
keep-compat. Gates: `emulator-plugin-market`, `emulator-plugin-public-graph`.

### dsh-harmony-pnpm-fetch.cjs

Two-line preload that installs the fetch shim before pnpm runs. Decision:
keep-compat (covered by pnpm install tests). Gates: `emulator-plugin-market`,
`emulator-plugin-git-update`.

### dsh-harmony-sharp.cjs

Image-processing (`sharp`) adapter for attachments/images. Decision:
upstream-seam-candidate. Gates: `emulator-toolkit`, `capability-parity-gate`.

### dsh-harmony-speech.cjs

Voice-input / speech launcher for the device audio path. Decision: keep-compat.
Gate: `emulator-voice-input`.

### dsh-harmony-office-worker.mjs

Office document conversion worker (paired with `packages/dsh-host/dsh-harmony-office*`).
Decision: keep-compat. Gates: `emulator-office`, `emulator-office-provider`,
`emulator-office-cancel`.

## Upstream seam watch

`scripts/adaptation/seam_watch.py` fetches the pinned release of the packages
behind each compat area and reports provider/plugin seam signals; evidence lands
in `docs/evidence/upstream-seams/<version>.json` and is attached to the matching
`adaptation/compat.json` rows (`seamEvidence`).

Latest watch (0.2.2-rc.5): forge (provider seams in `dsh-experimental-forge*`),
liveshare (`dsh-experimental-liveshare{,-protocol}`), speech
(`dsh-experimental-speech-to-text-sensevoice`) show real provider seams and remain
`upstream-seam-candidate`; office-kit is already the upstream provider (our worker
only adapts the phone runtime); image/sharp has only a weak seam upstream.
