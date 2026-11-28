"""Build and stage the locked, application-owned llama.cpp runtime."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory


NOTICES = {
    "LICENSE.llama.cpp.txt": "LICENSE",
    "LICENSE.llama-cpp-jsonhpp.txt": "licenses/LICENSE-jsonhpp",
    "LICENSE.llama-cpp-httplib.txt": "vendor/cpp-httplib/LICENSE",
    "LICENSE.llama-cpp-rotate-bits.txt": "vendor/hash/rotate-bits/LICENSE.md",
    "LICENSE.llama-cpp-sha256.txt": "vendor/hash/sha256/LICENSE",
    "LICENSE.llama-cpp-xxhash.txt": "vendor/hash/xxhash/LICENSE",
}


def build_llama(root):
    packaging = root / "runtime/harmonyos/packaging"
    patch = packaging / "local-inference-llama.patch"
    revision = (packaging / "local-inference-llama.revision").read_text().strip()
    checkout = os.environ.get("HARMONY_LLAMA_CPP_SOURCE")
    if not checkout:
        raise SystemExit(f"Set HARMONY_LLAMA_CPP_SOURCE to a llama.cpp checkout at {revision}")
    actual = subprocess.check_output(["git", "-C", checkout, "rev-parse", "HEAD"], text=True).strip()
    if revision != actual:
        raise SystemExit(f"llama.cpp revision mismatch: expected {revision}, got {actual}")

    cache = root / ".build/runtime-package-inputs"
    cache.mkdir(parents=True, exist_ok=True)
    patch_hash = hashlib.sha256(patch.read_bytes()).hexdigest()[:16]
    source = cache / f"llama.cpp-{revision}-{patch_hash}"
    if not source.exists():
        with TemporaryDirectory(prefix="llama.cpp-", dir=cache) as directory:
            temporary = Path(directory)
            archive = temporary / "source.tar"
            tree = temporary / "tree"
            tree.mkdir()
            subprocess.run(["git", "-C", checkout, "archive", "-o", str(archive), revision], check=True)
            subprocess.run(["tar", "-xf", str(archive), "-C", str(tree)], check=True)
            subprocess.run(["git", "apply", str(patch)], cwd=tree, check=True)
            try:
                tree.rename(source)
            except OSError:
                if not source.is_dir():
                    raise

    sdk = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents"))
    native_sdk = sdk / "sdk/default/openharmony/native"
    toolchain = native_sdk / "build/cmake/ohos.toolchain.cmake"
    options = [
        "-G", "Ninja",
        f"-DCMAKE_TOOLCHAIN_FILE={toolchain}", "-DOHOS_ARCH=arm64-v8a", "-DOHOS_STL=c++_static",
        "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_FLAGS=-D_GNU_SOURCE",
        "-DCMAKE_CXX_FLAGS=-D_GNU_SOURCE", "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
        "-DBUILD_SHARED_LIBS=OFF", "-DGGML_NATIVE=OFF", "-DGGML_OPENMP=OFF", "-DGGML_LLAMAFILE=OFF",
        "-DGGML_CPU_KLEIDIAI=OFF", "-DLLAMA_OPENSSL=OFF", "-DLLAMA_SUBPROCESS=OFF",
        "-DLLAMA_BUILD_APP=OFF", "-DLLAMA_BUILD_EXAMPLES=OFF", "-DLLAMA_BUILD_MTMD=OFF",
        "-DLLAMA_BUILD_TESTS=OFF", "-DLLAMA_BUILD_UI=OFF", "-DLLAMA_USE_PREBUILT_UI=OFF",
        "-DFETCHCONTENT_FULLY_DISCONNECTED=ON",
        "-DLLAMA_BUILD_NUMBER=12774", f"-DLLAMA_BUILD_COMMIT={revision}",
    ]
    recipe = hashlib.sha256(json.dumps(options).encode())
    recipe.update(toolchain.read_bytes())
    recipe.update((native_sdk / "oh-uni-package.json").read_bytes())
    build = cache / f"{source.name}-ohos-{recipe.hexdigest()[:16]}"
    configure = ["cmake", "-S", str(source), "-B", str(build), *options]
    compile_server = [
        "cmake", "--build", str(build), "--target", "llama-server-impl",
        "--parallel", str(min(8, os.cpu_count() or 1)),
    ]
    with (cache / f"{build.name}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        subprocess.run(configure, check=True)
        subprocess.run(compile_server, check=True)
        if "#define LLAMA_UI_HAS_ASSETS" in (build / "ui/apps/chat/ui.h").read_text():
            raise SystemExit("The experimental llama.cpp build must not embed UI assets")
    return source, build


def stage_local_inference(root, cpp, raw, enabled):
    if not enabled:
        for path in (cpp / "dsh-local-inference.cpp", cpp / "local-inference.cmake",
                     *(raw / name for name in NOTICES)):
            path.unlink(missing_ok=True)
        return

    source, build = build_llama(root)
    runtime = root / "runtime/harmonyos"
    shutil.copy2(runtime / "native/dsh-local-inference.cpp", cpp)
    shutil.copy2(runtime / "packaging/local-inference.cmake", cpp)
    for output, name in NOTICES.items():
        shutil.copy2(source / name, raw / output)
    with (cpp / "CMakeLists.txt").open("a") as stream:
        stream.write(f"\nset(MH_LLAMA_SOURCE {json.dumps(str(source))})\n")
        stream.write(f"set(MH_LLAMA_BUILD {json.dumps(str(build))})\n")
        stream.write('include("${CMAKE_CURRENT_SOURCE_DIR}/local-inference.cmake")\n')
