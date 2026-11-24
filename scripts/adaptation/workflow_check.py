#!/usr/bin/env python3
"""G1: keep the gate workflows wired to the gate registry and scripts.

Checks the workflow files structurally (no PyYAML dependency) and fails when a
workflow loses a required step or references a missing script, so CI and local
gates cannot silently drift apart.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
EXPECTED = {
    "gate-pr.yml": ["gates/run.py --tier G0", "gates/run.py --tier G1"],
    "gate-nightly.yml": ["capability-parity-gate", "nightly-recovery", "nightly-native-addon"],
    "gate-device.yml": ["device_lab.py run --suite verify", "device_lab.py status"],
    "gate-release.yml": ["gates/run.py --tier G0", "gates/run.py --tier G1", "./scripts/adaptation/release_dry_run.sh"],
}
SCRIPT = re.compile(r"(?:python3\s+|\./)((?:scripts|tests)/[A-Za-z0-9_./-]+?\.(?:py|sh))")


def main():
    failures = []
    for name, needles in EXPECTED.items():
        path = WORKFLOWS / name
        if not path.is_file():
            failures.append(f"missing workflow {name}")
            continue
        text = path.read_text()
        for required in ("name:", "\non:", "jobs:"):
            if required not in text:
                failures.append(f"{name}: missing section {required.strip()}")
        for needle in needles:
            if needle not in text:
                failures.append(f"{name}: missing step reference {needle!r}")
        for script in SCRIPT.findall(text):
            if not (ROOT / script).is_file():
                failures.append(f"{name}: references missing script {script}")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print(f"G1 workflows OK: {len(EXPECTED)} gate workflows wired to scripts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
