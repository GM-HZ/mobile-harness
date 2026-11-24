#!/usr/bin/env python3
"""G1: verify literal upstream anchors against the assembled DSH layer.

    python3 scripts/adaptation/anchors.py [--layer <dsh-chunks.json|dsh-layer.zip>] [--json out]

Layer resolution order: --layer, $MH_DSH_LAYER, then the current worktree stage.
Exit codes: 0 ok, 1 anchor drift, 2 layer unavailable (gate is skipped).
"""
import argparse
import json
import sys
from pathlib import Path

from dsh_layer import locate_layer, open_layer

ROOT = Path(__file__).resolve().parents[2]
ANCHORS = ROOT / "adaptation/anchors.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer")
    parser.add_argument("--json")
    args = parser.parse_args()
    layer = locate_layer(args.layer)
    if not layer:
        print("SKIP upstream anchors: DSH layer not available (pass --layer or MH_DSH_LAYER)", file=sys.stderr)
        return 2
    manifest = json.loads(ANCHORS.read_text())
    failures = []
    checked = []
    with open_layer(layer) as members:
        for anchor in manifest["anchors"]:
            path = anchor["file"]
            if path not in members:
                failures.append(f"{anchor['id']}: missing {path}")
                continue
            payload = members[path].read(path)
            if anchor.get("exists"):
                checked.append({"id": anchor["id"], "ok": True, "kind": "exists"})
                continue
            text = payload.decode("utf-8", "replace")
            if "pattern" not in anchor:
                ok = anchor.get("replacement", "\0") in text
                checked.append({"id": anchor["id"], "ok": ok, "kind": "patched"})
                if not ok:
                    failures.append(f"{anchor['id']}: patch marker {anchor.get('replacement')!r} missing")
                continue
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
