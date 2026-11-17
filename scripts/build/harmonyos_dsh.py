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


def stage_dsh(root, raw, baseline):
    manifest = root / "runtime/harmonyos/dsh"
    lock = manifest / "package-lock.json"
    # This layer also carries our application manifest. Cache the complete
    # recipe, not only npm's dependency graph.
    key = hashlib.sha256(lock.read_bytes() + (manifest / "package.json").read_bytes() + Path(__file__).read_bytes()).hexdigest()
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
        with ZipFile(baseline) as prior:
            for name in NATIVE_MODULES:
                if (modules / name).read_bytes() != prior.read("dsh/node_modules/" + name):
                    raise ValueError(f"DSH native input changed and needs a new HAP binding: {name}")

        pending = archive.with_suffix(".tmp")
        try:
            with ZipFile(pending, "w") as output:
                output.writestr(ZipInfo("dsh/package.json"), (manifest / "package.json").read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=3)
                for path in sorted(modules.rglob("*")):
                    if path.is_symlink():
                        raise ValueError(f"Unexpected npm symlink: {path}")
                    if path.is_file():
                        name = "dsh/" + path.relative_to(cache).as_posix()
                        output.writestr(ZipInfo(name), path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=3)
            pending.replace(archive)
        finally:
            pending.unlink(missing_ok=True)

    shutil.copy2(archive, raw / ARCHIVE)
    # A same-DSH-version production dependency change must invalidate unpack.
    # User profiles/workspaces live outside this immutable release directory.
    digest = hashlib.sha256()
    with archive.open("rb") as packed:
        for block in iter(lambda: packed.read(1024 * 1024), b''):
            digest.update(block)
    (raw / "dsh-runtime-id.txt").write_text(digest.hexdigest())
