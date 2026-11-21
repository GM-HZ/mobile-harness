# Seam: host bash / session-persistence runtime hooks

- Upstream packages (npm `0.2.2-rc.5`, pinned by `runtime/harmonyos/dsh/package-lock.json`):
  - `@deepseek-ai/dsh-bash-local` (`lib/index.js`)
  - `@deepseek-ai/dsh-bash-sandbox` (`lib/index.js`)
  - `@deepseek-ai/dsh-session-persistence-jsonl` (`lib/index.js`)
- Code: `packages/dsh-host/dsh-client.cjs` (`registerHooks`, `replacePinned`), `packages/dsh-host/dsh-native-web.cjs`
- Anchors:
  - `await link(tmp, finalPath);` — exactly once in the session-persistence module;
  - `"bash",\n\t\t\t"-c",` — exactly once in each bash module; replaced with the guest bash path literal.
  - native bash launcher expects `args.length === 2 && args[0] === '-c'` (one non-interactive command).
- Our assumption: bash modules receive a `-c` command, cwd `/workspace`, inherited environment; session persistence exposes a `link(tmp, finalPath)` step we replace with a copy for HarmonyOS.
- Failure mode: `replacePinned` throws `Unexpected pinned DSH implementation: <url>` at Host boot; or the hook silently stops applying after an upstream refactor.
- Replacement strategy: move to a Cordis/bundle extension seam (upstream "no privileged core") or a `pnpm patch` of the npm packages; keep runtime string replacement as a last resort.
- Gate: G1 anchor snapshot (planned), G2 capability gate (`bash`, exec probes), upstream bump rehearsal (`scripts/adaptation/verify.py`).
- History: 0.2.2-rc.5 pinned 2026-11.

### Session-persistence migration (2026-11-20)

The `await link(tmp, finalPath);` surface is now a package patch
(`patches/session-persistence-eacces-fallback.patch`) applied by
`scripts/build/harmonyos_dsh.py`; the boot hook no longer rewrites it. The
contract is: patched module contains the native fallback, `dsh-client.cjs`
defines `globalThis.__dshClientRenameNoReplace`, and no boot-time replacement
targets this file. Validated by a real patched build + G2 recovery.

### Bash command migration (2026-11-20)

`dsh-bash-local` and `dsh-bash-sandbox` now ship patched argv literals
(`"/bin/bash"`), applied by `harmonyos_dsh.py` from `patches/series.json`; the
`replacePinned` boot hook and the `registerHooks` source rewrite were removed.
Contract: both modules contain the patched literal and `dsh-client.cjs` contains
no replacement for the old anchor. Validated by a real patched build + G2.
