# Upstream seams

Each document here is a **contract** with upstream DeepSeek Harness (or a vendored
dependency). It records the exact files/anchors we depend on, why we depend on
them, how they fail, and which gate catches the failure. When upstream moves,
update the contract and the adaptation manifest together.

Template fields:

- **Upstream**: package + files + version pin (see `versions.lock.json`).
- **Anchor**: literal text/path/behavior we rely on.
- **Our assumption**: behavior our adapters require.
- **Failure mode**: symptom when upstream changes.
- **Replacement strategy**: extension seam to migrate to if the anchor is fragile.
- **Gate**: which gate tier fails on regression.

Current contracts:

- [host-bash-hooks.md](host-bash-hooks.md) — bash/session-persistence runtime hooks (`replacePinned` anchors).
- [web-settings-injection.md](web-settings-injection.md) — settings client injection.
- [native-overlay.md](native-overlay.md) — HAP native bindings and guest library/extension overlay.
