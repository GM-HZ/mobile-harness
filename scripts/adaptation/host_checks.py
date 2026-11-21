#!/usr/bin/env python3
"""G1: syntax-check the host/compat overlay scripts that are injected at boot."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GLOBS = ["packages/dsh-host/*.cjs", "packages/dsh-host/*.mjs",
         "runtime/harmonyos/compat/*.cjs", "runtime/harmonyos/compat/*.mjs", "runtime/harmonyos/compat/*.js"]


def main():
    files = sorted({path for pattern in GLOBS for path in ROOT.glob(pattern)})
    failures = []
    for path in files:
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            failures.append(f"{path.relative_to(ROOT)}: {result.stderr.strip().splitlines()[:2]}")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print(f"G1 host syntax OK: {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
