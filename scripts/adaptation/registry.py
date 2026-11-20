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
    {"id": "build-unsigned", "command": "HARMONY_UNSIGNED=1 ./build.sh --package",
     "covers": "emulator HAP builds", "timeout": 1800},
    {"id": "build-self", "command": "HARMONY_UNSIGNED=1 HARMONY_SELF_BUILD=1 ./build.sh --package",
     "covers": "self-build variant builds and includes exec/overlay assets", "timeout": 1800},
    {"id": "build-store-shape", "command": "HARMONY_UNSIGNED=1 ./build.sh --package && python3 scripts/adaptation/store_build_check.py",
     "covers": "store HAP has no exec shim / overlay libraries", "timeout": 1800},
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
    for name in sorted(emulator):
        if name.endswith("emulator-recovery.py"):
            continue
        g2.append({"id": Path(name).stem, "command": f"python3 {name} <target> <output> [scenario flags]",
                   "covers": "smoke acceptance", "requires": requirements(name), "timeout": 1800})
    g3 = []
    for name in sorted(device):
        command = f"python3 {name} --target <usb-serial> --output <output>"
        g3.append({"id": Path(name).stem, "command": command,
                   "covers": "real-device acceptance", "requires": ["USB device", "screen unlocked"],
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
                 "requires": ["assembled dsh-layer.zip"], "timeout": 300},
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
