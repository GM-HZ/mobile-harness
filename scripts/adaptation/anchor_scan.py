#!/usr/bin/env python3
"""Extract every host/compat runtime patch anchor into one searchable index.

`gates/run.py --tier G1` runs this in `--check` mode: adding a `replacePinned`
call without a matching anchors.full.json entry (or changing a literal anchor)
fails the gate. `--layer` additionally verifies every literal anchor against an
assembled dsh-layer.zip so a build/bump cannot silently lose an anchor.

    python3 scripts/adaptation/anchor_scan.py            # write index
    python3 scripts/adaptation/anchor_scan.py --check
    python3 scripts/adaptation/anchor_scan.py --layer <dsh-layer.zip>
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = [
    "packages/dsh-host/dsh-native-web.cjs",
    "packages/dsh-host/dsh-client.cjs",
    "runtime/harmonyos/compat/dsh-harmony-liveshare.cjs",
    "runtime/harmonyos/compat/dsh-harmony-forge.cjs",
]
OUTPUT = ROOT / "adaptation/anchors.full.json"
CANDIDATE_LAYERS = [
    ROOT / ".build/stage/harmonyos/entry/src/main/resources/rawfile/dsh-layer.zip",
    ROOT.parent / "harmonyos-capability-parity/.build/stage/harmonyos/entry/src/main/resources/rawfile/dsh-layer.zip",
]
CALL = re.compile(r"replacePinned\(")
FUNCTION = re.compile(r"function\s+([A-Za-z0-9_$]+)\s*\(")
MODULE = re.compile(r"paths\('([^']+)'\)|path\.join\(dsh,\s*'([^']+)'\)|path\.join\(dsh,\s*\"([^\"]+)\"\)")


def split_args(text, start):
    """Split call arguments starting after '(' up to the matching ')'."""
    args, depth, quote, current = [], 0, None, ""
    i = start
    while i < len(text):
        char = text[i]
        if quote:
            current += char
            if char == "\\":
                i += 1
                if i < len(text):
                    current += text[i]
            elif char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
            current += char
        elif char in "([{":
            depth += 1
            current += char
        elif char in ")]}":
            if depth == 0:
                args.append(current.strip())
                return args
            depth -= 1
            current += char
        elif char == "," and depth == 0:
            args.append(current.strip())
            current = ""
        else:
            current += char
        i += 1
    return args


def literal(argument):
    """Return the decoded body of a quoted literal argument, else None."""
    match = re.fullmatch(r"'(.*)'|\"(.*)\"", argument, re.S)
    if not match:
        return None
    body = match.group(1) if match.group(1) is not None else match.group(2)
    return body.encode("utf-8").decode("unicode_escape") if "\\" in body else body


VARIABLE = re.compile(r"const\s+([A-Za-z0-9_$]+)\s*=\s*paths\('([^']+)'\)")
BRANCH = re.compile(r"url\s*===\s*([A-Za-z0-9_$]+)")


def variable_modules(text):
    return {match.group(1): match.group(2) for match in VARIABLE.finditer(text)}


def function_modules(text):
    """Map a patch function name to the module name of the load-hook branch calling it."""
    variables = variable_modules(text)
    mapping = {}
    for match in FUNCTION.finditer(text):
        name = match.group(1)
        for call in re.finditer(r"\b" + re.escape(name) + r"\s*\(", text):
            if call.start() == match.end() - 1:
                continue
            window = text[max(0, call.start() - 9000):call.start()]
            branches = list(BRANCH.finditer(window))
            if not branches:
                continue
            variable = branches[-1].group(1)
            if variable in variables:
                mapping.setdefault(name, variables[variable])
                break
    return mapping


def branch_records(text):
    """Collect `url === X` branches, skipping strings/comments so literals cannot fake depth."""
    variables = variable_modules(text)
    depth = 0
    records = []
    i = 0
    quote = None
    while i < len(text):
        char = text[i]
        if quote:
            if char == "\\":
                i += 1
            elif char == quote:
                quote = None
            i += 1
            continue
        if char in "'\"`":
            quote = char
            i += 1
            continue
        if text.startswith("//", i):
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif text.startswith("url", i):
            match = BRANCH.match(text, i)
            if match and match.group(1) in variables:
                records.append({"position": i, "depth": depth, "module": variables[match.group(1)]})
        i += 1
    return records


def depth_at(text, position):
    depth = 0
    i = 0
    quote = None
    while i < min(position, len(text)):
        char = text[i]
        if quote:
            if char == "\\":
                i += 1
            elif char == quote:
                quote = None
            i += 1
            continue
        if char in "'\"`":
            quote = char
            i += 1
            continue
        if text.startswith("//", i):
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        i += 1
    return depth


def branch_module(text, position):
    records = branch_records(text)
    depth = depth_at(text, position)
    best = None
    for record in records:
        if record["position"] < position and record["depth"] < depth:
            best = record
    return best["module"] if best else None


def function_hint(text, position):
    matches = list(FUNCTION.finditer(text, 0, position))
    return matches[-1].group(1) if matches else None


def scan():
    entries = []
    for relative in FILES:
        path = ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text()
        modules = function_modules(text)
        for index, match in enumerate(CALL.finditer(text)):
            args = split_args(text, match.end())
            if len(args) < 2:
                continue
            anchor = literal(args[1])
            dynamic = anchor is None
            function = function_hint(text, match.start())
            entries.append({
                "file": relative,
                "index": index,
                "function": function,
                "module": (branch_module(text, match.start()) if function in (None, "main")
                           else (modules.get(function) or branch_module(text, match.start()))),
                "anchor": anchor if anchor is not None else args[1][:120],
                "dynamic": dynamic,
            })
    return entries


def locate_layer(explicit):
    if explicit:
        return Path(explicit)
    for candidate in CANDIDATE_LAYERS:
        if candidate.is_file():
            return candidate
    return None


def layer_js_files(layer):
    with zipfile.ZipFile(layer) as archive:
        for info in archive.infolist():
            name = info.filename
            if name.startswith("dsh/node_modules/") and name.endswith((".js", ".mjs", ".cjs")):
                yield archive.read(name).decode("utf-8", "replace"), name


def map_layer(entries, layer):
    """No static mapping guess: find each literal anchor in the assembled layer."""
    literals = [entry for entry in entries if not entry["dynamic"] and entry["anchor"]]
    state = {id(entry): {"count": 0, "files": []} for entry in literals}
    for text, name in layer_js_files(layer):
        for entry in literals:
            count = text.count(entry["anchor"])
            if count:
                row = state[id(entry)]
                row["count"] += count
                if len(row["files"]) < 3:
                    row["files"].append(name)
    mapped = ambiguous = missing = 0
    for entry in literals:
        row = state[id(entry)]
        if row["count"] == 1:
            entry["layerModule"] = row["files"][0]
            entry["layerCount"] = 1
            mapped += 1
        elif row["count"] > 1:
            entry["layerModule"] = row["files"][0]
            entry["layerCount"] = row["count"]
            entry["layerFiles"] = row["files"]
            entry["layerAmbiguous"] = True
            ambiguous += 1
        else:
            missing += 1
    return {"mapped": mapped, "ambiguous": ambiguous, "missing": missing}


def verify_layer(entries, layer):
    missing = []
    checked = 0
    with zipfile.ZipFile(layer) as archive:
        names = set(archive.namelist())
        for entry in entries:
            if entry["dynamic"] or not entry["anchor"]:
                continue
            if entry.get("layerModule"):
                checked += 1
                if entry.get("layerAmbiguous"):
                    good = any(archive.read(name).decode("utf-8", "replace").count(entry["anchor"]) >= 1
                               for name in entry.get("layerFiles", [entry["layerModule"]]))
                    if not good:
                        missing.append({**entry, "reason": "ambiguous anchor missing from all candidate files"})
                    continue
                payload = archive.read(entry["layerModule"]).decode("utf-8", "replace")
                if payload.count(entry["anchor"]) != 1:
                    missing.append({**entry, "reason": f"layer anchor count {payload.count(entry['anchor'])} != 1"})
                continue
            if not entry["module"]:
                continue
            candidates = [f"dsh/node_modules/@deepseek-ai/{entry['module']}"]
            # paths() values are dsh-<pkg>/lib/... without @deepseek-ai prefix
            candidates = [name for name in candidates if name in names]
            if not candidates:
                missing.append({**entry, "reason": "module not found in layer"})
                continue
            checked += 1
            payload = archive.read(candidates[0]).decode("utf-8", "replace")
            if payload.count(entry["anchor"]) != 1:
                missing.append({**entry, "reason": f"anchor count {payload.count(entry['anchor'])} != 1",
                                "moduleFile": candidates[0]})
    return checked, missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--layer")
    parser.add_argument("--map", action="store_true", help="map layerModule for every literal anchor")
    args = parser.parse_args()
    entries = scan()
    data = {"schema": 1, "source": "scripts/adaptation/anchor_scan.py", "entries": entries}
    if args.check:
        current = json.loads(OUTPUT.read_text()) if OUTPUT.is_file() else None
        def static(entries):
            return [{key: value for key, value in entry.items()
                     if key not in ("layerModule", "layerFiles", "layerCount", "layerAmbiguous")}
                    for entry in entries]
        current_static = (static(current.get("entries", [])) if current else None)
        data_static = static(entries)
        if current_static != data_static:
            print("anchors.full.json is stale; run scripts/adaptation/anchor_scan.py", file=sys.stderr)
            return 1
        literal_count = sum(1 for entry in entries if not entry["dynamic"])
        print(f"G1 anchor coverage OK: {len(entries)} anchors ({literal_count} literal, "
              f"{len(entries) - literal_count} dynamic) in {len(FILES)} files")
        return 0
    if args.map:
        layer = locate_layer(args.layer)
        if not layer:
            print("SKIP anchor mapping: dsh-layer.zip not available", file=sys.stderr)
            return 2
        stats = map_layer(entries, layer)
        data = {"schema": 1, "source": "scripts/adaptation/anchor_scan.py",
                "layer": layer.name, "stats": stats, "entries": entries}
        OUTPUT.write_text(json.dumps(data, indent=2) + "\n")
        print(f"anchor mapping: {stats['mapped']} mapped, {stats['ambiguous']} ambiguous, "
              f"{stats['missing']} missing (layer {layer.name})")
        return 0 if stats["missing"] == 0 and stats["ambiguous"] == 0 else 1
    if args.layer:
        layer = locate_layer(args.layer)
        if not layer:
            print("SKIP anchor layer verification: dsh-layer.zip not available", file=sys.stderr)
            return 2
        if OUTPUT.is_file():
            entries = json.loads(OUTPUT.read_text()).get("entries", entries)
        checked, missing = verify_layer(entries, layer)
        print(f"anchor layer scan: {checked} module anchors checked, {len(missing)} missing")
        for row in missing[:20]:
            print(f"  MISSING {row['file']}#{row['index']} {row['function']}: {row['reason']}")
        return 0 if not missing else 1
    OUTPUT.write_text(json.dumps(data, indent=2) + "\n")
    literal_count = sum(1 for entry in entries if not entry["dynamic"])
    print(f"anchors.full.json: {len(entries)} anchors ({literal_count} literal)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
