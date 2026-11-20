#!/usr/bin/env python3
"""Upstream DSH bump rehearsal (dry run).

Fetches the watched @deepseek-ai packages for a target release from the npm
registry, re-checks every literal anchor in adaptation/anchors.json against the
new package tarballs and reports which adaptation surfaces are affected. It
never modifies the working tree; the point is to know before bumping whether a
new DSH release breaks our runtime hooks.

    python3 scripts/adaptation/bump.py               # latest available vs pinned
    python3 scripts/adaptation/bump.py --to 0.2.3-rc.1
    python3 scripts/adaptation/bump.py --no-download # metadata only

Exit: 0 all anchors intact, 1 anchor drift, 2 registry unavailable.
"""
import argparse
import json
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANCHORS = ROOT / "adaptation/anchors.json"
LOCK = ROOT / "runtime/harmonyos/dsh/package-lock.json"
WATCH = [
    "@deepseek-ai/dsh",
    "@deepseek-ai/dsh-bash-local",
    "@deepseek-ai/dsh-bash-sandbox",
    "@deepseek-ai/dsh-session-persistence-jsonl",
    "@deepseek-ai/dsh-client-ui-settings-general",
]
CACHE = ROOT / ".build/upstream-bump"
EVIDENCE = ROOT / "docs/evidence/upstream-bump"


def npm(path):
    url = "https://registry.npmjs.org/" + path
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def metadata(package):
    return npm(package.replace("/", "%2F"))


def version_meta(package, version):
    return npm(package.replace("/", "%2F") + "/" + version)


def acquire(package, version):
    directory = CACHE / version
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (package.replace("/", "__") + ".tgz")
    if not target.is_file():
        meta = version_meta(package, version)
        tarball = meta["dist"]["tarball"]
        with urllib.request.urlopen(tarball, timeout=180) as response:
            target.write_bytes(response.read())
    return target


def package_versions(package):
    try:
        return set(metadata(package).get("versions", {}))
    except Exception:
        return set()


def layer_to_tarball(path):
    """dsh/node_modules/@deepseek-ai/<pkg>/<rest> -> (<pkg>, package/<rest>)."""
    prefix = "dsh/node_modules/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):]
    if rest.startswith("@deepseek-ai/"):
        parts = rest.split("/", 2)
        if len(parts) < 3:
            return None
        return "@deepseek-ai/" + parts[1], "package/" + parts[2]
    return None


def package_locks():
    lock = json.loads(LOCK.read_text())
    versions = {}
    for key, value in lock.get("packages", {}).items():
        if key.startswith("node_modules/@deepseek-ai/") and value.get("version"):
            versions[key[len("node_modules/"):]] = value["version"]
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", help="target DSH release (default: latest npm dist-tag)")
    parser.add_argument("--no-download", action="store_true", help="only inspect registry metadata")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    pinned = package_locks().get("@deepseek-ai/dsh")
    try:
        dsh = metadata("@deepseek-ai/dsh")
    except (urllib.error.URLError, OSError) as error:
        print("SKIP upstream bump: npm registry unavailable: " + str(error)[:160], file=sys.stderr)
        return 2
    available = sorted(dsh.get("versions", {}))
    target = args.to or dsh.get("dist-tags", {}).get("latest") or pinned
    if target not in available:
        print(f"target {target} not published; available tail: {available[-5:]}", file=sys.stderr)
        return 2
    newer = available.index(target) > available.index(pinned) if pinned in available else None
    locks = package_locks()
    anchors = json.loads(ANCHORS.read_text())["anchors"]
    report = {"pinned": pinned, "target": target, "newerThanPinned": newer,
              "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "packages": {}, "anchors": [], "affected": []}
    failures = 0
    if args.no_download:
        for package in WATCH:
            try:
                meta = metadata(package)
                versions = meta.get("versions", {})
                report["packages"][package] = {"locked": locks.get(package), "targetAvailable": target in versions}
            except Exception as error:
                report["packages"][package] = {"error": str(error)[:120]}
    else:
        # Pattern anchors follow the DSH release line; existence anchors (native
        # platform addons) follow their own locked version.
        pattern_packages = sorted({layer_to_tarball(anchor["file"])[0]
                                   for anchor in anchors
                                   if not anchor.get("exists") and layer_to_tarball(anchor["file"])})
        existence_packages = sorted({layer_to_tarball(anchor["file"])[0]
                                     for anchor in anchors
                                     if anchor.get("exists") and layer_to_tarball(anchor["file"])})
        for package in pattern_packages:
            versions = package_versions(package)
            if target not in versions:
                report["packages"][package] = {"locked": locks.get(package), "targetAvailable": False,
                                               "availableTail": sorted(versions)[-4:]}
                continue
            try:
                path = acquire(package, target)
                report["packages"][package] = {"locked": locks.get(package), "version": target,
                                               "tarball": path.name, "bytes": path.stat().st_size}
            except Exception as error:
                report["packages"][package] = {"error": str(error)[:120]}
        for package in existence_packages:
            locked = locks.get(package)
            versions = package_versions(package)
            version = locked if locked in versions else (sorted(versions)[-1] if versions else None)
            report["packages"][package] = {"locked": locked, "version": version}
            if version:
                try:
                    path = acquire(package, version)
                    report["packages"][package].update({"tarball": path.name, "bytes": path.stat().st_size})
                except Exception as error:
                    report["packages"][package]["error"] = str(error)[:120]
        for anchor in anchors:
            mapping = layer_to_tarball(anchor["file"])
            if not mapping:
                report["anchors"].append({"id": anchor["id"], "skipped": "not an @deepseek-ai package file"})
                continue
            package, member = mapping
            info = report["packages"].get(package) or {}
            version = info.get("version") or (locks.get(package) if anchor.get("exists") else target)
            row = {"id": anchor["id"], "package": package, "member": member, "version": version}
            path = CACHE / version / (package.replace("/", "__") + ".tgz") if version else None
            if not path or not path.is_file():
                row.update({"ok": False, "error": "package tarball unavailable"})
                failures += 1
                report["anchors"].append(row)
                continue
            try:
                with tarfile.open(path, ignore_zeros=True) as tarball:
                    payload = tarball.extractfile(member).read()
                if anchor.get("exists"):
                    row.update({"ok": True, "kind": "exists"})
                else:
                    actual = payload.decode("utf-8", "replace").count(anchor["pattern"])
                    row.update({"ok": actual == anchor["count"], "expected": anchor["count"], "actual": actual})
                    if not row["ok"]:
                        failures += 1
            except Exception as error:
                row.update({"ok": False, "error": str(error)[:160]})
                failures += 1
            report["anchors"].append(row)
    touched = {anchor["package"] for anchor in report["anchors"] if anchor.get("package")}
    manifest = json.loads((ROOT / "adaptation/manifest.json").read_text())
    for entry in manifest["entries"]:
        if set(entry.get("upstreamTouchpoints", [])) & touched:
            report["affected"].append(entry["id"])
    report["failures"] = failures
    report["ok"] = failures == 0
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    output = args.json or EVIDENCE / (target + "-dry-run.json")
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"upstream bump rehearsal: pinned {pinned} -> target {target} "
          f"({'newer' if newer else 'same/older' if newer is not None else 'unknown'})")
    for row in report["anchors"]:
        if row.get("skipped"):
            print(f"  SKIP {row['id']} ({row['skipped']})")
        elif row.get("ok"):
            print(f"  OK   {row['id']}")
        else:
            print(f"  DRIFT {row['id']}: expected {row.get('expected')}, found {row.get('actual')} ({row.get('error', '')})")
    print(f"affected adaptation entries: {len(report['affected'])}")
    print(f"evidence: {output.relative_to(ROOT)}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
