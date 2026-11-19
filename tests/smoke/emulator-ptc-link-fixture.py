"""Record the platform link restrictions that gate PTC boundary fixtures.

The PTC file proxy resolves every path from a pre-opened root descriptor with
RESOLVE_NO_SYMLINKS and refuses multi-link writes. The remaining stress cases
need a symbolic or hard link inside the authorized root. This probe records
whether the HarmonyOS app data view can create such a link at all, so the
boundary item can either run the end-to-end fixture or be recorded as a
platform limitation with reproducible bytes.
"""
import argparse
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import uuid

support = runpy.run_path(str(Path(__file__).with_name("emulator-recovery.py")))
Emulator = support["Emulator"]
BUNDLE = support["BUNDLE"]
FILES = support["FILES"]
WORKSPACE = support["WORKSPACE"]
HDC = support["HDC"]


def attempt(device, command):
    """Run a create attempt; hdc keeps the shell status, so parse an explicit marker."""
    target = command.rsplit(" ", 1)[-1]
    wrapped = f"({command}) 2>&1; echo MH_LINK_FAIL; test -e {target} && echo MH_LINK_PRESENT"
    output = device.app(wrapped)
    return {"command": command, "output": output[:768],
            "created": "MH_LINK_FAIL" not in output or "MH_LINK_PRESENT" in output}


def probe(device, command):
    output = device.app(f"{command} 2>&1 && echo MH_TEST_YES || echo MH_TEST_NO")
    return "MH_TEST_YES" in output


def app_version(target):
    output = subprocess.check_output([HDC, "-t", target, "shell", "bm", "dump", "-n", BUNDLE],
                                     text=True, timeout=90)
    return {"versionName": re.search(r'"versionName": "([^"]+)"', output).group(1),
            "versionCode": int(re.search(r'"versionCode": (\d+)', output).group(1))}


def run(device, target):
    name = "mh-ptc-link-" + uuid.uuid4().hex[:10]
    root = "alpine/workspace-native/" + name
    outside = f"alpine/{name}-outside.txt"
    outside_abs = f"{FILES}/{outside}"
    evidence = {"target": target, "fixture": name, "app": app_version(target)}
    bridge = (f"tcp:{device.url.rsplit(':', 1)[1]}", "tcp:19592")
    if "Forwardport result:OK" not in device.hdc("fport", *bridge):
        raise SystemExit("Could not forward the loopback Web port")
    try:
        evidence["readyMs"] = device.ready("normal")
        device.app(f"rm -rf {root} {outside} && mkdir -p {root} && printf OUTSIDE > {outside} "
                   f"&& printf INSIDE > {root}/inside.txt")
        evidence["fixtureCreated"] = True

        attempts = {
            "symlinkRelative": (f"ln -s ../{name}-outside.txt {root}/link-rel", f"{root}/link-rel"),
            "symlinkAbsolute": (f"ln -s {outside_abs} {root}/link-abs", f"{root}/link-abs"),
            "hardlinkRelative": (f"ln ../{name}-outside.txt {root}/hard-rel", f"{root}/hard-rel"),
            "hardlinkAbsolute": (f"ln {outside_abs} {root}/hard-abs", f"{root}/hard-abs"),
            "symlinkDirectory": (f"ln -s {root}/sub {root}/dirlink", f"{root}/dirlink"),
        }
        device.app(f"mkdir -p {root}/sub")
        results = {}
        for key, (command, link) in attempts.items():
            record = attempt(device, command)
            record["isLink"] = probe(device, f"test -L {link}")
            results[key] = record
        evidence["appContextAttempts"] = results
        evidence["appCanSeeShellSymlink"] = probe(
            device, f"test -L /data/local/tmp/{name}-link")

        # A link created by any path would be the fixture the boundary case needs.
        evidence["links"] = {
            "symlinksInWorkspace": device.app("find alpine/workspace-native -type l | wc -l"),
            "multiLinkFilesInWorkspace": device.app("find alpine/workspace-native -type f -links +1 | head -5"),
            "fixtureHardLinks": device.app(f"stat -c '%h' {root}/inside.txt 2>/dev/null || echo unknown"),
        }
        evidence["shellContext"] = {}
        for key, command in {
            "symlink": f"ln -s /data/local/tmp/{name}-outside.txt /data/local/tmp/{name}-link",
            "hardlink": f"ln /data/local/tmp/{name}-outside.txt /data/local/tmp/{name}-hard",
        }.items():
            try:
                output = device.hdc("shell", f"printf DATA > /data/local/tmp/{name}-outside.txt; "
                                    f"{command} && echo created || echo denied")
                evidence["shellContext"][key] = output
            except subprocess.CalledProcessError as error:
                evidence["shellContext"][key] = f"error: {error.returncode}"
        created = [key for key, record in results.items() if record["created"] and record["isLink"]]
        evidence["platformLinkCreation"] = "allowed" if created else "denied"
        evidence["createdLinks"] = created
        # The end-to-end boundary fixture is only runnable when a link exists
        # inside a grantable app-data root.
        evidence["linkStressRunnable"] = bool(created)
    finally:
        try:
            device.app(f"rm -rf {root} {outside}")
            device.hdc("shell", f"rm -f /data/local/tmp/{name}-outside.txt /data/local/tmp/{name}-link "
                               f"/data/local/tmp/{name}-hard")
        finally:
            device.app(f"test ! -e {root} || echo leftover")
            device.app(f"test ! -e {outside} || echo leftover")
            device.hdc("fport", "rm", *bridge)
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--host-port", type=int, default=19661)
    args = parser.parse_args()
    output = run(Emulator(args.target, args.host_port), args.target)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(output.get("platformLinkCreation"), ensure_ascii=False))
