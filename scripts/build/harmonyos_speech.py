"""Stage the pinned upstream HarmonyOS ARM64 SenseVoice libraries."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

RELEASE = "sherpa-onnx-v1.13.8-ohos-arm64-v8a"
ARCHIVE = RELEASE + ".tar.bz2"
SOURCE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.8/" + ARCHIVE
ARCHIVE_SHA256 = "7473e1f6138c2d33a26adda01dd94f4d618089370957ed374f8cc0d50b8cdfa7"
LIBRARIES = ("libsherpa-onnx-c-api.so", "libonnxruntime.so")
HEADER = "sherpa-onnx/c-api/c-api.h"


def check(path, expected):
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError(f"Speech input digest mismatch: {path.name}")


def pinned_asset(cache, name, url, expected):
    asset = cache / name
    if not asset.exists():
        temporary = asset.with_suffix(".download")
        try:
            with urllib.request.urlopen(url, timeout=90) as stream, temporary.open("wb") as target:
                shutil.copyfileobj(stream, target)
            check(temporary, expected)
            temporary.replace(asset)
        finally:
            temporary.unlink(missing_ok=True)
    check(asset, expected)
    return asset


def stage_speech(root, stage, raw):
    cache = root / ".build/runtime-package-inputs"
    cache.mkdir(exist_ok=True, parents=True)
    archive = pinned_asset(cache, ARCHIVE, SOURCE, ARCHIVE_SHA256)
    license_file = pinned_asset(
        cache, "LICENSE.sherpa-onnx.txt",
        "https://raw.githubusercontent.com/k2-fsa/sherpa-onnx/11afbd009a7f8c08f4bcf2fc1b265d0df4670fbf/LICENSE",
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    )
    shutil.copy2(license_file, raw)
    libraries = stage / "entry/libs/arm64-v8a"
    sdk = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents")) / "sdk/default/openharmony/native"
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        include = Path(directory)
        header = include / HEADER
        header.parent.mkdir(parents=True)
        with tarfile.open(archive) as package:
            for relative, target in [
                ("include/" + HEADER, header),
                *[("lib/" + name, libraries / name) for name in LIBRARIES],
            ]:
                member = package.getmember(RELEASE + "/" + relative)
                if not member.isfile():
                    raise ValueError(f"Speech input is not a regular file: {relative}")
                with package.extractfile(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
        shutil.copy2(sdk / "llvm/lib/aarch64-linux-ohos/libc++_shared.so", libraries)
        subprocess.run([
            str(sdk / "llvm/bin/clang"), "--target=aarch64-linux-ohos", "--sysroot=" + str(sdk / "sysroot"),
            "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", "-DNAPI_VERSION=8",
            "-I", str(include), "-I", str(root / "vendor/repos/node/src"),
            str(root / "runtime/harmonyos/native/dsh-speech.c"), "-L", str(libraries),
            "-lsherpa-onnx-c-api", "-lonnxruntime", "-ldl", "-Wl,-z,defs",
            "-o", str(libraries / "libdshspeech.so"),
        ], check=True)
