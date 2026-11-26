#!/usr/bin/env python3
"""G1: guard the real-device regressions fixed on 2026-11-21.

These are host/test invariants that are cheap to check and expensive to
rediscover on hardware:

1. `/bin/bash` (patched bash argv) must route through the packaged PRoot spawn
   path, like `bash`; otherwise signed real-device builds hit PRoot's
   signed-exec loader handoff ("embedded loader descriptors").
2. The bash exit-status cell is ASCII digits + binary padding; the parser must
   extract digits instead of requiring exactly three digits.
3. Each probe requires its own `*_DONE` marker and a clean Bash completion.
4. device_lab requires the probe's `ok:true`, and verify rejects a Host that
   becomes unhealthy after startup.
5. Embedded Host startup uses jitless, and children keep their intended
   descriptors while avoiding an unsupported bulk-close syscall.
"""
import json
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "packages/dsh-host/dsh-native-web.cjs"
PROBE = ROOT / "tests/smoke/mate60-proot-exec.py"
DEVICE_LAB = ROOT / "scripts/adaptation/device_lab.py"
NATIVE = ROOT / "runtime/harmonyos/native"


def verify_rejects_unhealthy_host():
    verify = runpy.run_path(str(ROOT / "tests/smoke/mate60-verify.py"))
    normal = {"mode": "normal", "pending": False}
    cases = (({"mode": "safe", "pending": True}, 200), (normal, 503))
    with TemporaryDirectory() as directory:
        output = Path(directory) / "verify.json"
        for state, status in cases:
            device = SimpleNamespace(
                target="fixture", port=19670, start=lambda: "started", ready=lambda: 1,
                hdc=lambda *_args: "{}", state=lambda: state, web_status=lambda: status,
                rpc=lambda method, _args: [] if method == "pluginManager/listBundles" else {},
            )
            try:
                verify["run"](device, output)
            except SystemExit:
                evidence = json.loads(output.read_text())
                if evidence.get("ok") is not False or evidence.get("state") != state or evidence.get("web") != status:
                    return False
            else:
                return False
    return True


def exec_requires_clean_bash_completion():
    record = runpy.run_path(str(PROBE))["record_probe_result"]
    command = "echo G3_TEST_DONE"
    calls = [{"name": "bash", "callId": "fixture", "arguments": json.dumps({"command": command})}]
    cases = (
        ("", []),
        ("\n[exit code: 7]", ["nonzeroExit"]),
        ("\n[killed by signal: SIGTERM]", ["signal"]),
        ("\n[timed out after 5000ms]", ["timedOut"]),
        ("\n[stderr]\n[output truncated; full output: (unavailable)]", ["truncated"]),
    )
    for suffix, expected in cases:
        result = {"toolCallId": "fixture", "isError": False, "content": [{"text": "G3_TEST_DONE" + suffix}]}
        evidence = {}
        record(evidence, command, calls, [result])
        if evidence["bashCompletionErrors"] != expected or evidence["ok"] is not (not expected):
            return False
    return True


def main():
    host = HOST.read_text()
    probe = PROBE.read_text()
    device_lab = DEVICE_LAB.read_text()
    failures = []
    if "program === 'bash' || program === '/bin/bash'" not in host:
        failures.append("host spawn no longer routes /bin/bash through the packaged path")
    if "program !== 'bash' && program !== '/bin/bash'" not in host:
        failures.append("__harmonyProotSpawn no longer accepts /bin/bash")
    if "replace(/\\D/g, '')" not in host:
        failures.append("bash status parser no longer extracts digits from padded status")
    if "^\\d{3}$" in host:
        failures.append("bash status parser regressed to requiring three digits")
    if "proxyEnv" not in host or "'HTTPS_PROXY'" not in host:
        failures.append("guest gh runner no longer forwards proxy environment variables")
    engine = (ROOT / "apps/harmonyos/entry/src/main/ets/runtime/DshEngine.ets").read_text()
    index = (ROOT / "apps/harmonyos/entry/src/main/ets/pages/Index.ets").read_text()
    if "plugin-snapshot" not in engine or "restartWithPluginRollback" not in engine:
        failures.append("plugin snapshot/rollback wiring missing from DshEngine")
    if "回滚插件配置" not in index:
        failures.append("plugin rollback action missing from the recovery UI")
    compat = (ROOT / "runtime/harmonyos/compat/dsh-harmony-forge.cjs").read_text()
    if "__harmonyPackagedShell" not in host or "createGhRunner(\n      (cwd, command, environment)" not in host:
        failures.append("forge gh no longer routes through the packaged shell helper")
    if "child.once('exit', code => setTimeout(() => finish(" not in compat:
        failures.append("forge gh child lifecycle no longer handles exit-only children")
    if "done.group(1) in lines" not in probe or "done is not None and all(markers.values())" not in probe:
        failures.append("probe success no longer uses its own *_DONE marker")
    if not exec_requires_clean_bash_completion():
        failures.append("exec probe accepts a failed or incomplete Bash result")
    if 'probe.get("ok") is True' not in device_lab:
        failures.append("device_lab no longer requires the probe's ok:true")
    if not verify_rejects_unhealthy_host():
        failures.append("device verify does not reject a Host that became unhealthy after startup")
    nativehost = (NATIVE / "nativehost.c").read_text()
    if ('"node", "--jitless", "--expose-internals"' not in nativehost or "MH_SELF_BUILD" in nativehost
            or "dsh-host-jitless" in nativehost or "dsh-host-jitless" in engine):
        failures.append("embedded Host startup must use jitless on every launch")
    descriptor_calls = {
        "workflow-broker.c": ("STDERR_FILENO + 1, -1", "STDIN_FILENO + 1, -1"),
        "ptc-supervisor.c": ("STDERR_FILENO + 1, 7",),
        "poc.c": ("STDERR_FILENO + 1, status_channel",),
    }
    for name, arguments in descriptor_calls.items():
        source = (NATIVE / name).read_text()
        if "SYS_close_range" in source or any(f"close_child_descriptors({args})" not in source for args in arguments):
            failures.append(f"{name} no longer closes child descriptors with the expected IPC exceptions")
    descriptors = (NATIVE / "child-descriptors.h").read_text()
    if not all(check in descriptors for check in ('opendir("/proc/self/fd")', "fd == own", "fd == keep")):
        failures.append("child descriptor cleanup must preserve its directory and IPC descriptors")
    staging = (ROOT / "scripts/build/stage-harmonyos.py").read_text()
    if '"child-descriptors.h"' not in staging:
        failures.append("HarmonyOS native staging omits the child descriptor helper")
    if failures:
        for failure in failures:
            print("FAIL", failure, file=sys.stderr)
        return 1
    print("G1 host regressions OK: bash routing, padded status, probe acceptance, startup and child descriptors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
