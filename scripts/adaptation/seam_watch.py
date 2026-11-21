#!/usr/bin/env python3
"""Watch upstream packages for extension seams relevant to our compat layer.

Fetches the pinned release of the packages behind our compat modules and reports
where they expose provider/plugin seams we could migrate to (evidence for the
`upstream-seam-candidate` decisions in adaptation/compat.json).

    python3 scripts/adaptation/seam_watch.py [--version 0.2.2-rc.5]
"""
import argparse
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".build/upstream-seams"
EVIDENCE = ROOT / "docs/evidence/upstream-seams"
WATCH = {
    "forge": ["@deepseek-ai/dsh-experimental-forge", "@deepseek-ai/dsh-experimental-forge-bundle",
              "@deepseek-ai/dsh-experimental-forge-github", "@deepseek-ai/dsh-experimental-forge-session",
              "@deepseek-ai/dsh-experimental-client-ui-forge"],
    "liveshare": ["@deepseek-ai/dsh-experimental-liveshare", "@deepseek-ai/dsh-experimental-liveshare-protocol"],
    "speech": ["@deepseek-ai/dsh-experimental-speech-to-text-sensevoice",
               "@deepseek-ai/dsh-experimental-voice-input-bundle"],
    "office": ["@deepseek-ai/dsh-office-kit", "@deepseek-ai/dsh-tool-office", "@deepseek-ai/dsh-skill-office"],
    "image": ["@deepseek-ai/dsh-compaction-image-offload"],
}
KEYWORDS = ("provider", "registerProvider", "defineProvider", "ctx.set(", "Service", "bundle", "client")


def npm_meta(package, version):
    url = "https://registry.npmjs.org/" + package.replace("/", "%2F") + "/" + version
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def fetch(package, version):
    directory = CACHE / version
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (package.replace("/", "__") + ".tgz")
    if not target.is_file():
        last = None
        for attempt in range(3):
            try:
                meta = npm_meta(package, version)
                with urllib.request.urlopen(meta["dist"]["tarball"], timeout=180) as response:
                    target.write_bytes(response.read())
                last = None
                break
            except Exception as error:
                last = error
        if last is not None:
            raise last
    return target


def inspect(archive):
    hits = {}
    files = 0
    with tarfile.open(archive) as package:
        names = package.getnames()
        for name in names:
            if not name.endswith((".js", ".mjs", ".cjs", ".d.ts")):
                continue
            try:
                text = package.extractfile(name).read().decode("utf-8", "replace")
            except (KeyError, AttributeError):
                continue
            files += 1
            for keyword in KEYWORDS:
                count = text.count(keyword)
                if count:
                    hits[keyword] = hits.get(keyword, 0) + count
    return {"files": files, "hits": dict(sorted(hits.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.2.2-rc.5")
    args = parser.parse_args()
    report = {"version": args.version, "packages": {}, "candidates": []}
    for area, packages in WATCH.items():
        for package in packages:
            try:
                archive = fetch(package, args.version)
            except Exception as error:
                report["packages"][package] = {"error": str(error)[:160]}
                continue
            info = inspect(archive)
            info["area"] = area
            report["packages"][package] = info
            if info["hits"].get("provider") or info["hits"].get("registerProvider") or info["hits"].get("ctx.set("):
                report["candidates"].append(package)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    output = EVIDENCE / (args.version + ".json")
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"upstream seam watch: {len(report['packages'])} packages, {len(report['candidates'])} candidates")
    for package, info in report["packages"].items():
        if "error" in info:
            print(f"  SKIP {package}: {info['error'][:80]}")
        else:
            print(f"  {package}: {info['files']} files, provider={info['hits'].get('provider', 0)} "
                  f"ctx.set={info['hits'].get('ctx.set(', 0)} client={info['hits'].get('client', 0)}")
    print(f"evidence: {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
