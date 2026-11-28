#!/usr/bin/env python3
"""G4: assert a store/default HAP does not ship self-build adaptations.

Checks the packaged HAP zip for:
  - the self-build flag asset (must be signedExecBypass=false or absent),
  - the in-memory loader tools (/usr/bin/mh-exec, mh-install raw assets),
  - the exec shim and overlay libraries under lib/arm64-v8a.

    python3 scripts/adaptation/store_build_check.py [--hap path]
"""
import argparse
import glob
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = ("mh-exec", "mh-install", "libguest_mh_exec_shim", "libguest_lib_", "libguest_ext_", "LICENSE.llama.cpp.txt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hap", type=Path,
                        default=next(iter(sorted(ROOT.glob(".build/artifacts/harmonyos/*-unsigned.hap"))), None))
    args = parser.parse_args()
    if not args.hap or not args.hap.is_file():
        print("FAIL no HAP found; build the default variant first", file=sys.stderr)
        return 1
    failures = []
    with zipfile.ZipFile(args.hap) as hap:
        names = hap.namelist()
        for name in names:
            if any(token in name for token in FORBIDDEN):
                failures.append(f"self-build asset in store HAP: {name}")
        flags = [name for name in names if name.endswith("dsh-self-build.json")]
        for name in flags:
            payload = json.loads(hap.read(name))
            if payload.get("signedExecBypass") or payload.get("selfBuild") or payload.get("localInference"):
                failures.append(f"store HAP enables self build: {payload}")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print(f"G4 store shape OK: {args.hap.name} ({len(names)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
