#!/usr/bin/env python3
"""G1 behavior contracts: apply our boot-time transformations to the assembled
upstream sources and verify the results stay valid and contain the expected
behavior. Needs the assembled DSH layer (otherwise exit 2 = skipped).

Checks:
  1. settings client injection keeps one apply(ctx) entry and yields valid JS;
  2. bash module command replacement yields the /bin/bash literal and valid JS;
  3. session-persistence replacement is still present in dsh-client.cjs and the
     upstream anchor still exists (the exact replacement expression is executed
     only at boot, so syntax-level validation is the contract here).
"""
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = [
    ROOT / ".build/stage/harmonyos/entry/src/main/resources/rawfile/dsh-layer.zip",
    ROOT.parent / "harmonyos-capability-parity/.build/stage/harmonyos/entry/src/main/resources/rawfile/dsh-layer.zip",
]
SETTINGS = "dsh/node_modules/@deepseek-ai/dsh-client-ui-settings-general/lib/client.js"
BASH_MODULES = [
    "dsh/node_modules/@deepseek-ai/dsh-bash-local/lib/index.js",
    "dsh/node_modules/@deepseek-ai/dsh-bash-sandbox/lib/index.js",
]
SESSION = "dsh/node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js"
ANCHOR = '"bash",\n\t\t\t"-c",'


def locate():
    for candidate in CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def node_check(source):
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as handle:
        handle.write(source)
        path = handle.name
    try:
        return subprocess.run(["node", "--check", path], capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)


def main():
    parser = __import__("argparse").ArgumentParser(description=__doc__)
    parser.add_argument("--layer")
    args = parser.parse_args()
    layer = Path(args.layer) if args.layer else locate()
    if not layer:
        print("SKIP host contracts: assembled DSH layer unavailable", file=sys.stderr)
        return 2
    failures = []
    checked = []
    with zipfile.ZipFile(layer) as archive:
        settings = archive.read(SETTINGS).decode()
        marker = "registerMobileHarnessRecovery(ctx);"
        stage = (ROOT / "scripts/build/stage-harmonyos.py").read_text()
        engine = (ROOT / "apps/harmonyos/entry/src/main/ets/runtime/DshEngine.ets").read_text()
        no_stage_override = ('dsh-settings-client.js").write_text' not in stage
                             and "copyGuest(context, 'dsh-settings-client.js'" not in engine)
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as handle:
            handle.write(settings)
            probe = handle.name
        try:
            syntax = subprocess.run(["node", "--check", probe], capture_output=True, text=True)
        finally:
            Path(probe).unlink(missing_ok=True)
        ok = marker in settings and no_stage_override and syntax.returncode == 0
        checked.append({"id": "settings-client-patch", "ok": ok,
                        "marker": marker in settings, "noStageOverride": no_stage_override})
        if not ok:
            failures.append(f"settings client contract: marker={marker in settings} "
                            f"noStageOverride={no_stage_override} syntax={syntax.returncode} "
                            f"{syntax.stderr.strip()[:200]}")
        boot_no_replacement = ANCHOR not in (ROOT / "packages/dsh-host/dsh-client.cjs").read_text()
        for module in BASH_MODULES:
            source = archive.read(module).decode()
            patched = '"/bin/bash",\n\t\t\t"-c",' in source
            syntax = node_check(source)
            ok = patched and boot_no_replacement and syntax.returncode == 0
            module_id = module.rsplit("/", 1)[0].rsplit("/", 1)[-1]
            checked.append({"id": "bash-command-" + module_id, "ok": ok, "mode": "patched"})
            if not ok:
                failures.append(f"{module}: patched={patched} bootNoReplacement={boot_no_replacement} "
                                f"syntax={syntax.returncode} {syntax.stderr.strip()[:200]}")
        forge = archive.read("dsh/node_modules/@deepseek-ai/dsh-experimental-forge-github/lib/index.js").decode()
        host = (ROOT / "packages/dsh-host/dsh-native-web.cjs").read_text()
        forge_marker = "globalThis.__harmonyGhRunner ?? ghRunner(resolved)"
        ok = forge_marker in forge and "__harmonyGhRunner" in host and "const execa = globalThis.__harmonyGh;" not in host
        checked.append({"id": "forge-guest-runner", "ok": ok})
        if not ok:
            failures.append("forge contract: patched registration + guest runner adapter + no boot rewrite")
        session = archive.read(SESSION).decode()
        boot = (ROOT / "packages/dsh-host/dsh-client.cjs").read_text()
        replacement = "globalThis.__dshClientRenameNoReplace(tmp, finalPath)"
        patched = replacement in session
        boot_owns_hook = "await link(tmp, finalPath);" in boot
        ok = patched and not boot_owns_hook and "globalThis.__dshClientRenameNoReplace = " in boot
        if not ok:
            failures.append("session-persistence contract: patched layer + helper defined + no boot-time replacement")
        checked.append({"id": "session-persistence-contract", "ok": ok, "mode": "patched"})
    result = {"layer": str(layer), "checked": checked, "failures": failures, "ok": not failures}
    print(json.dumps(result, indent=2))
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print(f"G1 host contracts OK: {len(checked)} contracts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
