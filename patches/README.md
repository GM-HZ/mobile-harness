# Upstream patches

Small, deterministic patches applied to pinned npm packages while assembling
`dsh-layer.zip` (`scripts/build/harmonyos_dsh.py`). This is the preferred
replacement for runtime string surgery where a package-level fix is enough.

`patches/series.json` declares each patch in application order:

```json
{"file": "name.patch", "package": "@deepseek-ai/<pkg>", "path": "lib/index.js",
 "marker": "text that must appear after the patch is applied", "reason": "..."}
```

Patch paths are relative to the package's `node_modules` tree (`-p1`). Every
patch must be rehearsed with `python3 scripts/adaptation/patch_rehearsal.py`
(see G1 `patch-rehearsal`) and covered by a seam contract or G1 host contract.

## Applied patches

- `session-persistence-eacces-fallback.patch` — HarmonyOS denies `link(2)` for the
  publish path; fall back to the native `renameNoReplace` helper (converged: no
  boot-time replacement remains).
