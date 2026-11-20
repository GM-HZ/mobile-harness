#!/usr/bin/env python3
"""G1: verify literal upstream anchors against the assembled DSH layer.

    python3 scripts/adaptation/anchors.py [--layer <dsh-layer.zip>] [--json out]

Layer resolution order: --layer, $MH_DSH_LAYER, .build/stage/.../dsh-layer.zip.
Exit codes: 0 ok, 1 anchor drift, 2 layer unavailable (gate is skipped).
"""
import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANCHORS = ROOT / "adaptation/anchors.json"
CANDIDATES = [
    ROOT / ".build/stage/harmonyos/entry/src/main/resources/rawfile/dsh-layer.zip",
    ROOT.parent / "harmonyos-capability-parity/.build/stage/harmonyos/entry/src/main/resources/rawfile/dsh-layer.zip",
]


def locate_layer(explicit):
    if explicit:
        return Path(explicit)
    environment = os.environ.get("MH_DSH_LAYER")
    if environment:
        return Path(environment)
    for candidate in CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer")
    parser.add_argument("--json")
    args = parser.parse_args()
    layer = locate_layer(args.layer)
    if not layer or not layer.is_file():
        print("SKIP upstream anchors: DSH layer not available (pass --layer or MH_DSH_LAYER)", file=sys.stderr)
        return 2
    manifest = json.loads(ANCHORS.read_text())
    failures = []
    checked = []
    with zipfile.ZipFile(layer) as archive:
        names = set(archive.namelist())
        for anchor in manifest["anchors"]:
            path = anchor["file"]
            if path not in names:
                failures.append(f"{anchor['id']}: missing {path}")
                continue
            payload = archive.read(path)
            if anchor.get("exists"):
                checked.append({"id": anchor["id"], "ok": True, "kind": "exists"})
                continue
            text = payload.decode("utf-8", "replace")
            actual = text.count(anchor["pattern"])
            replacement = anchor.get("replacement")
            patched = replacement is not None and replacement in text
            ok = actual == anchor["count"] or patched
            checked.append({"id": anchor["id"], "ok": ok, "expected": anchor["count"],
                            "actual": actual, "patched": bool(patched)})
            if not ok:
                failures.append(f"{anchor['id']}: expected {anchor['count']} occurrence(s), "
                                f"found {actual} in {path} (patched={patched})")
    result = {"layer": str(layer), "checked": checked, "failures": failures, "ok": not failures}
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2) + "\n")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print(f"G1 upstream anchors OK: {len(checked)} anchors in {layer.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
