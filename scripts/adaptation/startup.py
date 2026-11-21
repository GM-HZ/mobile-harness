#!/usr/bin/env python3
"""Measure HarmonyOS App cold/warm startup phases from device logs.

    python3 scripts/adaptation/startup.py 127.0.0.1:5555 --warm
    python3 scripts/adaptation/startup.py 127.0.0.1:5555 --cold   # removes unpack markers
    python3 scripts/adaptation/startup.py 127.0.0.1:5555 --warm --output docs/evidence/startup/warm.json

The script force-stops the App, clears hilog, starts the entry ability and
collects DSHClient phase logs plus the native timeline. It does not clean user
data; `--cold` only removes the unpack marker files under the App files dir.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HDC = "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc"
BUNDLE = "org.sayact.nodepoc"
TIME = re.compile(r"(\d\d:\d\d:\d\d\.\d+)")


def run(target, command, timeout=120):
    return subprocess.run([HDC, "-t", target, "shell", command],
                          capture_output=True, text=True, errors="replace", timeout=timeout).stdout


def app_shell(target, command, timeout=120):
    return subprocess.run([HDC, "-t", target, "shell", "-b", BUNDLE, command],
                          capture_output=True, text=True, errors="replace", timeout=timeout).stdout


def dump_logs(target, seconds=4):
    process = subprocess.Popen([HDC, "-t", target, "hilog", "-x"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors="replace")
    try:
        output, _ = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
    return [line for line in output.splitlines() if "DSHClient" in line]


def timeline(target):
    text = app_shell(target, "cd data/storage/el2/base/haps/entry/files/alpine && "
                             "cat tmp/dsh-native-timeline.log 2>/dev/null")
    rows = []
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def clear_unpack_markers(target):
    """Force the next start to extract packaged archives again."""
    app_shell(target, "cd data/storage/el2/base/haps/entry/files/alpine && "
                      "find . -maxdepth 3 -name '.validated-unpack-v2-*' -delete")


def measure(target, warm=True, timeout=300):
    if not warm:
        clear_unpack_markers(target)
    run(target, "aa force-stop " + BUNDLE)
    time.sleep(1)
    run(target, "hilog -r")
    started = time.time()
    run(target, "aa start -a EntryAbility -b " + BUNDLE)
    seen = []
    ready = False
    while time.time() - started < timeout:
        lines = dump_logs(target)
        if lines:
            seen = lines[-80:]
        text = "\n".join(seen)
        if "ArkWeb loaded" in text:
            ready = True
            break
        time.sleep(2)
    wall = round(time.time() - started, 1)
    phases = []
    for line in seen:
        message = line.split("DSHClient: ", 1)[-1]
        match = TIME.search(line)
        if any(key in message for key in ("ability foreground", "startup archive", "starting native Web",
                                          "native loopback ready", "ArkWeb loaded")):
            phases.append({"at": match.group(1) if match else None, "message": message.strip()[:200]})
    native_ms = None
    foreground = arkweb = None
    for phase in phases:
        message = phase["message"]
        match = re.search(r"native loopback ready ms=(\d+)", message)
        if match:
            native_ms = int(match.group(1))
        if "ability foreground" in message:
            foreground = phase["at"]
        if "ArkWeb loaded" in message:
            arkweb = phase["at"]
    ready_ms = None
    if foreground and arkweb:
        start_clock = time.strptime(foreground.split(".")[0], "%H:%M:%S")
        end_clock = time.strptime(arkweb.split(".")[0], "%H:%M:%S")
        start_seconds = start_clock.tm_hour * 3600 + start_clock.tm_min * 60 + start_clock.tm_sec + float("0." + foreground.split(".")[1])
        end_seconds = end_clock.tm_hour * 3600 + end_clock.tm_min * 60 + end_clock.tm_sec + float("0." + arkweb.split(".")[1])
        ready_ms = round((end_seconds - start_seconds) * 1000)
    return {
        "target": target,
        "mode": "warm" if warm else "cold",
        "ready": ready,
        "wallSeconds": wall,
        "nativeLoopbackMs": native_ms,
        "readyMs": ready_ms,
        "phases": phases,
        "timeline": timeline(target),
        "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--warm", action="store_true", help="use existing unpack markers (default)")
    group.add_argument("--cold", action="store_true", help="remove unpack markers first")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-wall", type=float, help="fail if readyMs/wallSeconds exceeds this budget")
    args = parser.parse_args()
    result = measure(args.target, warm=not args.cold, timeout=args.timeout)
    output = args.output or ROOT / "docs/evidence/startup" / (result["mode"] + "-" + time.strftime("%Y%m%dT%H%M%S") + ".json")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    measured = result["readyMs"] if result["readyMs"] is not None else int(result["wallSeconds"] * 1000)
    print(json.dumps({key: result[key] for key in ("mode", "ready", "wallSeconds", "nativeLoopbackMs", "readyMs")}, ensure_ascii=False))
    for phase in result["phases"]:
        print(" ", phase["at"], phase["message"])
    print("evidence:", output.relative_to(ROOT))
    if args.max_wall is not None and measured > args.max_wall * 1000:
        print(f"startup budget exceeded: {measured}ms > {int(args.max_wall * 1000)}ms", file=sys.stderr)
        return 1
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
