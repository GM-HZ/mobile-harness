#!/usr/bin/env python3
"""G1: structural contract for the HarmonyOS compatibility layer.

Every compat module must have an entry in adaptation/compat.json, its consumers
must exist and reference the module, every listed gate id must exist in the gate
registry, and docs/architecture/compat-layer.md must document the module.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPAT = ROOT / "runtime/harmonyos/compat"
INVENTORY = ROOT / "adaptation/compat.json"
DOC = ROOT / "docs/architecture/compat-layer.md"
REGISTRY = ROOT / "gates/registry.json"


def main():
    inventory = json.loads(INVENTORY.read_text())
    registry = json.loads(REGISTRY.read_text())["tiers"]
    gate_ids = {entry["id"] for tier in registry.values() for entry in tier["entries"]}
    doc = DOC.read_text()
    failures = []
    modules = {row["file"]: row for row in inventory["modules"]}
    present = {path.name for path in COMPAT.glob("*") if path.is_file() and not path.name.startswith("LICENSE")}
    for name in sorted(present - set(modules)):
        failures.append(f"compat module not in adaptation/compat.json: {name}")
    for name, row in modules.items():
        if name not in present:
            failures.append(f"compat inventory lists a missing file: {name}")
        for consumer in row["consumers"]:
            path = ROOT / consumer
            if not path.is_file():
                failures.append(f"{name}: missing consumer {consumer}")
            elif name not in path.read_text(errors="ignore"):
                failures.append(f"{name}: consumer {consumer} does not reference it")
        for gate in row["gates"]:
            if gate not in gate_ids:
                failures.append(f"{name}: gate id {gate} is not in gates/registry.json")
        if f"### {name}" not in doc:
            failures.append(f"{name}: not documented in docs/architecture/compat-layer.md")
        if row["decision"] not in ("keep-compat", "upstream-seam-candidate", "migrate-patch", "converged"):
            failures.append(f"{name}: unknown decision {row['decision']}")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print(f"G1 compat layer OK: {len(modules)} modules, {len(gate_ids)} gate ids")
    return 0


if __name__ == "__main__":
    sys.exit(main())
