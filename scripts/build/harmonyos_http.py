"""Lower exactly the locked Undici llhttp parser for a JITless native Host."""
import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request
from zipfile import ZipFile

from harmonyos_ptc import BINARYEN_SHA512

WASM_SHA256 = "ab4573a06c43574936dc98c3943b10a4ee32798e9797329e9f327e5f64115f54"
OUTPUT_SHA256 = "c59f929a2c4edc035fac36b2e3e8c77eeb83428f90e4b2abeac2a9aafc8ea508"
ASSET = "dsh-harmony-llhttp.cjs"


def stage_http(root, raw):
    with ZipFile(raw / "dsh-layer.zip") as layer:
        source = layer.read("dsh/node_modules/undici/lib/llhttp/llhttp-wasm.js").decode()
        license_text = layer.read("dsh/node_modules/undici/LICENSE")
    matches = re.findall(r"'([A-Za-z0-9+/=]{300,})'", source)
    if len(matches) != 1:
        raise ValueError("Unexpected locked Undici llhttp wrapper")
    wasm = base64.b64decode(matches[0], validate=True)
    if hashlib.sha256(wasm).hexdigest() != WASM_SHA256:
        raise ValueError("Unexpected locked Undici llhttp WASM")
    destination = root / ".build/portable-llhttp" / (WASM_SHA256 + "-binaryen132")
    target = destination / ASSET
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != OUTPUT_SHA256:
        archive = root / ".build/runtime-package-inputs/binaryen-132.0.0.tgz"
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.is_file():
            pending = archive.with_suffix(".download")
            try:
                with urllib.request.urlopen("https://registry.npmjs.org/binaryen/-/binaryen-132.0.0.tgz", timeout=60) as response, pending.open("wb") as output:
                    shutil.copyfileobj(response, output)
                if base64.b64encode(hashlib.sha512(pending.read_bytes()).digest()).decode() != BINARYEN_SHA512:
                    raise ValueError("Downloaded Binaryen archive failed integrity verification")
                pending.replace(archive)
            finally:
                pending.unlink(missing_ok=True)
        if base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode() != BINARYEN_SHA512:
            raise ValueError("Binaryen 132.0.0 archive failed integrity verification")
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as package:
            (destination / "wasm2js").write_bytes(package.extractfile("package/bin/wasm2js").read())
        (destination / "llhttp.wasm").write_bytes(wasm)
        with (destination / "wasm2js.log").open("w") as log:
            subprocess.run([os.environ.get("HARMONY_BUILD_NODE", "node"), "wasm2js", "llhttp.wasm", "-O2",
                            "--enable-bulk-memory", "--enable-bulk-memory-opt", "--enable-sign-ext", "-o", "generated.mjs"],
                           cwd=destination, stdout=log, stderr=subprocess.STDOUT, check=True)
        generated = (destination / "generated.mjs").read_text()
        header, body = generated.split("\n", 1)
        javascript, exports = body.rsplit("\nvar retasmFunc = asmFunc({", 1)
        if header != "import * as env from 'env';" or 'export var llhttp_execute = retasmFunc.llhttp_execute;' not in exports:
            raise ValueError("Unexpected Binaryen llhttp output")
        target.write_text('"use strict";\nmodule.exports = function(imports) {\n' + javascript + '\nreturn {exports:asmFunc(imports)};\n};\n')
    if hashlib.sha256(target.read_bytes()).hexdigest() != OUTPUT_SHA256:
        raise ValueError("Unexpected portable llhttp output")
    shutil.copy2(target, raw / ASSET)
    (raw / "LICENSE.undici.txt").write_bytes(license_text)
    shutil.copy2(root / "vendor/repos/node/deps/llhttp/LICENSE-MIT", raw / "LICENSE.llhttp.txt")
