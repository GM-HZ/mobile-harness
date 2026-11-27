#!/usr/bin/env python3
"""G4: collect release evidence for the variants in scope.

Runs the store shape check and the variant assertions, records artifact hashes and
sizes, writes docs/evidence/release/<version>-<commit>.json and appends the run to
the RSI ledger.

    python3 scripts/adaptation/release_evidence.py --store .build/store.hap --self .build/self.hap
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from pathlib import Path
from zipfile import BadZipFile, ZipFile

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


def store_version_check(package, version):
    profile = json.loads((ROOT / "apps/harmonyos/AppScope/app.json5").read_text())["app"]
    expected = {key: profile[key] for key in ("bundleName", "versionName", "versionCode")}
    try:
        with ZipFile(package) as archive:
            packaged = json.loads(archive.read("module.json"))["app"]
        actual = {key: packaged.get(key) for key in expected}
        passed = actual == expected and version == expected["versionName"]
        output = f"{actual}, expected {expected} for release {version}"
    except (BadZipFile, OSError, ValueError, KeyError) as error:
        passed = False
        output = str(error)
    return {"command": "Store package release metadata", "exit": int(not passed),
            "passed": passed, "output": output}


def appgallery_check(package):
    with TemporaryDirectory() as directory, ZipFile(package) as archive:
        entries = [entry for entry in archive.infolist() if entry.filename.endswith(".hap")]
        if len(entries) != 1:
            raise ValueError(f"Expected one HAP in {package}, found {len(entries)}")
        hap = Path(directory) / "appgallery.hap"
        with archive.open(entries[0]) as source, hap.open("wb") as output:
            shutil.copyfileobj(source, output)
        result = run_check(["scripts/adaptation/variant_check.py", "--variant", "appgallery", "--hap", str(hap)])
    result["command"] = "AppGallery variant check on " + package.name
    return result


def archive_scoreboard(staging):
    report = staging / "scoreboard.md"
    result = subprocess.run(["python3", "scripts/adaptation/gate_report.py", "--output", str(report)],
                            cwd=ROOT, capture_output=True)
    if result.returncode != 0:
        return None

    content = report.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    snapshot = EVIDENCE / f"rsi-{digest}.md"
    pending_snapshot = staging / snapshot.name
    pending_snapshot.write_bytes(content)
    pending_snapshot.replace(snapshot)

    scoreboard = ROOT / "docs/evidence/rsi/scoreboard.md"
    scoreboard.parent.mkdir(parents=True, exist_ok=True)
    report.replace(scoreboard)
    return {"path": str(snapshot.relative_to(ROOT)), "sha256": digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--self", dest="self_hap", type=Path)
    parser.add_argument("--appgallery", type=Path)
    parser.add_argument("--store-only", action="store_true")
    parser.add_argument("--version", default=None)
    parser.add_argument("--require-self-build-metadata", action="store_true")
    args = parser.parse_args()
    if args.store_only and (args.self_hap or args.appgallery):
        parser.error("--store-only accepts only --store")
    if not args.store_only and args.self_hap is None:
        parser.error("--self is required for a multi-variant release")
    inputs = {"store": args.store}
    if args.self_hap:
        inputs["self"] = args.self_hap
    if args.appgallery:
        inputs["appgallery"] = args.appgallery
    for label, path in inputs.items():
        if not path.is_file():
            print(f"FAIL missing {label} HAP: {path}", file=sys.stderr)
            return 2
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    version = args.version
    if not version:
        match = re.search(r"-v(\d+\.\d+\.\d+)-", args.store.name)
        version = match.group(1) if match else "unknown"
    variants = {name: json.loads((ROOT / f"variants/{name}.json").read_text()) for name in inputs}
    metadata_check = ["--require-self-build-metadata"] if args.require_self_build_metadata or args.store_only else []
    checks = [
        run_check(["scripts/adaptation/store_build_check.py", "--hap", str(args.store)]),
        run_check(["scripts/adaptation/variant_check.py", "--variant", "store", "--hap", str(args.store),
                   *metadata_check]),
    ]
    if args.store_only:
        checks.append(store_version_check(args.store, version))
    else:
        checks.append(run_check(["scripts/adaptation/variant_check.py", "--variant", "self", "--hap",
                                 str(args.self_hap), *metadata_check]))
    if args.appgallery:
        try:
            checks.append(appgallery_check(args.appgallery))
        except (BadZipFile, ValueError, OSError) as error:
            checks.append({"command": "AppGallery variant check", "exit": 1, "passed": False,
                           "output": str(error)})
    artifacts = {}
    for label, path in inputs.items():
        artifacts[label] = {"file": path.name, "sha256": sha256(path), "bytes": path.stat().st_size,
                            "maxBytes": variants[label]["hap"].get("maxBytes")}
    ok = all(check["passed"] for check in checks) and all(
        artifact["maxBytes"] is None or artifact["bytes"] <= artifact["maxBytes"]
        for artifact in artifacts.values()
    )
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    output = EVIDENCE / f"{version}-{commit}.json"
    with TemporaryDirectory(dir=EVIDENCE) as directory:
        staging = Path(directory)
        rsi = archive_scoreboard(staging)
        evidence = {"version": version, "commit": commit, "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "artifacts": artifacts, "checks": checks, "rsiScoreboard": rsi, "ok": ok}
        if args.store_only:
            evidence["scope"] = "store-only"
        pending_evidence = staging / output.name
        pending_evidence.write_text(json.dumps(evidence, indent=2) + "\n")
        pending_evidence.replace(output)
    subprocess.run(["python3", "scripts/adaptation/rsi_ledger.py", "record", "--tiers", "G4",
                    "--evidence", str(output.relative_to(ROOT))] + (["--ok"] if ok else []),
                   cwd=ROOT, check=False)
    print(f"release evidence: {output.relative_to(ROOT)}")
    print(f"  store: {artifacts['store']['bytes']:,} B (max {artifacts['store']['maxBytes']:,})")
    if "self" in artifacts:
        print(f"  self:  {artifacts['self']['bytes']:,} B (max {artifacts['self']['maxBytes']:,})")
    for check in checks:
        print(f"  {'OK  ' if check['passed'] else 'FAIL'} {check['command']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
