#!/usr/bin/env python3
"""G4 tag/release gate: the release evidence for the commit must exist and be green.

    python3 scripts/adaptation/release_gate.py --version 0.4.69 [--commit <sha>]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence/release"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", default=None)
    parser.add_argument("--require-appgallery", action="store_true")
    args = parser.parse_args()
    commit = args.commit or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    path = EVIDENCE / f"{args.version}-{commit}.json"
    if not path.is_file():
        print(f"FAIL release evidence missing for {args.version} @ {commit[:12]} ({path.relative_to(ROOT)})",
              file=sys.stderr)
        return 1
    evidence = json.loads(path.read_text())
    failures = []
    if not evidence.get("ok"):
        failures.append("release evidence is not green")
    if evidence.get("commit") != commit:
        failures.append(f"evidence commit {evidence.get('commit')} != {commit}")
    for check in evidence.get("checks", []):
        if not check.get("passed"):
            failures.append("failed check: " + check.get("command", "?"))
    rsi = evidence.get("rsiScoreboard")
    if rsi:
        scoreboard = ROOT / rsi["path"]
        if not scoreboard.is_file():
            failures.append("RSI scoreboard missing: " + rsi["path"])
        else:
            import hashlib
            if hashlib.sha256(scoreboard.read_bytes()).hexdigest() != rsi["sha256"]:
                failures.append("RSI scoreboard hash drifted: " + rsi["path"])
    artifacts = evidence.get("artifacts", {})
    required = {"store", "self"}
    if args.require_appgallery:
        required.add("appgallery")
    for label in sorted(required - artifacts.keys()):
        failures.append(f"missing {label} artifact evidence")
    for label, artifact in artifacts.items():
        maximum = artifact.get("maxBytes")
        if maximum and artifact.get("bytes", 0) > maximum:
            failures.append(f"{label} HAP {artifact['bytes']} > budget {maximum}")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    sizes = ", ".join(f"{label} {artifact['bytes']:,} B" for label, artifact in artifacts.items())
    print(f"G4 release gate OK: {evidence['version']} @ {commit[:12]} ({sizes})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
