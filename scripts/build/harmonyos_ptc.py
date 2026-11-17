"""Convert the pinned Node source tree's Amaro WASM to a pure JavaScript runtime."""
import argparse
import base64
import hashlib
import os
import shutil
import urllib.request
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
BINARYEN_SHA512 = ("4Usg7yEvwO3FMso3Oov6qkOOHSod1IEv+boKkh77kTljM+eNBouqCTbqWswGzbG+v"
                   "DNO/b/v2C4gfEh1WgB9Lg==")
FEATURES = ["--enable-bulk-memory", "--enable-bulk-memory-opt",
            "--enable-sign-ext", "--enable-multivalue"]
PORTABLE_ASSETS = {
    "amaro.cjs": "efc9e1155df1dacbf1d0605e78140f09d7016e58dba227006e3d362310d3f839",
    "instantiate.cjs": "cdcdd45f429279c4d966c2d2a6333c4ee06271065fff4f762a041e153be999a3",
}
IMPORT_ADAPTER = """
const bindings = imports.__wbindgen_placeholder__;
const toI64 = (low, high) => (BigInt(high | 0) << 32n) | BigInt(low >>> 0);
return asmFunc({
  __wbindgen_placeholder__: {
    ...bindings,
    __wbindgen_bigint_from_i64: (low, high) => bindings.__wbindgen_bigint_from_i64(toI64(low, high)),
    __wbindgen_bigint_from_u64: (low, high) => bindings.__wbindgen_bigint_from_u64(toI64(low, high)),
  },
});
"""


def generate(binaryen, destination):
    digest = base64.b64encode(hashlib.sha512(binaryen.read_bytes()).digest()).decode("ascii")
    if digest != BINARYEN_SHA512:
        raise ValueError("Binaryen 132.0.0 archive failed integrity verification")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(binaryen) as archive:
        (destination / "LICENSE.binaryen.txt").write_bytes(archive.extractfile("package/LICENSE").read())
        for name in ("wasm-opt", "wasm2js"):
            target = destination / name
            target.write_bytes(archive.extractfile(f"package/bin/{name}").read())
    source = (ROOT / "vendor/repos/node/deps/amaro/dist/index.js").read_text()
    glue = re.compile(
        r'    var bytes = Buffer2.from\("([A-Za-z0-9+/=]+)", "base64"\);\n'
        r'    var wasmModule = new WebAssembly.Module\(bytes\);\n'
        r'    var wasmInstance = new WebAssembly.Instance\(wasmModule, imports\);\n'
        r'    wasm = wasmInstance.exports;'
    )
    matches = list(glue.finditer(source))
    if len(matches) != 1:
        raise ValueError("Unexpected pinned Amaro instantiation code")
    (destination / "amaro.wasm").write_bytes(base64.b64decode(matches[0][1], validate=True))
    commands = [
        ["wasm-opt", "amaro.wasm", *FEATURES, "--enable-nontrapping-float-to-int",
         "--llvm-nontrapping-fptoint-lowering", "-o", "amaro-lowered.wasm"],
        ["wasm2js", "amaro-lowered.wasm", *FEATURES, "-O2", "-o", "generated.mjs"],
    ]
    for command in commands:
        log = destination / (command[0] + ".log")
        with log.open("w") as output:
            result = subprocess.run([os.environ.get("HARMONY_BUILD_NODE", "node"), *command], cwd=destination, stdout=output, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"{command[0]} exited {result.returncode}. See {log}")
    generated = (destination / "generated.mjs").read_text()
    header, body = generated.split("\n", 1)
    javascript, exports = body.rsplit("\nvar retasmFunc = asmFunc({", 1)
    if (header != "import * as __wbindgen_placeholder__ from '__wbindgen_placeholder__';"
            or "export var transformSync = retasmFunc.transformSync;" not in exports):
        raise ValueError("Unexpected Binaryen output")
    (destination / "instantiate.cjs").write_text(
        '"use strict";\nmodule.exports = function instantiate(imports) {\n'
        + javascript + IMPORT_ADAPTER + '};\n'
    )
    # Wasm detaches old memory views when it grows. wasm2js swaps buffers instead.
    for variable, guard in (
        ("cachedUint8ArrayMemory0", "cachedUint8ArrayMemory0.byteLength === 0"),
        ("cachedDataViewMemory0", "cachedDataViewMemory0.buffer.detached === true || "
         "cachedDataViewMemory0.buffer.detached === void 0 && cachedDataViewMemory0.buffer !== wasm.memory.buffer"),
    ):
        if source.count(guard) != 1:
            raise ValueError(f"Unexpected pinned Amaro buffer guard: {variable}")
        source = source.replace(guard, f"{variable}.buffer !== wasm.memory.buffer")
    (destination / "amaro.cjs").write_text(
        glue.sub('    wasm = require("./instantiate.cjs")(imports);', source)
    )


def portable_assets():
    """Prepare verified build-time output; ship no compiler or WASM to the phone."""
    override = os.environ.get("HARMONY_PTC_AMARO_DIR")
    if override:
        destination = Path(override).resolve()
    else:
        source = ROOT / "vendor/repos/node/deps/amaro/dist/index.js"
        key = hashlib.sha256(source.read_bytes()).hexdigest()
        destination = ROOT / ".build/portable-amaro" / (key + "-binaryen132")
        if not all((destination / name).is_file() and
                   hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
                   for name, digest in PORTABLE_ASSETS.items()):
            archive = ROOT / ".build/runtime-package-inputs/binaryen-132.0.0.tgz"
            archive.parent.mkdir(parents=True, exist_ok=True)
            if not archive.exists():
                pending = archive.with_suffix(".download")
                try:
                    with urllib.request.urlopen(
                        "https://registry.npmjs.org/binaryen/-/binaryen-132.0.0.tgz", timeout=60
                    ) as response, pending.open("wb") as output:
                        shutil.copyfileobj(response, output)
                    digest = base64.b64encode(hashlib.sha512(pending.read_bytes()).digest()).decode("ascii")
                    if digest != BINARYEN_SHA512:
                        raise ValueError("Downloaded Binaryen archive failed integrity verification")
                    pending.replace(archive)
                finally:
                    pending.unlink(missing_ok=True)
            generate(archive, destination)
    for name, expected in PORTABLE_ASSETS.items():
        if hashlib.sha256((destination / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Unexpected portable Amaro input: {name}")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binaryen_archive", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    generate(options.binaryen_archive.resolve(), options.output.resolve())
