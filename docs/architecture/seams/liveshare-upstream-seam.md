# Seam: liveshare upstream bundle vs our liveshare compat

Status: **keep-compat** (no usable upstream injection point as of 0.2.2-rc.5).

## Upstream structure

- `@deepseek-ai/dsh-experimental-liveshare` — host plugin (`liveshare-share-host`)
  plus client bundle (`dsh.bundle.patch`, `dsh.client.inject`), a `cordis.patch.yml`,
  and a `./client` entry.
- Config surface (`share-host.Config`) is limited to identity/state files:
  `allowedSubjectIds`, `ownerIdentity*`, `ownerStateFile`, `ownerCredentialFile`.
  The Relay address lives in owner state, not config.
- The owner gateway worker is spawned internally:
  `gatewayWorkerCommand(import.meta.url)` → `new TunnelWorker({ command: tunnelCommand() })`,
  and `TunnelWorker` calls `spawn(this.options.command.executable, [...args], ...)` from
  `node:child_process`. There is **no configurable worker/spawn factory**.
- `@deepseek-ai/dsh-experimental-liveshare-protocol` is the wire/identity contract
  (usable as-is).

## Our current adaptation

`packages/dsh-host/dsh-native-web.cjs` rewrites the upstream module at load time:

1. `import { spawn } from "node:child_process";` → `const spawn = globalThis.__harmonyLiveshareSpawn;`
   so the gateway CLI runs in an isolated Node **Worker thread**
   (`createTunnelLauncher(entry, mark)` in `runtime/harmonyos/compat/dsh-harmony-liveshare.cjs`);
2. viewer-upload support injected around `withoutManifestLink(read)`;
3. `patchLivesharePolicies` adjusts the sharing policy for the phone runtime.

Plus `patchFileUploads` / `patchFileUploadSchemas` patch the client upload modules.

## Why we keep compat

- The spawn replacement needs an **injection point that upstream does not expose**;
  introducing one ourselves would mean patching a large, security-sensitive module
  and duplicating child-process IPC semantics — worse than the current adapters.
- The upload/policy patches are client-side behavioral additions tied to mobile
  sharing; there is no provider seam for them today either.
- G2 covers the behavior: `emulator-liveshare-relay`, `emulator-liveshare-browser`,
  `emulator-auto-review-liveshare`.

## Options / next steps

- **Now:** keep-compat; treat the three rewrites as compat-layer inventory entries
  (already in `adaptation/compat.json`).
- **If upstream adds a seam** (`spawn`/worker factory in `Config`, or a provider
  contract for sharing policy), migrate the spawn rewrite first — it is the only
  part that must run inside the host process at that exact point.
- **Optional low-risk convergence:** move the two upload patches into a package
  patch of the client upload modules (same pattern as the settings client), leaving
  only the spawn rewrite as runtime code.

## Risks

- Gateway Worker thread must preserve child-process IPC semantics (`send`, `on("message")`,
  `kill`, `connected`); any upstream change to `TunnelWorker` breaks it silently.
- Relay/WebRTC acceptance depends on fixtures and a second emulator; the G2 relay
  cases stay the guard.
