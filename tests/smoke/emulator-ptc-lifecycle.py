"""Verify fixture-owned AgentHandle disposal through real model-driven PTC sessions."""
import argparse
import io
import json
import os
from pathlib import Path
import runpy
import tarfile
import tempfile
import time
import uuid

ptc = runpy.run_path(str(Path(__file__).with_name("emulator-ptc-host.py")))
support = ptc["support"]
PROFILE = "alpine/native-benchmark-home/profiles/web"
PATCH = ptc["PTC_PROFILE_PATCH"]


def fixture_archive(destination, name):
    manifest = Path(__file__).resolve().parents[2] / "runtime/harmonyos/dsh/package.json"
    version = json.loads(manifest.read_text())["dependencies"]["@deepseek-ai/dsh"]
    packages = support["WORKSPACE"].rsplit("/", 1)[0] + f"/.dsh-{version}/dsh/node_modules/@deepseek-ai/"
    source = Path(__file__).with_name("fixtures").joinpath("ptc-lifecycle.mjs").read_text()
    source = source.replace("__MH_DSH_PACKAGES__", json.dumps("file://" + packages))
    source = source.replace("__MH_WORKSPACE__", json.dumps(support["WORKSPACE"]))
    files = {
        "package.json": json.dumps({
            "name": name, "version": "1.0.0", "type": "module", "main": "index.js",
            "files": ["index.js", "cordis.patch.yml"], "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
        }),
        "cordis.patch.yml": f"- insert:\n    - id: {name}\n      name: {name}\n",
        "index.js": source,
    }
    with tarfile.open(destination, "w:gz", format=tarfile.USTAR_FORMAT) as archive:
        for filename, contents in files.items():
            data = contents.encode()
            entry = tarfile.TarInfo(filename)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))


def fixture_command(emulator, driver, action, case):
    previous = support["events"](emulator, driver)
    old_calls = {row["data"]["callId"] for row in previous if row["type"] == "tool/call"}
    old_turns = sum(row["type"] == "turn/end" for row in previous)
    args = {"action": action, "case": case}
    emulator.rpc("session/prompt", {"request": {
        "sessionId": driver, "requestId": str(uuid.uuid4()), "mode": "queue",
        "content": [{"type": "text", "text": "Call mh_ptc_lifecycle once with precisely " +
                     json.dumps(args) + ". Return its result and take no other action."}],
    }})
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        rows = support["events"](emulator, driver)
        if sum(row["type"] == "turn/end" for row in rows) > old_turns:
            calls = {row["data"]["callId"] for row in rows
                     if row["type"] == "tool/call" and row["data"]["name"] == "mh_ptc_lifecycle"} - old_calls
            for row in rows:
                if row["type"] != "tool/result":
                    continue
                message = row["data"]["message"]
                if message.get("toolCallId") in calls:
                    text = "\n".join(item.get("text", "") for item in message["content"])
                    assert not message["isError"], text[:1800]
                    return json.loads(text)
            break
        time.sleep(0.25)
    raise AssertionError(f"No lifecycle tool result for {action} {case}")


def verify(emulator, mode, evidence):
    workspace = emulator.rpc("workspace/create", {"request": {"path": support["WORKSPACE"]}})["workspace"]["workspaceId"]
    driver = emulator.rpc("session/create", {"request": {"workspaceId": workspace, "agentPreset": "standard"}})["sessionId"]
    emulator.rpc("session/selectModel", {"request": {
        "sessionId": driver, "provider": "deepseek-official", "model": "deepseek-flash", "reasoningEffort": "off",
    }})
    for case in ("idle", "active"):
        created = fixture_command(emulator, driver, "create", case)
        assert not created["disposed"] and created["agentRegistered"] and created["sessionRegistered"], created
        sid = created["sessionId"]
        prior = {row["id"] for row in ptc["workers"](emulator)}
        marker = "MH_DISPOSE_" + uuid.uuid4().hex.upper()
        ptc["complete_code"](emulator, sid, "Initialize an owner-retained value",
                             f'var fixtureOwned: string = "{marker}"; fixtureOwned', marker)
        admitted = {row["id"] for row in ptc["workers"](emulator)
                    if row["event"] == "ptc-worker-admitted" and row["id"] not in prior}
        assert len(admitted) == 1, admitted
        worker = next(iter(admitted))
        assert not any(row["event"] == "ptc-worker-reaped" and row["id"] == worker for row in ptc["workers"](emulator))
        ready_name = "mh-ptc-dispose-" + uuid.uuid4().hex[:12]
        ready_file = f"alpine/workspace-native/{ready_name}"
        try:
            if case == "active":
                ptc["prompt_run_code"](emulator, sid, "Enter a marked synchronous loop for owner disposal",
                                      "var disposalFs = await import('node:fs/promises'); "
                                      f"await disposalFs.writeFile('{ready_name}', 'ready'); for (;;) {{}}")
                deadline = time.monotonic() + 30
                while emulator.app(f"test -f {ready_file} && printf READY") != "READY":
                    if time.monotonic() >= deadline:
                        raise AssertionError("The owned Agent did not enter its active PTC program")
                    time.sleep(0.15)
            disposed = fixture_command(emulator, driver, "dispose", case)
            assert disposed["sessionId"] == sid and disposed["disposed"], disposed
            assert not disposed["agentRegistered"] and not disposed["sessionRegistered"], disposed
            assert any(row["event"] == "ptc-worker-reaped" and row["id"] == worker for row in ptc["workers"](emulator))
            evidence[case] = {
                "ownedHandleDisposed": True, "agentUnregistered": True, "sessionUnregistered": True,
                "workerReaped": True, "disposeMs": disposed["disposeMs"],
            }
            prior_resume = {row["id"] for row in ptc["workers"](emulator)}
            emulator.rpc("session/selectModel", {"request": {
                "sessionId": sid, "provider": "deepseek-official", "model": "deepseek-flash", "reasoningEffort": "off",
            }})
            ptc["complete_code"](emulator, sid, "Resume the durable session with fresh PTC state",
                                 '"MH_FRESH_" + typeof fixtureOwned', "MH_FRESH_undefined")
            assert sum(row["event"] == "ptc-worker-admitted" and row["id"] not in prior_resume
                       for row in ptc["workers"](emulator)) == 1
            evidence[case]["durableSessionResumedWithFreshWorker"] = True
        finally:
            emulator.app(f"rm -f {ready_file}")
    evidence["executionMode"] = mode


def run(emulator, mode, evidence):
    name = "mh-ptc-lifecycle-" + uuid.uuid4().hex[:12]
    remote = "/data/local/tmp/" + name
    backup = f"{PROFILE}/package.json.{name}"
    lock_backup = f"{PROFILE}/pnpm-lock.yaml.{name}"
    boot_backup = f"mobile-harness-boot.json.{name}"
    forward = ("tcp:19649", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    saved = False
    had_lock = False
    try:
        emulator.ready("normal")
        assert emulator.app(f"test ! -e {PATCH} && printf EMPTY") == "EMPTY"
        assert emulator.app(f"cp {PROFILE}/package.json {backup} && printf SAVED") == "SAVED"
        assert emulator.app(f"cp mobile-harness-boot.json {boot_backup} && printf SAVED") == "SAVED"
        saved = True
        lock_state = emulator.app(f"if test -e {PROFILE}/pnpm-lock.yaml; then printf PRESENT; else printf ABSENT; fi")
        assert lock_state in ("PRESENT", "ABSENT"), lock_state
        had_lock = lock_state == "PRESENT"
        if had_lock:
            assert emulator.app(f"cp {PROFILE}/pnpm-lock.yaml {lock_backup} && printf SAVED") == "SAVED"
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            archive = temporary / "fixture.tgz"
            fixture_archive(archive, name)
            assert "FileTransfer finish" in emulator.hdc("file", "send", str(archive), remote + ".tgz")
            assert emulator.app(f"mkdir alpine/workspace-native/{name} && "
                                f"tar -xzf {remote}.tgz -C alpine/workspace-native/{name} && printf READY") == "READY"
            installed = emulator.rpc("pluginManager/installBundle", {
                "spec": f"file:{support['WORKSPACE']}/{name}", "options": {"enabled": False},
            }, timeout=90)
            assert installed.get("enabled") is False, installed
            emulator.stop()
            profile = json.loads(emulator.app(f"cat {PROFILE}/package.json"))
            profile["dsh"]["profile"]["bundles"].append(name)
            manifest = temporary / "package.json"
            manifest.write_text(json.dumps(profile) + "\n")
            patch = temporary / "cordis.patch.yml"
            patch.write_text("- id: ptc-runtime\n  config:\n"
                             f"    executionMode: {mode}\n"
                             f"    scriptPersistence: {str(mode == 'vm-script').lower()}\n")
            for file, extension, target in ((manifest, ".json", f"{PROFILE}/package.json"), (patch, ".yml", PATCH)):
                assert "FileTransfer finish" in emulator.hdc("file", "send", str(file), remote + extension)
                assert emulator.app(f"cp {remote}{extension} {target} && printf COPIED") == "COPIED"
        emulator.start()
        evidence["readyMs"] = emulator.ready("normal")
        with support["model_key"](emulator):
            verify(emulator, mode, evidence)
        evidence["temporaryModelCredentialRemoved"] = True
    finally:
        try:
            if saved:
                emulator.stop()
                assert emulator.app(f"cp {backup} {PROFILE}/package.json && "
                                    f"cmp -s {backup} {PROFILE}/package.json && printf RESTORED") == "RESTORED"
                if had_lock:
                    assert emulator.app(f"cp {lock_backup} {PROFILE}/pnpm-lock.yaml && "
                                        f"cmp -s {lock_backup} {PROFILE}/pnpm-lock.yaml && printf RESTORED") == "RESTORED"
                else:
                    emulator.app(f"rm -f {PROFILE}/pnpm-lock.yaml")
                assert emulator.app(f"cp {boot_backup} mobile-harness-boot.json && "
                                    f"cmp -s {boot_backup} mobile-harness-boot.json && printf RESTORED") == "RESTORED"
                emulator.app(f"rm -f {PATCH} {backup} {lock_backup} {boot_backup}; "
                             f"rm -rf alpine/workspace-native/{name} {PROFILE}/node_modules/{name}")
                emulator.start()
                emulator.ready("normal")
                evidence["originalProfileRestored"] = True
        finally:
            emulator.hdc("shell", "rm", "-f", remote + ".tgz", remote + ".json", remote + ".yml")
            emulator.hdc("fport", "rm", *forward)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=("persistent-in-memory", "vm-script"), default="persistent-in-memory")
    options = parser.parse_args()
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"):
        parser.error("MH_TEST_DEEPSEEK_API_KEY is required")
    emulator = support["Emulator"](options.target, 19649)
    evidence = {}
    try:
        run(emulator, options.mode, evidence)
    finally:
        options.output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
