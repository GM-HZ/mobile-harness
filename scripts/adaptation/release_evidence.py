#!/usr/bin/env python3
"""G4: collect release evidence for the store and self HAP variants.

Runs the store shape check and the variant assertions, records artifact hashes and
sizes, writes docs/evidence/release/<version>-<commit>.json and appends the run to
the RSI ledger.

    python3 scripts/adaptation/release_evidence.py --store .build/store.hap --self .build/self.hap
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence/release"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run_check(arguments):
    result = subprocess.run(["python3", *arguments], cwd=ROOT, capture_output=True, text=True)
    return {"command": " ".join(arguments), "exit": result.returncode, "passed": result.returncode == 0,
            "output": (result.stdout + result.stderr).strip()[-1200:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--self", dest="self_hap", type=Path, required=True)
    parser.add_argument("--version", default=None)
    args = parser.parse_args()
    for label, path in (("store", args.store), ("self", args.self_hap)):
        if not path.is_file():
            print(f"FAIL missing {label} HAP: {path}", file=sys.stderr)
            return 2
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    version = args.version
    if not version:
        match = re.search(r"-v(\d+\.\d+\.\d+)-", args.store.name)
        version = match.group(1) if match else "unknown"
    variants = {name: json.loads((ROOT / f"variants/{name}.json").read_text()) for name in ("store", "self")}
    checks = [
        run_check(["scripts/adaptation/store_build_check.py", "--hap", str(args.store)]),
        run_check(["scripts/adaptation/variant_check.py", "--variant", "store", "--hap", str(args.store)]),
        run_check(["scripts/adaptation/variant_check.py", "--variant", "self", "--hap", str(args.self_hap)]),
    ]
    artifacts = {}
    for label, path in (("store", args.store), ("self", args.self_hap)):
        artifacts[label] = {"file": path.name, "sha256": sha256(path), "bytes": path.stat().st_size,
                            "maxBytes": variants[label]["hap"].get("maxBytes")}
    ok = all(check["passed"] for check in checks)
    evidence = {"version": version, "commit": commit, "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "artifacts": artifacts, "checks": checks, "ok": ok}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    output = EVIDENCE / f"{version}-{commit}.json"
    output.write_text(json.dumps(evidence, indent=2) + "\n")
    subprocess.run(["python3", "scripts/adaptation/rsi_ledger.py", "record", "--tiers", "G4",
                    "--evidence", str(output.relative_to(ROOT))] + (["--ok"] if ok else []),
                   cwd=ROOT, check=False)
    print(f"release evidence: {output.relative_to(ROOT)}")
    print(f"  store: {artifacts['store']['bytes']:,} B (max {artifacts['store']['maxBytes']:,})")
    print(f"  self:  {artifacts['self']['bytes']:,} B (max {artifacts['self']['maxBytes']:,})")
    for check in checks:
        print(f"  {'OK  ' if check['passed'] else 'FAIL'} {check['command']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
