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
    key = hashlib.sha256(lock.read_bytes()).hexdigest()
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
