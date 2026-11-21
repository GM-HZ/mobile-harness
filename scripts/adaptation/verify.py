#!/usr/bin/env python3
"""G0 gate: verify the adaptation manifest against the working tree.

Fails when a surfaced file is missing, its hash drifted, the app tree changed,
a pinned input moved or a submodule gitlink no longer matches versions.lock.json.

    python3 scripts/adaptation/verify.py
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "adaptation/manifest.json"
VERSIONS = ROOT / "versions.lock.json"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hash(directory):
    digest = hashlib.sha256()
    result = subprocess.run(["git", "ls-files", "-z", "--", str(directory)], cwd=ROOT,
                            check=True, stdout=subprocess.PIPE)
    for name in sorted(n for n in result.stdout.decode().split("\0") if n):
        path = ROOT / name
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + sha256(path).encode() + b"\n")
    return digest.hexdigest()


def gitlink(name):
    result = subprocess.run(["git", "ls-tree", "HEAD", f"vendor/repos/{name}"], cwd=ROOT,
                            check=True, stdout=subprocess.PIPE, text=True)
    parts = result.stdout.split()
    return parts[2] if len(parts) >= 3 else None


def main():
    if not MANIFEST.is_file() or not VERSIONS.is_file():
        print("missing adaptation/manifest.json or versions.lock.json", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST.read_text())
    versions = json.loads(VERSIONS.read_text())
    failures = []
    for row in manifest["entries"]:
        if row["kind"] != "file":
            continue
        path = ROOT / row["source"]
        if not path.is_file():
            failures.append(f"missing {row['source']}")
            continue
        if sha256(path) != row["sha256"]:
            failures.append(f"hash drift {row['source']}")
    for row in manifest["entries"]:
        if row["kind"] != "tree":
            continue
        if tree_hash(ROOT / row["source"]) != row["sha256"]:
            failures.append(f"tree drift {row['source']} (run scripts/adaptation/inventory.py)")
    for name, link in versions["submodules"].items():
        if gitlink(name) != link:
            failures.append(f"submodule {name} moved: {link} -> {gitlink(name)}")
    for pin in ("buildInputs", "guestToolsLock"):
        row = versions.get(pin) or {}
        path = ROOT / (row.get("path") or "")
        if row.get("sha256") and path.is_file() and sha256(path) != row["sha256"]:
            failures.append(f"pinned input drifted: {pin}")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print(f"G0 OK: {len(manifest['entries'])} adaptation entries, dsh {versions['dshRelease']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
