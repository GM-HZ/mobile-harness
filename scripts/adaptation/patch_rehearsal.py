#!/usr/bin/env python3
"""G1: rehearse patches/series.json against the pinned npm tarballs.

For every patch: extract the package tarball (cached by scripts/adaptation/bump.py),
apply the patch with `patch -p1`, assert the series marker appears, the boot-time
anchor is gone, and the patched module still passes `node --check`.

    python3 scripts/adaptation/patch_rehearsal.py [--keep]

Exit: 0 all patches apply cleanly, 1 rehearsal failure, 2 tarball cache missing.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIES = ROOT / "patches/series.json"
CACHE = ROOT / ".build/upstream-bump"


def version():
    lock = json.loads((ROOT / "runtime/harmonyos/dsh/package-lock.json").read_text())
    return lock["packages"]["node_modules/@deepseek-ai/dsh"]["version"]


def tarball(package, release):
    return CACHE / release / (package.replace("/", "__") + ".tgz")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    release = version()
    series = json.loads(SERIES.read_text())["patches"]
    failures = []
    checked = []
    workspace = Path(tempfile.mkdtemp(prefix="patch-rehearsal-"))
    try:
        for entry in series:
            archive = tarball(entry["package"], release)
            if not archive.is_file():
                print(f"SKIP patch rehearsal: missing {archive.relative_to(ROOT)} "
                      f"(run scripts/adaptation/bump.py)", file=sys.stderr)
                return 2
            target_root = workspace / entry["package"]
            target_root.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive) as package:
                for member in package.getmembers():
                    if member.name.startswith("package/"):
                        member.name = member.name[len("package/"):]
                        package.extract(member, target_root, filter="data")
            result = subprocess.run(["patch", "-p1", "--forward", "--batch", "-s",
                                     "-i", str(ROOT / "patches" / entry["file"])],
                                    cwd=workspace, capture_output=True, text=True)
            target = workspace / entry["package"] / entry["path"]
            text = target.read_text() if target.is_file() else ""
            ok = result.returncode == 0 and entry["marker"] in text
            if entry.get("removed"):
                ok = ok and entry["removed"] not in text
            syntax = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
            ok = ok and syntax.returncode == 0
            checked.append({"file": entry["file"], "package": entry["package"], "ok": ok})
            if not ok:
                failures.append(f"{entry['file']}: apply={result.returncode} marker={entry['marker'] in text} "
                                f"removedStillPresent={bool(entry.get('removed') and entry['removed'] in text)} "
                                f"syntax={syntax.returncode} {result.stderr.strip()[:300]}")
    finally:
        if not args.keep:
            shutil.rmtree(workspace, ignore_errors=True)
        else:
            print("rehearsal workspace:", workspace)
    print(f"patch rehearsal: {len(checked)} patch(es), release {release}")
    for row in checked:
        print(f"  {'OK  ' if row['ok'] else 'FAIL'} {row['file']} ({row['package']})")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
