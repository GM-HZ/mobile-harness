"""Assemble the pinned DSH npm release and verify existing native bindings."""
import hashlib
import json
import os
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
# Advertise the official optional bundles validated on HarmonyOS. Selection
# remains in the user's profile; an installation dependency only makes a
# bundle available to PluginManager without downloading another copy.
OPTIONAL_BUNDLES = (
    "@deepseek-ai/dsh-deepseek-chat-import",
    "@deepseek-ai/dsh-experimental-badge-skill-bundle",
    "@deepseek-ai/dsh-experimental-forge-bundle",
    "@deepseek-ai/dsh-experimental-plugin-market-bundle",
    "@deepseek-ai/dsh-experimental-ralph-bundle",
    "@deepseek-ai/dsh-experimental-session-search",
    "@deepseek-ai/dsh-experimental-session-titles-bundle",
    "@deepseek-ai/dsh-experimental-tool-worktree",
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
    key = hashlib.sha256(lock.read_bytes() + (manifest / "package.json").read_bytes() + Path(__file__).read_bytes() + b''.join(file.read_bytes() for file in bundle_files)).hexdigest()
    pinned = json.loads(lock.read_text())["packages"]
    for package, source in json.loads((manifest / "lsp-sources.json").read_text()).items():
        recorded = pinned["node_modules/" + package]
        checkout = root / source["source"]
        head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        if (head != source["commit"] or recorded["version"] != source["version"] or
                recorded["integrity"] != source["integrity"] or
                json.loads((checkout / "package.json").read_text())["version"] != source["version"]):
            raise ValueError(f"LSP source / npm pin mismatch: {package}")
    cache = root / ".build/dsh-runtime" / key
    archive = cache / ARCHIVE
    if not archive.is_file():
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

        pending = archive.with_suffix(".tmp")
        try:
            with ZipFile(pending, "w") as output:
                output.writestr(ZipInfo("dsh/package.json"), (json.dumps(application, indent=2) + '\n').encode(), compress_type=ZIP_DEFLATED, compresslevel=3)
                for file in bundle_files:
                    output.writestr(ZipInfo("dsh/node_modules/@mobile-harness/lsp/" + file.name), file.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=3)
                for path in sorted(modules.rglob("*")):
                    if path.is_symlink():
                        raise ValueError(f"Unexpected npm symlink: {path}")
                    if path.is_file():
                        name = "dsh/" + path.relative_to(cache).as_posix()
                        output.writestr(ZipInfo(name), path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=3)
                # tsserver watches its nearest node_modules recursively. Keep
                # its immutable compiler library away from DSH's large tree;
                # workspace dependencies remain visible and fully watched.
                compiler = modules / "typescript"
                for path in sorted(compiler.rglob("*")):
                    if path.is_file():
                        name = "toolchains/lsp/node_modules/typescript/" + path.relative_to(compiler).as_posix()
                        output.writestr(ZipInfo(name), path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=3)
            pending.replace(archive)
        finally:
            pending.unlink(missing_ok=True)

    shutil.copy2(archive, raw / ARCHIVE)
    (raw / "dsh-lsp.patch.yml").unlink(missing_ok=True)
    # A same-DSH-version production dependency change must invalidate unpack.
    # User profiles/workspaces live outside this immutable release directory.
    digest = hashlib.sha256()
    with archive.open("rb") as packed:
        for block in iter(lambda: packed.read(1024 * 1024), b''):
            digest.update(block)
    (raw / "dsh-runtime-id.txt").write_text(digest.hexdigest())
