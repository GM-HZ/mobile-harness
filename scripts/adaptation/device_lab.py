#!/usr/bin/env python3
"""G3 device lab protocol: detect a connected phone, serialize lab access and
run a device suite with evidence.

    python3 scripts/adaptation/device_lab.py status
    python3 scripts/adaptation/device_lab.py run --suite verify
    python3 scripts/adaptation/device_lab.py run --suite exec      # needs a model turn
    python3 scripts/adaptation/device_lab.py run --suite overlay   # needs a model turn

Exit codes: 0 pass, 1 suite failed, 2 no device, 3 lab lock busy.
"""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence/device-lab"
LOCK = ROOT / ".build/device-lab.lock"
BUNDLE = "org.sayact.nodepoc"
SUITES = {
    "verify": ["tests/smoke/mate60-verify.py"],
    "exec": ["tests/smoke/mate60-proot-exec.py", "--probe", "exec"],
    "overlay": ["tests/smoke/mate60-proot-exec.py", "--probe", "native-overlay"],
}


def hdc_path():
    home = os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents")
    return str(Path(home) / "sdk/default/openharmony/toolchains/hdc")


def hdc(*args):
    result = subprocess.run([hdc_path(), *args], capture_output=True, text=True, timeout=180)
    return result.stdout.strip() + result.stderr.strip()


def detect():
    targets = [line.strip() for line in hdc("list", "targets").splitlines() if line.strip()]
    usb = [target for target in targets if not target.startswith("127.0.0.1")]
    return usb[0] if usb else None


def status(serial):
    dump = hdc("-t", serial, "shell", "bm dump -n " + BUNDLE)
    start = dump.find("{")
    build = {}
    try:
        build = json.loads(dump[start:])
    except Exception:
        pass
    boot = hdc("-t", serial, "shell", "-b", BUNDLE,
               "cd data/storage/el2/base/haps/entry/files && cat mobile-harness-boot.json")
    launch = hdc("-t", serial, "shell", "aa start -a EntryAbility -b " + BUNDLE)
    return {
        "serial": serial,
        "versionName": build.get("versionName"),
        "versionCode": build.get("versionCode"),
        "boot": boot[:300],
        "launch": launch[:300],
        "screenLocked": "screen is locked" in launch,
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def run_suite(serial, suite):
    command = ["python3", str(ROOT / SUITES[suite][0]), "--target", serial]
    if suite == "verify":
        output = EVIDENCE / "verify.json"
        command += ["--output", str(output)]
    else:
        output = EVIDENCE / (suite + ".json")
        command += ["--output", str(output)] + SUITES[suite][1:]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=1200)
    elapsed = round(time.monotonic() - started)
    probe = {}
    if output.is_file():
        try:
            payload = json.loads(output.read_text())
            if isinstance(payload, dict):
                probe = payload
        except (ValueError, OSError):
            pass
    # Probe scripts exit 0 even when they report a failed acceptance; require both.
    passed = result.returncode == 0 and probe.get("ok") is True
    return {"suite": suite, "exit": result.returncode, "passed": passed, "probeOk": probe.get("ok"),
            "durationSeconds": elapsed, "outputTail": (result.stdout + result.stderr)[-1500:],
            "evidence": str(output.relative_to(ROOT)) if output.is_file() else None,
            "requiresModel": suite in ("exec", "overlay")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    runner = sub.add_parser("run")
    runner.add_argument("--suite", choices=sorted(SUITES), required=True)
    runner.add_argument("--wait-unlock", type=int, default=0,
                        help="poll for an unlocked screen up to N seconds before running")
    args = parser.parse_args()
    serial = detect()
    if not serial:
        print("SKIP device lab: no USB device connected", file=sys.stderr)
        return 2
    device = status(serial)
    if args.command == "status":
        print(json.dumps(device, ensure_ascii=False, indent=2))
        return 0
    deadline = time.monotonic() + args.wait_unlock
    while device.get("screenLocked") and time.monotonic() < deadline:
        time.sleep(5)
        device = status(serial)
    if device.get("screenLocked"):
        print("SKIP device lab: screen is locked (unlock the phone and retry)", file=sys.stderr)
        return 4
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("SKIP device lab: another lab run holds the lock", file=sys.stderr)
        return 3
    try:
        run = run_suite(serial, args.suite)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    evidence = {"device": device, "run": run, "ok": run["passed"]}
    output = EVIDENCE / (time.strftime("%Y%m%dT%H%M%S") + "-" + args.suite + ".json")
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(f"device lab [{args.suite}] {'PASS' if run['passed'] else 'FAIL'} "
          f"({run['durationSeconds']}s) -> {output.relative_to(ROOT)}")
    if not run["passed"]:
        print(run["outputTail"][-800:], file=sys.stderr)
    return 0 if run["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
