#!/usr/bin/env python3
"""G4: assert a built HAP matches a variant definition (variants/*.json)."""
import argparse
import glob
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = ROOT / "variants"


def load(name):
    path = Path(name)
    if not path.is_file():
        path = VARIANTS / (name + ".json")
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant")
    parser.add_argument("--hap", type=Path)
    parser.add_argument("--require-self-build-metadata", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        for path in sorted(VARIANTS.glob("*.json")):
            data = json.loads(path.read_text())
            print(f"{path.stem}: {data.get('description', '')}")
        return 0
    if not args.variant:
        print("--variant is required", file=sys.stderr)
        return 2
    variant = load(args.variant)
    hap = args.hap
    if not hap:
        candidates = sorted(ROOT.glob(".build/artifacts/harmonyos/*-unsigned.hap"))
        hap = candidates[-1] if candidates else None
    if not hap or not Path(hap).is_file():
        print("SKIP variant check: HAP not found (pass --hap)", file=sys.stderr)
        return 2
    hap = Path(hap)
    with zipfile.ZipFile(hap) as archive:
        names = archive.namelist()
        failures = []
        for token in variant["hap"].get("present", []):
            if not any(token in name for name in names):
                failures.append(f"missing required asset {token}")
        for token in variant["hap"].get("absent", []):
            hits = [name for name in names if token in name]
            if hits:
                failures.append(f"forbidden asset {token}: {hits[:3]}")
        maximum = variant["hap"].get("maxBytes")
        if maximum and hap.stat().st_size > maximum:
            failures.append(f"HAP too large: {hap.stat().st_size} > {maximum}")
        for token, minimum in variant["hap"].get("minimum", {}).items():
            count = sum(1 for name in names if token in name)
            if count < minimum:
                failures.append(f"too few {token}: {count} < {minimum}")
        flag_names = [name for name in names if name.endswith("dsh-self-build.json")]
        expected = variant["hap"].get("flag")
        if expected is not None:
            if len(flag_names) != 1:
                failures.append("expected exactly one dsh-self-build.json")
            else:
                flag = json.loads(archive.read(flag_names[0]))
                for key, value in expected.items():
                    actual = flag.get(key)
                    if actual != value or type(actual) is not type(value):
                        failures.append(f"flag {key}={actual!r}, expected {value!r}")
                module = json.loads(archive.read("module.json"))["module"]
                build_values = [item.get("value") for item in module.get("metadata", [])
                                if item.get("name") == "org.mobileharness.selfBuild"]
                if build_values or args.require_self_build_metadata:
                    expected_value = "true" if expected["selfBuild"] else "false"
                    if build_values != [expected_value]:
                        failures.append(f"installed self-build metadata must have one value {expected_value}")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print(f"G4 variant OK: {variant['name']} <- {hap.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
