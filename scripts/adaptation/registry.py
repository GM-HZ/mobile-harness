#!/usr/bin/env python3
"""Generate gates/registry.json from the test tree.

Tiers:
  G0 static/consistency, G1 host contracts, G2 emulator capability,
  G3 real-device lab, G4 build/release.
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "gates/registry.json"

G0 = [
    {"id": "adaptation-verify", "command": "python3 scripts/adaptation/verify.py",
     "covers": "manifest/pins/submodule consistency", "timeout": 120},
    {"id": "manifest-fresh", "command": "python3 scripts/adaptation/inventory.py --check",
     "covers": "checked-in manifest matches the tree", "timeout": 120},
    {"id": "relay-preflight-self-test", "command": "python3 tests/smoke/relay-preflight.py --self-test",
     "covers": "public Relay preflight tooling", "requires": ["pinned DSH runtime cache"],
     "optional": True, "timeout": 180},
]
G4 = [
    {"id": "release-dry-run", "command": "./scripts/adaptation/release_dry_run.sh",
     "covers": "release packages, shapes and same-commit evidence for store, self and AppGallery",
     "optional": True, "timeout": 3600},
    {"id": "build-unsigned", "command": "HARMONY_UNSIGNED=1 ./build.sh --package",
     "covers": "emulator HAP builds", "timeout": 1800},
    {"id": "build-self", "command": "HARMONY_UNSIGNED=1 HARMONY_SELF_BUILD=1 ./build.sh --package",
     "covers": "self-build variant builds and includes exec/overlay assets", "timeout": 1800},
    {"id": "build-store-shape", "command": "HARMONY_UNSIGNED=1 ./build.sh --package && python3 scripts/adaptation/store_build_check.py",
     "covers": "store HAP has no exec shim / overlay libraries", "timeout": 1800},
    {"id": "release-gate", "command": "python3 scripts/adaptation/release_gate.py --version <version>",
     "covers": "tag/release blocked unless green release evidence exists for the commit",
     "requires": ["release evidence for this commit"], "optional": True, "timeout": 120},
    {"id": "release-evidence", "command": "python3 scripts/adaptation/release_evidence.py --store <store-hap> --self <self-hap>",
     "covers": "artifact hashes/sizes + store/self shape assertions in one release record",
     "requires": ["built store and self HAPs"], "optional": True, "timeout": 300},
    {"id": "variant-store-check", "command": "python3 scripts/adaptation/variant_check.py --variant store --hap <hap>",
     "covers": "store HAP matches variants/store.json", "optional": True, "timeout": 120},
    {"id": "variant-self-check", "command": "python3 scripts/adaptation/variant_check.py --variant self --hap <hap>",
     "covers": "self HAP matches variants/self.json", "optional": True, "timeout": 120},
]


def tracked(pattern):
    result = subprocess.run(["git", "ls-files", "-z", "--", pattern], cwd=ROOT,
                            check=True, stdout=subprocess.PIPE)
    return [name for name in result.stdout.decode().split("\0") if name]


def requirements(name):
    tags = []
    if "voice" in name:
        tags.append("voice-model+audio fixtures")
    if "ollama" in name:
        tags.append("host Ollama model")
    if "liveshare" in name:
        tags.append("relay fixture/second emulator")
    if "ptc" in name:
        tags.append("model route")
    if "forge" in name:
        tags.append("host gh credentials")
    if "account" in name:
        tags.append("clean signed-out device")
    return tags


def main():
    emulator = [name for name in tracked("tests/smoke/emulator-*.py")]
    device = [name for name in tracked("tests/smoke/mate60-*.py")]
    g2 = [{"id": "capability-parity-gate",
           "command": "python3 tests/bench/capability-parity-regression.py --output .build/capability-parity-gate.json",
           "covers": "recovery/voice/ollama/ptc/liveshare/account/addon", "timeout": 1200}]
    g2.append({"id": "nightly-native-addon",
               "command": "python3 tests/smoke/emulator-native-addon-location.py \"$MH_EMULATOR\" .build/gate-evidence/native-addon.json",
               "covers": "native addon location + Inspector evaluation on the native Host",
               "requires": ["MH_EMULATOR env"], "timeout": 1200})
    g2.append({"id": "startup-warm-budget",
               "command": "python3 scripts/adaptation/startup.py \"$MH_EMULATOR\" --warm --max-wall 30 --output .build/gate-evidence/startup-warm.json",
               "covers": "warm startup (ability foreground to ArkWeb) stays under the 10s budget",
               "requires": ["MH_EMULATOR env"], "timeout": 300})
    g2.append({"id": "nightly-plugin-git-update",
               "command": "python3 tests/smoke/emulator-plugin-git-update.py \"$MH_EMULATOR\" .build/gate-evidence/plugin-git-update.json",
               "covers": "plugin manager installs a local git plugin and enables it",
               "requires": ["MH_EMULATOR env"], "timeout": 1200})
    g2.append({"id": "nightly-mcp-stdio",
               "command": "python3 tests/smoke/emulator-mcp-stdio.py \"$MH_EMULATOR\" .build/gate-evidence/mcp-stdio.json",
               "covers": "Node/Python MCP stdio servers on the native Host", "requires": ["MH_EMULATOR env"],
               "timeout": 1200})
    g2.append({"id": "nightly-ptc-link-fixture",
               "command": "python3 tests/smoke/emulator-ptc-link-fixture.py \"$MH_EMULATOR\" .build/gate-evidence/ptc-link-fixture.json",
               "covers": "platform link restrictions that gate PTC boundary fixtures",
               "requires": ["MH_EMULATOR env"], "timeout": 900})
    g2.append({"id": "nightly-inspector-availability",
               "command": "python3 tests/smoke/emulator-inspector-availability.py \"$MH_EMULATOR\" .build/gate-evidence/inspector-availability.json",
               "covers": "optional Inspector worker availability probe", "requires": ["MH_EMULATOR env"],
               "timeout": 900})
    g2.append({"id": "nightly-lsp-bundle",
               "command": "python3 tests/smoke/emulator-lsp-bundle.py \"$MH_EMULATOR\" .build/gate-evidence/lsp-bundle.json",
               "covers": "LSP bundle composition on the native Host", "requires": ["MH_EMULATOR env"],
               "timeout": 1200})
    g2.append({"id": "nightly-inspector",
               "command": "python3 tests/smoke/emulator-inspector.py \"$MH_EMULATOR\" .build/gate-evidence/inspector.json",
               "covers": "Inspector CDP over the authenticated ArkWeb proxy",
               "requires": ["MH_EMULATOR env"], "timeout": 1200})
    g2.append({"id": "nightly-recovery",
               "command": "python3 tests/smoke/emulator-recovery.py \"$MH_EMULATOR\" .build/gate-evidence/recovery.json",
               "covers": "plugin crash, safe startup and rollback in the recovery UI", "requires": ["MH_EMULATOR env"],
               "timeout": 1200})
    for capability in ("images", "search"):
        g2.append({"id": f"appgallery-{capability}",
                   "command": f'python3 tests/smoke/emulator-appgallery-{capability}.py "$MH_APPGALLERY_EMULATOR"',
                   "covers": f"AppGallery Release native {capability} through DSH",
                   "requires": ["MH_APPGALLERY_EMULATOR env", "AppGallery Release HAP after privacy consent"],
                   "optional": True, "timeout": 600})
    for name in sorted(emulator):
        if name.endswith("emulator-recovery.py") or Path(name).name.startswith("emulator-appgallery-"):
            continue
        g2.append({"id": Path(name).stem, "command": f"python3 {name} <target> <output> [scenario flags]",
                   "covers": "smoke acceptance", "requires": requirements(name), "timeout": 1800})
    g3 = [{"id": "device-lab-verify", "command": "python3 scripts/adaptation/device_lab.py run --suite verify",
           "covers": "device lab protocol: lock + status + read-only verify", "optional": True,
           "requires": ["USB device connected and unlocked"], "timeout": 900}]
    for name in sorted(device):
        command = f"python3 {name} --target <usb-serial> --output <output>"
        requires = ["USB device", "screen unlocked"]
        if Path(name).stem == "mate60-proot-exec":
            requires.append("installed HAP self-build metadata")
        g3.append({"id": Path(name).stem, "command": command,
                   "covers": "real-device acceptance", "requires": requires,
                   "timeout": 1200})
    registry = {
        "schema": 1,
        "source": "scripts/adaptation/registry.py",
        "tiers": {
            "G0": {"name": "static/consistency", "entries": G0},
            "G1": {"name": "host contracts", "entries": [
                {"id": "host-syntax", "command": "python3 scripts/adaptation/host_checks.py",
                 "covers": "node --check for host/compat overlays", "timeout": 180},
                {"id": "upstream-anchors", "command": "python3 scripts/adaptation/anchors.py",
                 "covers": "literal upstream anchors used by runtime hooks",
                 "requires": ["assembled DSH layer in the current worktree"], "timeout": 300},
                {"id": "compat-inventory", "command": "python3 scripts/adaptation/compat_check.py",
                 "covers": "compat modules have inventory rows, consumers and documented gates", "timeout": 120},
                {"id": "compat-contracts", "command": "python3 scripts/adaptation/compat_contracts.py",
                 "covers": "forge/package/liveshare/sharp public behavior contracts", "timeout": 120},
                {"id": "guidance-docs", "command": "python3 scripts/adaptation/guidance_check.py",
                 "covers": "AGENTS/framework/roadmap/module guidance files, sections and indexes",
                 "timeout": 120},
                {"id": "remote-hosts-contract", "command": "node tests/contract/remote-hosts.cjs",
                 "covers": "self/lab gate, HTTPS origin, same-origin token exchange and metadata-only persistence",
                 "timeout": 120},
                {"id": "workflow-check", "command": "python3 scripts/adaptation/workflow_check.py",
                 "covers": "gate workflows stay wired to gate scripts and steps", "timeout": 120},
                {"id": "anchor-coverage", "command": "python3 scripts/adaptation/anchor_scan.py --check",
                 "covers": "every replacePinned anchor is indexed in adaptation/anchors.full.json",
                 "timeout": 120},
                {"id": "host-regressions", "command": "python3 scripts/adaptation/host_regressions.py",
                 "covers": "/bin/bash routing, padded status parsing, probe done/ok checks", "timeout": 120},
                {"id": "forge-account-fixture",
                 "command": "python3 tests/smoke/emulator-forge-account.py \"$MH_EMULATOR\" .build/gate-evidence/forge-account.json",
                 "covers": "Forge account device-flow fixture (clean app data required)",
                 "requires": ["MH_EMULATOR env", "bm clean -n org.sayact.nodepoc -d before the run"],
                 "optional": True, "timeout": 1800},
                {"id": "patch-targets", "command": "python3 scripts/adaptation/patch_targets.py --check",
                 "covers": "machine patch index matches series.json/anchors and TARGETS.md",
                 "timeout": 120},
                {"id": "patch-rehearsal", "command": "python3 scripts/adaptation/patch_rehearsal.py",
                 "covers": "patches/series.json applies cleanly to the pinned tarballs",
                 "requires": ["upstream tarball cache (scripts/adaptation/bump.py)"],
                 "optional": True, "timeout": 300},
                {"id": "host-contracts", "command": "python3 scripts/adaptation/host_contracts.py",
                 "covers": "apply boot-time transformations and validate the results",
                 "requires": ["assembled DSH layer"], "optional": True, "timeout": 300},
                {"id": "upstream-bump-rehearsal", "command": "python3 scripts/adaptation/bump.py",
                 "covers": "dry-run the next DSH release against our anchors",
                 "requires": ["npm registry"], "optional": True, "timeout": 600},
            ], "note": "anchor checks need the assembled DSH layer (build machine)"},
            "G2": {"name": "emulator capability", "entries": g2,
                   "note": "requires two API 26 ARM64 emulators for cross-device cases"},
            "G3": {"name": "real-device lab", "entries": g3,
                   "note": "device-specific; run when the Mate 60 is connected and unlocked"},
            "G4": {"name": "build/release", "entries": G4,
                   "note": "store/self/lab variant matrix and HAP size/feature budgets"},
        },
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(registry, indent=2) + "\n")
    print(f"gates registry: " + ", ".join(f"{tier}={len(registry['tiers'][tier]['entries'])}"
                                          for tier in registry["tiers"]))


if __name__ == "__main__":
    main()
