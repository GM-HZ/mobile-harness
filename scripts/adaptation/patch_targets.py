#!/usr/bin/env python3
"""Generate/check the machine-readable patch target index.

    python3 scripts/adaptation/patch_targets.py          # write patches/targets.json
    python3 scripts/adaptation/patch_targets.py --check  # fail if stale
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIES = ROOT / "patches/series.json"
ANCHORS = ROOT / "adaptation/anchors.json"
TARGETS_DOC = ROOT / "patches/TARGETS.md"
OUTPUT = ROOT / "patches/targets.json"


def build():
    series = json.loads(SERIES.read_text())["patches"]
    anchors = json.loads(ANCHORS.read_text())["anchors"]
    doc = TARGETS_DOC.read_text()
    rows = []
    for entry in series:
        gates = ["G1 patch-rehearsal"]
        if any(anchor.get("patch") == entry["file"] for anchor in anchors):
            gates.insert(0, "G1 upstream-anchors")
        rows.append({
            "file": entry["file"],
            "package": entry["package"],
            "path": entry["path"],
            "marker": entry["marker"],
            "removed": entry.get("removed"),
            "reason": entry.get("reason", ""),
            "documented": entry["file"] in doc,
            "gates": gates,
        })
    return {"schema": 1, "source": "scripts/adaptation/patch_targets.py", "targets": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = build()
    if args.check:
        current = json.loads(OUTPUT.read_text()) if OUTPUT.is_file() else None
        if current != data:
            print("patch targets are stale; run scripts/adaptation/patch_targets.py", file=sys.stderr)
            return 1
        print(f"patch targets up to date: {len(data['targets'])} patches")
        return 0
    OUTPUT.write_text(json.dumps(data, indent=2) + "\n")
    undocumented = [row["file"] for row in data["targets"] if not row["documented"]]
    print(f"patch targets: {len(data['targets'])} patches"
          + (f" (undocumented: {undocumented})" if undocumented else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
