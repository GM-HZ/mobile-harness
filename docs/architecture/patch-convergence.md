# Patch convergence

We currently adapt upstream at several layers. The goal is to move every
fragile runtime patch toward an upstream-supported seam (plugin/bundle/profile),
then `pnpm patch`, and keep string replacement only where nothing better exists.

The ranked inventory lives in [`adaptation/convergence.json`](../../adaptation/convergence.json);
it is checked into the repo so a bump rehearsal can report which surfaces are
still "keep-with-gate" versus "converged".

## Decision rules

1. If upstream exposes a plugin/bundle/slot/provider (deepseek-harness is
   all-plugin by design), mount an extension instead of patching.
2. If the change is a small fix inside a third-party npm package, express it as
   a `pnpm patch` file under `patches/` and keep the runtime hook out of boot.
3. If the change must run before modules load (bash spawn, storage link,
   settings entry), keep the runtime hook, but it must have:
   - an anchor entry in `adaptation/anchors.json`,
   - a seam contract in `docs/architecture/seams/`,
   - a G1 host contract test,
   - an entry in `adaptation/convergence.json` with a migration target.
4. Migration order: P1 anchors first (highest download/upstream-bump risk),
   then P2 compat modules, then platform-specific bindings.

## Migration checklist

- [ ] add `patches/<pkg>@<version>.patch` (or extension seam) and verify with `pnpm install --frozen-lockfile`
- [ ] remove the runtime replacement from `dsh-client.cjs`
- [ ] update manifest/convergence status to `converged`
- [ ] add or update the G1 contract that proves the new path
- [ ] run G0/G1/G2 and a bump rehearsal (`scripts/adaptation/bump.py`)
