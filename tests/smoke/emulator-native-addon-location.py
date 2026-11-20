"""Measure where the native Host can load an N-API addon from.

The 0.4.57 extension regression reported ERR_DLOPEN_FAILED for an OHOS addon
that was unpacked into the application data directory. This probe asks the
Host process itself, through the shipped Inspector, to load the same bundled
library twice: by its installed soname (``libs/arm64``) and from a copy in the
application data view. The measurement replaces an inference with a direct
observation and needs no model route.
"""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
from urllib.parse import urlsplit
import urllib.request
import uuid

inspector = runpy.run_path(str(Path(__file__).with_name("emulator-inspector.py")))
support = inspector["support"]
agent = inspector["agent"]
lsp = inspector["lsp"]
request = inspector["request"]
NAME = inspector["NAME"]
PROFILE = inspector["PROFILE"]
BOOTSTRAP = inspector["BOOTSTRAP"]
FILES = support["WORKSPACE"].rsplit("/alpine/", 1)[0]
FIXTURE = Path(__file__).with_name("fixtures") / "inspector-host-eval.cjs"


def cdp_evaluate(emulator, expressions):
    status, body = request(emulator, BOOTSTRAP, True)
    assert status == 200, (status, body[:400])
    info = json.loads(body)
    target = urlsplit(info["endpoint"])
    forward = ("tcp:19646", f"tcp:{target.port}")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    try:
        discovery = urllib.request.Request(
            "http://127.0.0.1:19646/json/list",
            headers={"X-DSH-Inspector-Token": info["protocol"]})
        with emulator.opener.open(discovery, timeout=6) as response:
            targets = json.load(response)
        assert len(targets) == 1, targets
        page = urlsplit(targets[0]["webSocketDebuggerUrl"])
        payload = {
            "proxy": emulator.url.replace("http:", "ws:") + "/inspector/devtools/cdp",
            "cookie": emulator.cookie(),
            "expressions": expressions,
        }
        node = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents")) / "tools/node/bin/node"
        ws = runpy.run_path(str(Path(__file__).with_name("emulator-ptc-approval.py")))["ws_module"]()
        output = subprocess.check_output([str(node), str(FIXTURE), str(ws)],
                                         input=json.dumps(payload), text=True, timeout=90)
        return json.loads(output), {"workerPort": target.port, "targetCount": len(targets), "pagePath": page.path}
    finally:
        emulator.hdc("fport", "rm", *forward)


def run(emulator, output):
    evidence, originals = {}, {}
    ident = "mh-addon-location-" + uuid.uuid4().hex[:10]
    remote = "/data/local/tmp/" + ident
    probe = f"{FILES}/alpine/tmp/{ident}.so"
    try:
        evidence["readyMs"] = emulator.ready("normal")
        for path in [PROFILE + "/package.json", PROFILE + "/pnpm-lock.yaml", "mobile-harness-boot.json"]:
            originals[path] = agent["read_bytes"](emulator, path)
        enabled = emulator.rpc("pluginManager/setBundleEnabled", {"name": NAME, "enabled": True})
        assert enabled["application"] in ["applied", "restart-required"], enabled
        emulator.stop()
        emulator.start()
        evidence["inspectorReadyMs"] = emulator.ready("normal")
        copy_expression = (
            "(() => { const fs = process.getBuiltinModule('node:fs'); "
            f"fs.mkdirSync('{FILES}/alpine/tmp', {{ recursive: true }}); "
            f"fs.copyFileSync('/data/storage/el1/bundle/libs/arm64/libdshshell.so', '{probe}'); "
            "const m = { exports: {} }; const bytes = fs.statSync(" + json.dumps(probe) + ").size; "
            "try { process.dlopen(m, " + json.dumps(probe) + "); "
            "return { ok: true, bytes, exports: Object.keys(m.exports) }; } "
            "catch (error) { return { ok: false, bytes, code: error.code, "
            "message: String(error.message).slice(0, 400) }; } })()"
        )
        expressions = [
            {"label": "hostGlobal", "expression": "6 * 7"},
            {"label": "builtinModule", "expression": "typeof process.getBuiltinModule"},
            {"label": "installedSoname",
             "expression": "(() => { const m = { exports: {} }; try { process.dlopen(m, 'libdshshell.so'); "
                           "return { ok: true, exports: Object.keys(m.exports) }; } "
                           "catch (error) { return { ok: false, code: error.code, "
                           "message: String(error.message).slice(0, 300) }; } })()"},
            {"label": "dataViewCopy", "expression": copy_expression},
            {"label": "sameBytes",
             "expression": "(() => { const fs = process.getBuiltinModule('node:fs'); "
                           "const crypto = process.getBuiltinModule('node:crypto'); "
                           "const source = crypto.createHash('sha256').update("
                           "fs.readFileSync('/data/storage/el1/bundle/libs/arm64/libdshshell.so')).digest('hex'); "
                           "const copy = crypto.createHash('sha256').update("
                           "fs.readFileSync(" + json.dumps(probe) + ")).digest('hex'); "
                           "return { equal: source === copy, sha256: source }; })()"},
            {"label": "installedSonameAgain",
             "expression": "(() => { const m = { exports: {} }; try { process.dlopen(m, 'libdshshell.so'); "
                           "return { ok: true }; } catch (error) { return { ok: false, code: error.code }; } })()"},
        ]
        results, connection = cdp_evaluate(emulator, expressions)
        byLabel = {row["label"]: row for row in results}
        evidence["inspector"] = connection
        evidence["evaluations"] = results
        assert byLabel["hostGlobal"]["value"] == 42, byLabel["hostGlobal"]
        assert byLabel["builtinModule"]["value"] == "function", byLabel["builtinModule"]
        installed = byLabel["installedSoname"]["value"]
        assert installed and installed.get("ok") is True, installed
        # N-API initialisation writes its exports through the dlopen contract; the
        # location probe only needs the loader outcome, which the voice and shell
        # regressions already exercise functionally.
        copy = byLabel["dataViewCopy"]["value"]
        evidence["dataViewCopy"] = copy
        assert copy and copy.get("bytes", 0) > 0, copy
        assert copy.get("ok") is False, copy
        assert copy.get("code") == "ERR_DLOPEN_FAILED", copy
        assert "Error loading shared library" in (copy.get("message") or ""), copy
        same = byLabel["sameBytes"]["value"]
        assert same and same.get("equal") is True, same
        evidence["sameBytes"] = same
        evidence["addonLocation"] = {
            "installedSonameLoads": True,
            "sameBytesFromAppDataFail": True,
            "errorCode": copy["code"],
            "errorMessage": copy["message"],
        }
    finally:
        try:
            emulator.stop()
            if originals:
                for index, (path, body) in enumerate(originals.items()):
                    lsp["restore_bytes"](emulator, path, body, remote + str(index))
            emulator.app(f"rm -f alpine/tmp/{ident}.so")
            emulator.start()
            evidence["restoredReadyMs"] = emulator.ready("normal")
            for path, body in originals.items():
                assert agent["read_bytes"](emulator, path) == body, path
            evidence["restoredConfiguration"] = True
        finally:
            emulator.hdc("shell", "rm", "-f", remote)
            output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--port", type=int, default=19647)
    args = parser.parse_args()
    emulator = support["Emulator"](args.target, args.port)
    forward = (f"tcp:{args.port}", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    try:
        run(emulator, args.output)
    finally:
        emulator.hdc("fport", "rm", *forward)
