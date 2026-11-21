#!/usr/bin/env python3
"""Generate the adaptation manifest and the upstream version lock.

The manifest is the single inventory of every adaptation surface: host runtime
overlays, compatibility shims, native runtime code, packaging inputs, app
sources and variant switches. `scripts/adaptation/verify.py` checks it against
the working tree (G0 gate).

    python3 scripts/adaptation/inventory.py [--check]

`--check` only exits non-zero when the checked-in manifest is stale.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "adaptation/manifest.json"
VERSIONS = ROOT / "versions.lock.json"

LAYERS = [
    ("host", "packages/dsh-host", "runtime overlay copied into the guest root"),
    ("web", "runtime/harmonyos/web", "web client injection"),
    ("compat", "runtime/harmonyos/compat", "upstream capability shim"),
    ("diagnostics", "runtime/harmonyos/diagnostics", "diagnostic probe"),
    ("native", "runtime/harmonyos/native", "native runtime / adapter"),
    ("packaging", "runtime/harmonyos/packaging", "build and packaging scripts"),
    ("tools", "runtime/harmonyos/tools", "guest tools shipped inside the HAP"),
    ("bundles", "packages/bundles", "profile/bundle overlays"),
    ("variants", "variants", "store/self/lab build variant definitions"),
    ("patches", "patches", "npm package patch series applied while assembling the DSH layer"),
]
TREE_LAYERS = [("app", "apps/harmonyos", "HarmonyOS app host (ArkTS + native)")]
PIN_FILES = [
    "docs/build-inputs.sha256",
    "docs/guest-tools-lock.json",
    "runtime/harmonyos/dsh/package-lock.json",
    ".gitmodules",
]
HIGH_RISK = ("replacePinned", "registerHooks", ".replace(", "readTextSync", "process.dlopen")
MEDIUM_RISK = ("process.env", "require(", "import(")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tracked_files(directory):
    result = subprocess.run(["git", "ls-files", "-z", "--", str(directory)], cwd=ROOT,
                            check=True, stdout=subprocess.PIPE)
    return [ROOT / name for name in result.stdout.decode().split("\0") if name]


def tree_hash(directory):
    digest = hashlib.sha256()
    files = sorted(tracked_files(directory))
    for path in files:
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + sha256(path).encode() + b"\n")
    return digest.hexdigest(), len(files)


def touchpoints(text):
    found = set(re.findall(r"replacePinned\([^,]+,\s*'([^']+)'", text))
    found.update(re.findall(r"@deepseek-ai/dsh[-a-z0-9]+", text))
    found.update(re.findall(r"dsh-[a-z0-9-]+/lib/[a-z0-9-]+\.js", text))
    return sorted(found)[:12]


def fragility(text):
    if any(marker in text for marker in HIGH_RISK):
        return "high"
    if any(marker in text for marker in MEDIUM_RISK):
        return "medium"
    return "low"


def gitlink(name):
    result = subprocess.run(["git", "ls-tree", "HEAD", f"vendor/repos/{name}"], cwd=ROOT,
                            check=True, stdout=subprocess.PIPE, text=True)
    parts = result.stdout.split()
    return parts[2] if len(parts) >= 3 else None


def dsh_version():
    lock = json.loads((ROOT / "runtime/harmonyos/dsh/package-lock.json").read_text())
    return lock.get("packages", {}).get("node_modules/@deepseek-ai/dsh", {}).get("version")


def entries():
    rows = []
    for layer, directory, role in LAYERS:
        for path in sorted(tracked_files(directory)):
            text = ""
            try:
                text = path.read_text(errors="ignore")[:40000]
            except OSError:
                pass
            rows.append({
                "id": f"{layer}:{path.relative_to(ROOT)}",
                "layer": layer,
                "kind": "file",
                "source": str(path.relative_to(ROOT)),
                "role": role,
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "fragility": fragility(text),
                "upstreamTouchpoints": touchpoints(text),
                "gates": ["G0", "G1"] if layer in ("host", "web", "compat") else ["G0"],
            })
    for layer, directory, role in TREE_LAYERS:
        digest, count = tree_hash(directory)
        rows.append({
            "id": f"{layer}:{directory}",
            "layer": layer,
            "kind": "tree",
            "source": directory,
            "role": role,
            "sha256": digest,
            "files": count,
            "fragility": "medium",
            "upstreamTouchpoints": [],
            "gates": ["G0", "G4"],
        })
    return rows


def switches():
    rows = []
    patterns = {
        "HARMONY_SELF_BUILD": "self-built variant: exec shim, mh-exec, native overlay, self signed-exec bypass",
        "HARMONY_GUEST_LIB_GROUPS": "signed native library/extension groups (common,media,extensions)",
        "HARMONY_UNSIGNED": "unsigned emulator build",
        "HARMONY_SIGNING_PROFILE": "real-device signing profile",
        "HARMONY_EXPERIMENTAL_HOST_PROCESS": "experimental host-process build",
    }
    for name, description in patterns.items():
        result = subprocess.run(["git", "grep", "-l", name], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        code_prefixes = ("scripts/", "runtime/", "apps/", "packages/", ".github/", "tests/")
        places = [line for line in result.stdout.splitlines()
                  if line.startswith(code_prefixes)][:10]
        rows.append({"id": f"switch:{name}", "layer": "variant", "kind": "switch",
                     "source": name, "role": description, "places": places,
                     "gates": ["G0", "G4"]})
    return rows


def pins():
    rows = {}
    for relative in PIN_FILES:
        path = ROOT / relative
        rows[relative] = {"sha256": sha256(path), "bytes": path.stat().st_size} if path.is_file() else None
    rows["submodules"] = {name: gitlink(name) for name in
                          ("dsh", "node", "proot", "dshm", "termony", "typescript",
                           "typescript-language-server", "pyright")}
    rows["dshRelease"] = dsh_version()
    rows["npmLock"] = {"path": "runtime/harmonyos/dsh/package-lock.json",
                       "sha256": sha256(ROOT / "runtime/harmonyos/dsh/package-lock.json")}
    return rows


def build():
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = {
        "schema": 1,
        "generatedFrom": commit,
        "layers": [layer for layer, _, _ in LAYERS + TREE_LAYERS],
        "entries": entries() + switches(),
        "pins": pins(),
    }
    versions = {
        "schema": 1,
        "dshRelease": manifest["pins"]["dshRelease"],
        "npmLock": manifest["pins"]["npmLock"],
        "submodules": manifest["pins"]["submodules"],
        "buildInputs": {"path": "docs/build-inputs.sha256", **manifest["pins"]["docs/build-inputs.sha256"]},
        "guestToolsLock": {"path": "docs/guest-tools-lock.json", **manifest["pins"]["docs/guest-tools-lock.json"]},
    }
    return manifest, versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest, versions = build()
    if args.check:
        current = json.loads(MANIFEST.read_text()) if MANIFEST.is_file() else None
        current_versions = json.loads(VERSIONS.read_text()) if VERSIONS.is_file() else None

        def stable(value):
            if isinstance(value, dict):
                return {key: stable(item) for key, item in value.items() if key != "generatedFrom"}
            return value

        if stable(current) != stable(manifest) or current_versions != versions:
            print("adaptation manifest is stale; run scripts/adaptation/inventory.py", file=sys.stderr)
            return 1
        print("adaptation manifest is up to date")
        return 0
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest["generatedFrom"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    VERSIONS.write_text(json.dumps(versions, indent=2) + "\n")
    by_layer = {}
    for row in manifest["entries"]:
        by_layer[row["layer"]] = by_layer.get(row["layer"], 0) + 1
    high = [row["id"] for row in manifest["entries"] if row.get("fragility") == "high"]
    print(f"adaptation entries: {len(manifest['entries'])} {by_layer}")
    print(f"high-fragility surfaces: {len(high)}")
    for row in high:
        print("  ", row)
    print(f"dsh release: {versions['dshRelease']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
