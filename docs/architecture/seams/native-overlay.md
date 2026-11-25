# Seam: HAP native bindings and guest library/extension overlay

- Layer: HarmonyOS packaging (`runtime/harmonyos/native/poc.c`, `scripts/build/harmonyos_guest_extras.py`, `docs/guest-tools-lock.json`).
- Mechanism: native libs are bound into the guest through `packaged[]` (+ generated `guest-tools.inc` / `guest-libs.inc`); every binding maps a guest path to a signed HAP library.
- The `common` group packages the jq CLI from the same pinned Alpine APK as libjq. For that APK, `mh-install jq` checks the download digest before switching the command to the signed program path. The extra layer contains the install metadata generated from the lock.
- Normal self startup migrates a legacy jq registration when the launcher, receipt, downloaded APK and extracted tool match the signed package's metadata. The launcher is replaced atomically and custom registrations stay available. The shell extras identity tracks variant changes during upgrade.
- The self launcher reports exit status 126 if control returns before the child exits through the program, including when launch setup fails.
- jq is distributed under the [jq MIT license](https://github.com/jqlang/jq/blob/jq-1.8.2/COPYING), with [Oniguruma](https://github.com/kkos/oniguruma/blob/v6.9.10/COPYING) linked through the existing native overlay.
- Our assumptions:
  - binding tables are compiled in; adding a library requires a rebuild;
  - the number of bindings applied depends on the launch stage (`dsh_test` / `node_test` / default) — new bindings must stay inside the stage's limit;
  - store builds must not ship `mh-exec`/`mh-install`, the exec shim or overlay libraries; self builds select groups with `HARMONY_GUEST_LIB_GROUPS`;
  - stale overlay libs from previous builds are removed before staging.
- Failure mode: guest path missing (binding absent), `HARMONY_PRELOAD loader file mmap failed`, or a store build accidentally shipping self-build assets.
- Replacement strategy: keep bindings data-driven (manifest + generated inc) and add a loader fallback only for self builds.
- Gate: G4 `store_build_check.py` + variant build assertions, G2 `native-overlay` acceptance, G0 manifest/pins.
- History: 0.4.69 added configurable common/media/extension overlay; self-build exec shim.
