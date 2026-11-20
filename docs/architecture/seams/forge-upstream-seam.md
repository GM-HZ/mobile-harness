# Seam: forge upstream provider (GitHub) vs our forge compat

Status: **migration A implemented (2026-11-20)** — guest runner injected by
`patches/forge-github-guest-runner.patch`, the load-time `import { execa }`
rewrite is gone. Validated by a real build (layer marker), G1 `host-contracts`
and G2 `nightly-recovery`; full forge flows still need a clean GitHub account
fixture on the emulator (`emulator-forge-account`/`-github`).

## Upstream structure (0.2.2-rc.5)

- `@deepseek-ai/dsh-experimental-forge` — provider-neutral change-request registry
  (`ctx.forge`, at most one provider per forge family, shared polling).
- `@deepseek-ai/dsh-experimental-forge-github` — `GitHubProvider implements
  ForgeProvider`; the plugin registers it with
  `ctx.forge.register(new GitHubProvider(ghRunner(resolved), resolved.hosts, resolved))`.
- `@deepseek-ai/dsh-experimental-forge-bundle` — `cordis.patch.yml` inserts
  worktree/tool-worktree/forge/forge-github/forge-session/forge-panel.
- `GhRunner` contract: `(args: readonly string[], signal: AbortSignal, input?: string)
  => Promise<{exitCode, stdout, stderr}>`; the built-in `ghRunner(config)` spawns
  host `gh` through `execa` with scrubbed env, timeout and maxBuffer, mapping
  failures to `GhUnavailableError` / `GhTimeoutError` / `GhOutputLimitError`.

## Our current adaptation

`packages/dsh-host/dsh-native-web.cjs` rewrites the upstream module source at load
time:

```js
if (url === forgeGithubUrl) {
  return { ...result, source: replacePinned(source,
    'import { execa } from "execa";',
    'const execa = globalThis.__harmonyGh;') };
}
```

`globalThis.__harmonyGh` is our `createGhRunner(launchGuest, quoteShellArgument)`
from `runtime/harmonyos/compat/dsh-harmony-forge.cjs` — it runs `gh` **inside the
guest** through the proot launch path, because the Host Node cannot execute the
Alpine `gh` binary directly. `startForgeAccountBridge` wires the App-side account.

This is a runtime source rewrite (fragile, invisible to patch review), even though
the rest of the boot path is already patch-based.

## Migration options

**A. Package patch of `forge-github` (recommended first).**
`execa` **is present** in the assembled DSH layer, so the import can stay. Replace
the registration line with an injected guest runner:

```js
ctx.forge.register(new GitHubProvider(
  globalThis.__harmonyGhRunner ?? ghRunner(resolved), resolved.hosts, resolved));
```

- Add a proper `GhRunner` adapter in `dsh-native-web.cjs` (`__harmonyGhRunner`)
  that maps our guest-runner result (`isCanceled/timedOut/isMaxBuffer/exitCode/
  stdout/stderr`) to `GhOutput` and the three upstream error classes.
- Add `patches/forge-github-guest-runner.patch` to `patches/series.json`, rehearse
  it (`patch_rehearsal`), and remove the load-time rewrite branch.
- Keep the provider, session integration and client UI from upstream; only the
  transport (gh execution) stays ours.

**B. Custom Cordis plugin mounting `GitHubProvider` (later, cleaner).**
Requires exporting the class (not part of the public `index.d.ts` surface today:
the package exports only `apply`/`Config`/`name`/`inject`), a local bundle row and
disabling the upstream `forge-github` row for the mobile profile. Keep as a follow-up
if A proves stable.

## Risks / open questions

- Forge bundle also inserts worktree/tool-worktree/forge-session widgets; those are
  upstream and untested on HarmonyOS (G2 `emulator-forge-*` covers account/GitHub
  flows when credentials/fixtures exist).
- Account bridge (App ↔ guest gh credential store) remains; A only removes the
  module rewrite, not the guest gh transport.
- Adapter must preserve cancellation semantics: upstream throws `signal.reason` on
  cancel; our guest runner returns `isCanceled`.
- Tests: `emulator-forge-account`, `emulator-forge-github`; at minimum a build +
  Host boot + forge panel load gate after the patch lands.
