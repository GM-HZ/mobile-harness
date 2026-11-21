# Architecture & gate system — delivery summary (2026-11-20)

Branch: `codex/harmonyos-architecture` (from `main` `8d3f22e`).
Scope: make the mobile-harness adaptation layer and gate system iterable against
upstream DeepSeek Harness, per the round-19 plan.

## 1. Objective vs delivered

| Objective | Delivered | Where |
| --- | --- | --- |
| Single adaptation inventory | 73 entries across host/web/compat/native/packaging/tools/bundles/variants/patches/app + 5 variant switches; 12 high-fragility surfaces flagged; hashes enforced | `adaptation/manifest.json`, `scripts/adaptation/inventory.py` |
| Upstream pin lock | DSH release + npm lock hash + submodule gitlinks + build inputs + guest-tools lock | `versions.lock.json` |
| Anchor / patch verification | 7 anchors (literal/patch markers), 5 package patches with rehearsal, TARGETS table + machine index | `adaptation/anchors.json`, `scripts/adaptation/{anchors,patch_rehearsal,patch_targets}.py`, `patches/` |
| Upstream bump rehearsal | dry-run fetch of pinned release, anchor/package checks, affected entries report | `scripts/adaptation/bump.py`, `docs/evidence/upstream-bump/` |
| G0 static/consistency | manifest/pins/submodules + patch targets + compat inventory/contracts | `gates/run.py --tier G0`, PR workflow |
| G1 host contracts | host syntax, upstream anchors, settings/session/forge behavior contracts, patch rehearsal | `gates/run.py --tier G1`, PR workflow |
| G2 emulator capability | consolidated capability gate + 8-item model-free nightly matrix (recovery/native-addon/inspector/availability/lsp-bundle/mcp-stdio/ptc-link) | `gate-nightly.yml`, validated 7/7 PASS repeatedly |
| G3 real-device lab | `device_lab.py` protocol: USB detect, screen-lock detection, flock, wait-unlock, suites verify/exec/overlay, evidence; manual `gate-device.yml` | protocol validated (locked device exits 4); **successful device run pending** (phone stayed locked) |
| G4 build/release | store/self/lab variants, shape+size assertions, release evidence with RSI scoreboard hash, release gate for tags, local dry run | `variants/`, `release_evidence.py`, `release_gate.py`, `release-dry-run.sh`, `gate-release.yml` |
| Evidence / RSI loop | per-commit gate evidence, RSI ledger with first/flake/fail buckets, weekly scoreboard, release evidence | `docs/evidence/gates|release|rsi|upstream-*`, `rsi_ledger.py`, `gate_report.py` |
| Patch convergence | session-persistence, bash-local/sandbox, settings-client converged to package patches; forge migrated to upstream provider seam; liveshare/speech seam studies conclude keep-compat | `docs/architecture/seams/`, `adaptation/convergence.json` |
| Reference alignment | deepseek-harness all-plugin/patches/CI patterns; dsh-Go patch series/TARGETS/maintenance contracts | plan doc + TARGETS + seams |

## 2. Current numbers (commit `b997be6` unless noted)

- adaptation entries: **73** (12 high-fragility), patches: **5**, anchors: **7**, compat modules: **10**;
- gate registry: **G0=3, G1=8, G2=69, G3=3, G4=7**;
- RSI ledger: **48 runs** — G0 17 first + 1 fail (historical fix), G1 18 first, G2 7 first, G4 5 first, no flake-pass records yet;
- latest release dry run: **G4 release gate OK: 0.4.69 @ b997be6** (store 768,499,205 B / self 773,562,910 B);
- nightly regression: **7/7 PASS** on the current build.

## 3. Known gaps (environment-blocked, tracked)

1. **G3 real-device evidence (complete 2026-11-21)**: unlocked Mate 60, signed self build
   (0.4.69/76) installed; all three suites pass:
   - `verify` PASS (3 s; web 200, account credential-stored);
   - `exec` PASS (36 s; all exec/redirect markers, COPY_NODE_OK, fake-ELF 126/127 as designed);
   - `overlay` PASS (60 s; signed libs present, node dlopen returns 42, downloaded dynamic jq runs).
   Evidence: `docs/evidence/device-lab/20261121T08*.json`.
   Root causes found and fixed during validation:
   - signed builds return a 3-byte bash exit-status cell with binary padding (`30 00 18`);
     the parser now extracts digits instead of requiring `^\d{3}$`;
   - patched bash argv (`/bin/bash`) bypassed the packaged spawn path on real devices and hit
     PRoot's signed-exec loader handoff ("embedded loader descriptors"); `/bin/bash` now routes
     through the same packaged path as `bash`;
   - `device_lab` now requires the probe's own `ok:true`, and the probe derives its DONE marker
     per probe instead of requiring the exec probe's markers for every probe.
2. **Real model turn / session write regression (complete 2026-11-21)**: on the unlocked Mate 60 with
   the signed self build, a real `deepseek-account`/`deepseek-flash` turn completed
   (`turn/end reason=completed`, 1 assistant message, 21 events) and the session log survived an app
   restart (21 events after restart, including `turn/end`). Evidence:
   `docs/evidence/device-lab/20261121-session-turn.json`; validates the session-persistence package patch.
3. **forge fixture**: `emulator-forge-account` reaches OAuth sign-in and the forge panel RPC, but
   `forgePanel/changeRequestText` → `forgePanel/diff-failed` (fixture/TLS/GH_CONFIG environment).
   The forge provider migration itself is validated by build + G1 contract + G2 recovery.
4. **CI execution**: PR/nightly/release workflows are defined; only local equivalents were executed
   (GitHub self-hosted runner not exercised in this session).
5. **Runtime arbitrary dlopen** for unsigned `.so` remains unsupported (build-time overlay only);
   track separately from this architecture goal.

## 4. How to resume

```sh
# static/host gates
python3 gates/run.py --tier G0,G1 --record
# nightly matrix (emulator running, MH_EMULATOR set)
MH_EMULATOR=127.0.0.1:5555 python3 gates/run.py --tier G2 \
  --only nightly-recovery,nightly-native-addon,nightly-inspector,nightly-inspector-availability,nightly-lsp-bundle,nightly-mcp-stdio,nightly-ptc-link-fixture --retries 1
# release dry run
./scripts/adaptation/release_dry_run.sh 0.4.69
# device lab (unlocked phone)
python3 scripts/adaptation/device_lab.py run --suite verify --wait-unlock 120
# weekly scoreboard
python3 scripts/adaptation/gate_report.py
```


## 5. 2026-11-21 emulator re-validation

- Latest build (forge proxy forwarding + bash routing + status parser) installed on the API 26
  emulator in compat PRoot mode: `exec` and `overlay` probes PASS, nightly 7/7 PASS.
- Forge fixture: `emulator-forge-account` PASS after fixing proxy forwarding and cleaning app data;
  `emulator-forge-github` remains blocked by its temporary file-URL plugin injection conflicting with
  the mobile Host's plugin boundary (documented in the plan).
- G1 now has 11 entries (adds workflow wiring and real-device regression guards); G4 release gate
  re-run green at commit `e9d2559`.
