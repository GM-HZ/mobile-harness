#!/usr/bin/env python3
"""G1: guard the real-device regressions fixed on 2026-11-21.

These are host/test invariants that are cheap to check and expensive to
rediscover on hardware:

1. `/bin/bash` (patched bash argv) must route through the packaged PRoot spawn
   path, like `bash`; otherwise signed real-device builds hit PRoot's
   signed-exec loader handoff ("embedded loader descriptors").
2. The bash exit-status cell is ASCII digits + binary padding; the parser must
   extract digits instead of requiring exactly three digits.
3. Each probe determines success from its own `*_DONE` marker, not the exec
   probe's markers.
4. device_lab requires the probe's `ok:true`, not only exit code 0.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "packages/dsh-host/dsh-native-web.cjs"
PROBE = ROOT / "tests/smoke/mate60-proot-exec.py"
DEVICE_LAB = ROOT / "scripts/adaptation/device_lab.py"


def main():
    host = HOST.read_text()
    probe = PROBE.read_text()
    device_lab = DEVICE_LAB.read_text()
    failures = []
    if "program === 'bash' || program === '/bin/bash'" not in host:
        failures.append("host spawn no longer routes /bin/bash through the packaged path")
    if "program !== 'bash' && program !== '/bin/bash'" not in host:
        failures.append("__harmonyProotSpawn no longer accepts /bin/bash")
    if "replace(/\\D/g, '')" not in host:
        failures.append("bash status parser no longer extracts digits from padded status")
    if "^\\d{3}$" in host:
        failures.append("bash status parser regressed to requiring three digits")
    if "proxyEnv" not in host or "'HTTPS_PROXY'" not in host:
        failures.append("guest gh runner no longer forwards proxy environment variables")
    if "expected_done in text" not in probe:
        failures.append("probe success no longer uses its own *_DONE marker")
    if "probe.get(\"ok\", True) is not False" not in device_lab:
        failures.append("device_lab no longer requires the probe's ok:true")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print("G1 host regressions OK: bash routing, padded status, probe/done and ok checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
