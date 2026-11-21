"""Assemble the pinned DSH npm release and verify existing native bindings."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

NATIVE_MODULES = (
    "node-addon-require-builtin-linux-arm64-musl/prebuilt/linux-arm64-musl-napi-v9.node",
    "@deepseek-ai/node-addon-system-linux-arm64/bin/musl/system.node",
    "@deepseek-ai/node-addon-system-linux-arm64/bin/landlock-run",
    "@vscode/ripgrep-linux-arm64/bin/rg",
    "@koromix/koffi-linux-arm64/musl_arm64/koffi.node",
    "@img/sharp-linuxmusl-arm64/lib/sharp-linuxmusl-arm64-0.35.5.node",
    "@img/sharp-libvips-linuxmusl-arm64/lib/libvips-cpp.so.8.18.7",
)
ARCHIVE = "dsh-layer.zip"
OPTIONAL_ARCHIVE = "dsh-layer-optional.zip"
CHUNKS = 8
MANIFEST = "dsh-chunks.json"
# Runtime does not need type declarations, source maps, test suites or prose.
# Dropping them cuts 1.08GB / 99,770 files by roughly a third and shortens the
# first-boot extraction, which dominates cold start. Set HARMONY_DSH_PRUNE=0 to
# keep the raw npm tree for debugging.
PRUNE_PATTERNS = (
    re.compile(r"\.map$"),
    re.compile(r"\.d\.ts$"),
    re.compile(r"/(?:test|tests|__tests__|spec)/"),
)
# Heavy payloads that are only imported when their feature is used. They stay
# in the HAP but are extracted as a second archive in parallel with the core
# layer, keeping first-boot wall time close to the core layer.
OPTIONAL_PATTERNS = (
    re.compile(r"libreoffice-kit-wasm/"),
    re.compile(r"node_modules/sherpa-onnx/"),
    re.compile(r"dsh-experimental-client-ui-forge/"),
    re.compile(r"dsh-experimental-liveshare/"),
    re.compile(r"dsh-client-ui-sidebar-documentpreview/"),
    re.compile(r"node_modules/@img/sharp"),
    re.compile(r"node_modules/@google/genai/"),
    re.compile(r"node_modules/@anthropic-ai/"),
)


def pruned(name: str) -> bool:
    if os.environ.get("HARMONY_DSH_PRUNE") == "0":
        return False
    return any(pattern.search(name) for pattern in PRUNE_PATTERNS)


def chunk_index(name: str) -> int:
    """Group every file of a package into one chunk so upgrades replace whole packages."""
    parts = name.split("/")
    if len(parts) >= 4 and parts[0] == "dsh" and parts[1] == "node_modules":
        key = "/".join(parts[:4]) if parts[2].startswith("@") else "/".join(parts[:3])
    elif len(parts) >= 2:
        key = "/".join(parts[:2])
    else:
        key = name
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % CHUNKS
# Advertise the official optional bundles validated on HarmonyOS. Selection
# remains in the user's profile; an installation dependency only makes a
# bundle available to PluginManager without downloading another copy.
OPTIONAL_BUNDLES = (
    "@deepseek-ai/dsh-deepseek-chat-import",
    "@deepseek-ai/dsh-experimental-auto-review",
    "@deepseek-ai/dsh-experimental-badge-skill-bundle",
    "@deepseek-ai/dsh-experimental-cot-translation-bundle",
    "@deepseek-ai/dsh-experimental-forge-bundle",
    "@deepseek-ai/dsh-experimental-inspector-profile",
    "@deepseek-ai/dsh-experimental-liveshare",
    "@deepseek-ai/dsh-experimental-plugin-market-bundle",
    "@deepseek-ai/dsh-experimental-ralph-bundle",
    "@deepseek-ai/dsh-experimental-session-search",
    "@deepseek-ai/dsh-experimental-session-titles-bundle",
    "@deepseek-ai/dsh-experimental-tool-worktree",
    "@deepseek-ai/dsh-experimental-voice-input-bundle",
    "@deepseek-ai/dsh-personalized-recommendations",
)


def stage_dsh(root, raw, baseline):
    manifest = root / "runtime/harmonyos/dsh"
    lock = manifest / "package-lock.json"
    # This layer also carries our application manifest. Cache the complete
    # recipe, not only npm's dependency graph.
    bundle = root / "packages/bundles/mobile-lsp"
    bundle_files = [bundle / "package.json", bundle / "cordis.patch.yml"]
    application = json.loads((manifest / "package.json").read_text())
    for package, version in json.loads(bundle_files[0].read_text())["dependencies"].items():
        if application["dependencies"].get(package) != version:
            raise ValueError(f"Mobile LSP bundle dependency mismatch: {package}")
    # Our bundle is built from this repository, not fetched from npm. Declare
    # it in the final carrier so PluginManager recognizes shipped ownership.
    bundle_manifest = json.loads(bundle_files[0].read_text())
    application["dependencies"][bundle_manifest["name"]] = bundle_manifest["version"]
    patch_dir = root / "patches"
    patch_bytes = b''.join(path.name.encode() + path.read_bytes()
                           for path in sorted(patch_dir.glob("*.patch")) if path.is_file())
    key = hashlib.sha256(lock.read_bytes() + (manifest / "package.json").read_bytes() + Path(__file__).read_bytes() + b''.join(file.read_bytes() for file in bundle_files) + patch_bytes).hexdigest()
    pinned = json.loads(lock.read_text())["packages"]
    for package, source in json.loads((manifest / "lsp-sources.json").read_text()).items():
        recorded = pinned["node_modules/" + package]
        checkout = root / source["source"]
        package_json = checkout / source.get("packageJson", "package.json")
        head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        if (head != source["commit"] or recorded["version"] != source["version"] or
                recorded["integrity"] != source["integrity"] or
                json.loads(package_json.read_text())["version"] != source["version"]):
            raise ValueError(f"LSP source / npm pin mismatch: {package}")
    cache = root / ".build/dsh-runtime" / key
    archive = cache / ARCHIVE
    if not (cache / MANIFEST).is_file():
        cache.mkdir(parents=True, exist_ok=True)
        for source in (manifest / "package.json", lock):
            shutil.copy2(source, cache / source.name)
        modules = cache / "node_modules"
        node = Path(os.environ["HARMONY_BUILD_NODE"])
        subprocess.run([
            str(node), str(node.with_name("npm")), "ci", "--ignore-scripts", "--omit=dev",
            "--cpu=arm64", "--os=linux", "--libc=musl", "--bin-links=false",
            "--registry=https://registry.npmjs.org", "--no-audit", "--no-fund",
        ], cwd=cache, check=True)

        expected = json.loads(lock.read_text())["packages"]["node_modules/@deepseek-ai/dsh"]["version"]
        current = json.loads((modules / "@deepseek-ai/dsh/package.json").read_text())["version"]
        if current != expected:
            raise ValueError(f"Installed DSH {current}, expected {expected}")
        official = pinned["node_modules/@deepseek-ai/dsh"]["dependencies"]
        for name in OPTIONAL_BUNDLES:
            version = pinned["node_modules/" + name]["version"]
            folder = modules / name
            metadata = json.loads((folder / "package.json").read_text())
            patch = metadata.get("dsh", {}).get("bundle", {}).get("patch")
            if (official.get(name) != version or version != expected or metadata.get("version") != version
                    or not isinstance(patch, str) or not (folder / patch).is_file()):
                raise ValueError(f"Invalid official optional bundle: {name}")
            application["dependencies"][name] = version
        with ZipFile(baseline) as prior:
            for name in NATIVE_MODULES:
                if (modules / name).read_bytes() != prior.read("dsh/node_modules/" + name):
                    raise ValueError(f"DSH native input changed and needs a new HAP binding: {name}")
        # patches/series.json replaces fragile boot-time string surgery where a
        # package-level fix is enough (see patches/README.md).
        series_path = patch_dir / "series.json"
        if series_path.is_file():
            for entry in json.loads(series_path.read_text())["patches"]:
                subprocess.run(["patch", "-p1", "--forward", "--batch", "-s",
                                "-i", str(patch_dir / entry["file"])], cwd=modules, check=True)
                target = modules / entry["package"] / entry["path"]
                if entry["marker"] not in target.read_text():
                    raise ValueError(f"patch marker missing after apply: {entry['file']}")

        chunk_paths = [cache / f"dsh-layer-{index}.zip" for index in range(CHUNKS)]
        chunk_pending = [path.with_suffix(".tmp") for path in chunk_paths]
        optional_pending = cache / (OPTIONAL_ARCHIVE + ".tmp")
        try:
            outputs = [ZipFile(path, "w") for path in chunk_pending]
            optional_output = ZipFile(optional_pending, "w")
            try:
                def write(name: str, payload: bytes) -> None:
                    if any(pattern.search(name) for pattern in OPTIONAL_PATTERNS):
                        target = optional_output
                    else:
                        target = outputs[chunk_index(name)]
                    target.writestr(ZipInfo(name), payload, compress_type=ZIP_DEFLATED, compresslevel=3)

                write("dsh/package.json", (json.dumps(application, indent=2) + '\n').encode())
                for file in bundle_files:
                    write("dsh/node_modules/@mobile-harness/lsp/" + file.name, file.read_bytes())
                for path in sorted(modules.rglob("*")):
                    if path.is_symlink():
                        raise ValueError(f"Unexpected npm symlink: {path}")
                    if path.is_file():
                        name = "dsh/" + path.relative_to(cache).as_posix()
                        if pruned(name):
                            continue
                        write(name, path.read_bytes())
                compiler = modules / "typescript"
                for path in sorted(compiler.rglob("*")):
                    if path.is_file():
                        name = "toolchains/lsp/node_modules/typescript/" + path.relative_to(compiler).as_posix()
                        if pruned(name):
                            continue
                        write(name, path.read_bytes())
            finally:
                for output in outputs:
                    output.close()
                optional_output.close()
            manifest = {"schema": 1, "chunks": []}
            for index, (path, pending) in enumerate(zip(chunk_paths, chunk_pending)):
                pending.replace(path)
                manifest["chunks"].append({
                    "file": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
            (cache / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
            optional = cache / OPTIONAL_ARCHIVE
            optional_pending.replace(optional)
        finally:
            for pending in chunk_pending:
                pending.unlink(missing_ok=True)
            optional_pending.unlink(missing_ok=True)

    for path in sorted(cache.glob("dsh-layer-*.zip")):
        if path.name == OPTIONAL_ARCHIVE:
            continue
        shutil.copy2(path, raw / path.name)
    shutil.copy2(cache / MANIFEST, raw / MANIFEST)
    optional = cache / OPTIONAL_ARCHIVE
    if optional.is_file():
        shutil.copy2(optional, raw / OPTIONAL_ARCHIVE)
        (raw / "dsh-optional-runtime-id.txt").write_text(hashlib.sha256(optional.read_bytes()).hexdigest())
    else:
        (raw / "dsh-optional-runtime-id.txt").write_text("")
    (raw / "dsh-lsp.patch.yml").unlink(missing_ok=True)
    # A same-DSH-version production dependency change must invalidate unpack.
    # User profiles/workspaces live outside this immutable release directory.
    (raw / "dsh-runtime-id.txt").write_text(
        hashlib.sha256((cache / MANIFEST).read_bytes()).hexdigest())
