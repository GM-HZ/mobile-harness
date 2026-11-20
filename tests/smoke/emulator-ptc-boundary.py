"""Stress the PTC file proxy boundary with an actual model-driven run_code.

Two cases run in one PTC session against the real Host worker:

* self-privilege: the program cannot create symbolic or hard links, read link
  targets, change metadata, or open a file read-write;
* concurrent parent rename: the host renames the program's parent directory out
  of and back into the authorized root while the program reads and writes, and
  nothing lands outside the root.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import tarfile
import tempfile
import threading
import time
import uuid

host = runpy.run_path(str(Path(__file__).with_name("emulator-ptc-host.py")))
support = host["support"]
recovery = runpy.run_path(str(Path(__file__).with_name("emulator-recovery.py")))
continuation = runpy.run_path(str(Path(__file__).with_name("emulator-agent-continuation.py")))
WORKSPACE = support["WORKSPACE"]
FILES = recovery["FILES"]
PROFILE = recovery["PROFILE"]
ERRORS = {"ENOENT", "EACCES", "EXDEV", "ELOOP", "ENOTDIR", "EPERM"}
SELF_ERRORS = {"EPERM", "EACCES", "ENOSYS", "EINVAL"}


def session(emulator, evidence):
    workspace = emulator.rpc("workspace/create", {"request": {"path": WORKSPACE}})["workspace"]["workspaceId"]
    sid = emulator.rpc("session/create", {"request": {
        "workspaceId": workspace, "agentPreset": "ptc"}})["sessionId"]
    catalog = emulator.rpc("session/modelCatalog", {})
    provider = catalog["default"]["provider"]
    model = catalog["default"]["model"]
    emulator.rpc("session/selectModel", {"request": {
        "sessionId": sid, "provider": provider, "model": model, "reasoningEffort": "off"}})
    evidence["model"] = {"provider": provider, "model": model}
    return workspace, sid


def run_code(emulator, sid, description, script, marker):
    """Run one modeled run_code call and return its result text and end reason."""
    before = sum(row["type"] == "turn/end" for row in support["events"](emulator, sid))
    previous = {row["data"]["callId"] for row in support["events"](emulator, sid) if row["type"] == "tool/call"}
    host["prompt_run_code"](emulator, sid, description, script)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        events = support["events"](emulator, sid)
        ends = [row for row in events if row["type"] == "turn/end"]
        if len(ends) > before:
            calls = {row["data"]["callId"] for row in events if row["type"] == "tool/call"
                     and row["data"]["name"] == "run_code"} - previous
            for row in events:
                if row["type"] != "tool/result" or row["data"]["message"].get("toolCallId") not in calls:
                    continue
                message = row["data"]["message"]
                text = "\n".join(item.get("text", "") for item in message["content"])
                return {"result": text, "end": ends[-1]["data"]["reason"]["kind"],
                        "isError": message["isError"], "marker": marker in text}
            raise AssertionError("run_code result missing for " + description)
        time.sleep(0.25)
    print("run_code timeout; recent events:",
          [row["type"] for row in support["events"](emulator, sid)][-12:], flush=True)
    raise AssertionError("The modeled run_code turn did not finish: " + description)


def self_privilege(emulator, sid, evidence):
    name = "mh-ptc-links-" + uuid.uuid4().hex[:12]
    inside = f"{name}-inside.txt"
    written = f"{name}-written.txt"
    emulator.app(f"printf INSIDE > alpine/workspace-native/{inside}")
    script = f"""
var fs = await import('node:fs/promises');
const out = {{}};
async function attempt(key, run) {{
  try {{ await run(); out[key] = 'OK'; }}
  catch (error) {{ out[key] = error.code || String(error); }}
}}
await attempt('symlink', () => fs.symlink('{inside}', '{name}-link'));
await attempt('hardlink', () => fs.link('{inside}', '{name}-hard'));
await attempt('readlink', () => fs.readlink('{inside}'));
await attempt('chmod', () => fs.chmod('{inside}', 0o600));
await attempt('utimes', () => fs.utimes('{inside}', new Date(), new Date()));
await attempt('readWrite', () => fs.writeFile('{inside}', 'x', {{ flag: 'r+' }}));
await attempt('truncate', () => fs.truncate('{inside}', 1));
await attempt('read', () => fs.readFile('{inside}', 'utf8'));
await attempt('write', () => fs.writeFile('{written}', 'ok'));
console.log('MH_SELF_PRIVILEGE ' + JSON.stringify(out));
return 'MH_SELF_PRIVILEGE_DONE';
""".strip()
    result = run_code(emulator, sid, "PTC self-privilege boundary fixture", script, "MH_SELF_PRIVILEGE")
    assert not result["isError"], result["result"][:800]
    match = re.search(r"MH_SELF_PRIVILEGE (\{.*\})", result["result"], re.S)
    assert match, result["result"][:1200]
    outcome = json.loads(match.group(1))
    evidence["selfPrivilege"] = {"turnEnd": result["end"], "outcome": outcome}
    for key in ("symlink", "hardlink", "readlink", "chmod", "utimes", "readWrite", "truncate"):
        assert outcome[key] != "OK", (key, outcome)
        assert outcome[key] in SELF_ERRORS, (key, outcome[key])
    assert outcome["read"] == "OK" and outcome["write"] == "OK", outcome
    # Nothing the program tried may have left a link or truncated the file.
    assert emulator.app(f"test -L alpine/workspace-native/{name}-link && echo LEAK || echo clean") == "clean"
    assert emulator.app(f"test -e alpine/workspace-native/{name}-hard && echo LEAK || echo clean") == "clean"
    assert emulator.app(f"cat alpine/workspace-native/{inside}") == "INSIDE"
    evidence["selfPrivilegeContained"] = True
    emulator.app(f"rm -f alpine/workspace-native/{inside} alpine/workspace-native/{written} "
                 f"alpine/workspace-native/{name}-link alpine/workspace-native/{name}-hard")


ACTUATOR = "mh-ptc-actuator-"


def actuator_archive(destination, name):
    """Bundle whose apply() renames paths on request from the Host process."""
    command = f"{FILES}/alpine/workspace-native/{name}-cmd.json"
    result = f"{FILES}/alpine/workspace-native/{name}-result.json"
    source = f"""
import fs from 'node:fs';
export const name = {json.dumps(name)};
export function apply() {{
  const commandPath = {json.dumps(command)};
  const resultPath = {json.dumps(result)};
  let last = '';
  fs.writeFileSync(resultPath, JSON.stringify({{ ready: true }}));
  setInterval(() => {{
    let text;
    try {{ text = fs.readFileSync(commandPath, 'utf8'); }} catch {{ return; }}
    if (!text || text === last) return;
    last = text;
    let command;
    try {{ command = JSON.parse(text); }} catch {{ return; }}
    try {{
      fs.renameSync(command.from, command.to);
      fs.writeFileSync(resultPath, JSON.stringify({{ id: command.id, ok: true }}));
    }} catch (error) {{
      fs.writeFileSync(resultPath, JSON.stringify({{ id: command.id, ok: false, error: String(error.code || error) }}));
    }}
  }}, 100);
}}
""".strip()
    files = {
        "package.json": json.dumps({
            "name": name, "version": "1.0.0", "type": "module", "main": "index.js",
            "files": ["index.js", "cordis.patch.yml"], "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
        }).encode(),
        "cordis.patch.yml": f"- insert:\n    - id: {name}\n      name: {name}\n".encode(),
        "index.js": source.encode(),
    }
    with tarfile.open(destination, "w:gz", format=tarfile.USTAR_FORMAT) as archive:
        for filename, data in files.items():
            entry = tarfile.TarInfo(filename)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))


def install_actuator(device, name, evidence):
    remote = "/data/local/tmp/" + name
    folder = WORKSPACE + "/" + name
    with tempfile.TemporaryDirectory(prefix="mh-actuator-") as temporary:
        archive = Path(temporary) / "actuator.tgz"
        actuator_archive(archive, name)
        assert "FileTransfer finish" in device.hdc("file", "send", str(archive), remote + ".tgz")
        assert device.app(f"mkdir -p alpine/workspace-native/{name} && tar -xzf {remote}.tgz "
                          f"-C alpine/workspace-native/{name} && printf READY") == "READY"
    installed = device.rpc("pluginManager/installBundle", {
        "spec": f"file:{folder}", "options": {"enabled": False}}, timeout=120)
    assert installed.get("enabled") is False and installed.get("application") != "failed", installed
    enabled = device.rpc("pluginManager/setBundleEnabled", {"name": name, "enabled": True})
    assert enabled.get("application") != "failed", enabled
    device.stop()
    device.start()
    evidence["actuatorReadyMs"] = device.ready("normal")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if device.app(f"test -f alpine/workspace-native/{name}-result.json && printf READY") == "READY":
            return
        time.sleep(0.2)
    raise AssertionError("The Host rename actuator did not start")


def rename_via_actuator(device, name, source, destination, request_id, timeout=15):
    payload = base64.b64encode(json.dumps({"id": request_id, "from": source, "to": destination}).encode()).decode()
    assert device.app(f"printf '%s' '{payload}' | base64 -d > "
                      f"alpine/workspace-native/{name}-cmd.json && printf WROTE") == "WROTE"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = device.app(f"cat alpine/workspace-native/{name}-result.json 2>/dev/null || true")
        if raw:
            try:
                value = json.loads(raw)
            except ValueError:
                value = None
            if value and value.get("id") == request_id:
                return value
        time.sleep(0.05)
    raise AssertionError("The Host rename actuator did not answer")


def remove_actuator(device, name, original_manifest, original_boot, evidence):
    device.rpc("pluginManager/setBundleEnabled", {"name": name, "enabled": False})
    device.stop()
    for path, body in ((PROFILE + "/package.json", original_manifest),
                       ("mobile-harness-boot.json", original_boot)):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / "original"
            local.write_bytes(body)
            assert "FileTransfer finish" in device.hdc("file", "send", str(local), f"/data/local/tmp/{name}-restore")
            device.app(f"cp /data/local/tmp/{name}-restore {path}")
    device.app(f"rm -f /data/local/tmp/{name}-restore; rm -rf alpine/workspace-native/{name} "
               f"alpine/workspace-native/{name}-cmd.json alpine/workspace-native/{name}-result.json "
               f"alpine/workspace-native/{name}-ready alpine/workspace-native/{name}-log")
    device.start()
    device.ready("normal")
    restored = continuation["read_bytes"](device, PROFILE + "/package.json")
    assert restored == original_manifest, "The profile manifest was not restored"
    assert name not in json.loads(restored)["dsh"]["profile"]["bundles"], restored
    evidence["actuatorRemoved"] = True

def concurrent_parent_rename(emulator, sid, evidence, actuator):
    """Move the program's parent out of the granted root between two writes.

    The program waits on a host gate before each read/write pair, so each
    attempt is deterministically made while the directory is outside the root.
    """
    name = "mh-ptc-race-" + uuid.uuid4().hex[:12]
    workspace = "alpine/workspace-native"
    root = f"{workspace}/{name}"
    away = f"{workspace}/{name}-away"
    log_path = f"{workspace}/{name}-log"
    root_abs = FILES + "/" + root
    away_abs = FILES + "/" + away
    rounds = 4
    emulator.app(f"mkdir -p {root}/sub && printf ORIGINAL > {root}/sub/input.txt "
                 f"&& printf base > {root}/sub/output.txt")
    script = f"""
var fs = await import('node:fs/promises');
const log = [];
await fs.writeFile('{name}-ready', '1');
console.log('MH_RACE_READY');
for (let i = 0; i < {rounds}; i++) {{
  for (;;) {{
    try {{ await fs.readFile('{name}-gate' + i); break; }}
    catch (error) {{ if (error.code !== 'ENOENT') throw error; }}
    await new Promise(resolve => setTimeout(resolve, 20));
  }}
  try {{ log.push('r:' + (await fs.readFile('{name}/sub/input.txt', 'utf8'))); }}
  catch (error) {{ log.push('r!' + error.code); }}
  try {{ await fs.writeFile('{name}/sub/output.txt', 'moved-' + i); log.push('w'); }}
  catch (error) {{ log.push('w!' + error.code); }}
  await fs.writeFile('{name}-done' + i, '1');
}}
await fs.writeFile('{name}-log', log.join(','));
console.log('MH_RACE_LOG ' + log.join(','));
return 'MH_RACE_DONE';
""".strip()
    observations = {"rounds": []}
    thread_error = []

    def mover():
        try:
            print("mover: waiting for the program ready marker", flush=True)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if emulator.app(f"test -f {workspace}/{name}-ready && printf READY") == "READY":
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("The concurrent program never reached its ready marker")
            print("mover: program ready", flush=True)
            request = 0
            for index in range(rounds):
                request += 1
                forward = rename_via_actuator(emulator, actuator, root_abs, away_abs, request)
                print("mover: round", index, "renamed away", forward, flush=True)
                before = emulator.app(f"cat {away}/sub/output.txt")
                emulator.app(f"printf 1 > {workspace}/{name}-gate{index}")
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if emulator.app(f"test -f {workspace}/{name}-done{index} && printf DONE") == "DONE":
                        break
                    time.sleep(0.05)
                else:
                    raise AssertionError(f"The program did not finish moved round {index}")
                after = emulator.app(f"cat {away}/sub/output.txt")
                print("mover: round", index, "before=", before, "after=", after, flush=True)
                request += 1
                back = rename_via_actuator(emulator, actuator, away_abs, root_abs, request)
                observations["rounds"].append({"index": index, "forward": forward, "back": back,
                                               "before": before, "after": after})
                if not forward.get("ok") or not back.get("ok"):
                    raise AssertionError({"round": index, "forward": forward, "back": back})
        except BaseException as error:
            print("mover: failed", repr(error)[:800], flush=True)
            thread_error.append(error)

    thread = threading.Thread(target=mover)
    thread.start()
    try:
        result = run_code(emulator, sid, "PTC concurrent parent rename fixture", script, "MH_RACE_DONE")
        thread.join(timeout=180)
        assert not thread.is_alive(), "The rename loop did not finish"
        if thread_error:
            raise AssertionError(str(thread_error[0])[:1200])
        assert not result["isError"], result["result"][:800]
        match = re.search(r"MH_RACE_LOG ([^\n]*)", result["result"])
        assert match, result["result"][:1200]
        entries = [entry for entry in match.group(1).split(",") if entry]
        assert emulator.app(f"cat {log_path}") == ",".join(entries)
        assert len(entries) == rounds * 2, entries
        for index in range(rounds):
            read, write = entries[index * 2], entries[index * 2 + 1]
            assert read.startswith("r!") and read[2:] in ERRORS, (index, read, entries)
            assert write.startswith("w!") and write[2:] in ERRORS, (index, write, entries)
        # The moved directory must keep the content written before the move.
        for row in observations["rounds"]:
            assert row["before"] == row["after"], row
        assert emulator.app(f"cat {root}/sub/input.txt") == "ORIGINAL"
        assert emulator.app(f"test -e {root}/sub/output.txt && echo PRESENT || echo missing") == "PRESENT"
        assert emulator.app(f"test -e {away} && echo LEAK || echo clean") == "clean"
        evidence["concurrentParentRename"] = {
            "rounds": len(observations["rounds"]), "errorCodes": sorted({entry[2:] for entry in entries if "!" in entry}),
            "contained": True, "movedContentUnchanged": True,
            "renames": observations["rounds"],
        }
    finally:
        thread.join(timeout=5)
        if emulator.app(f"test -e {away} && echo AWAY || echo gone") == "AWAY":
            rename_via_actuator(emulator, actuator, away_abs, root_abs, 999)
        emulator.app("rm -rf " + root + " " + away + " " + log_path + " " +
                     " ".join(f"alpine/workspace-native/{name}-{suffix}{index}" for index in range(rounds)
                              for suffix in ("gate", "done")) +
                     f" alpine/workspace-native/{name}-ready alpine/workspace-native/{name}-log")


def run(device, args):
    evidence = {"target": args.target}
    workspace = None
    sid = None
    actuator = ACTUATOR + uuid.uuid4().hex[:10]
    manifest = boot = None
    try:
        evidence["readyMs"] = device.ready("normal")
        manifest = continuation["read_bytes"](device, PROFILE + "/package.json")
        boot = continuation["read_bytes"](device, "mobile-harness-boot.json")
        evidence["manifestBeforeSha256"] = hashlib.sha256(manifest).hexdigest()
        install_actuator(device, actuator, evidence)
        workspace, sid = session(device, evidence)
        self_privilege(device, sid, evidence)
        concurrent_parent_rename(device, sid, evidence, actuator)
    finally:
        if sid:
            try:
                device.rpc("session/cancel", {"request": {"sessionId": sid}})
            except Exception:
                pass
        if workspace:
            try:
                evidence["workspaceDeleted"] = device.rpc("workspace/delete", {"request": {"workspaceId": workspace}})
            except Exception as error:
                evidence["workspaceDeleted"] = str(error)[:200]
        device.app("rm -rf alpine/workspace-native/mh-ptc-links-* alpine/workspace-native/mh-ptc-race-*")
        if manifest is not None and boot is not None:
            remove_actuator(device, actuator, manifest, boot, evidence)
            evidence["manifestAfterSha256"] = hashlib.sha256(
                continuation["read_bytes"](device, PROFILE + "/package.json")).hexdigest()
            assert evidence["manifestAfterSha256"] == evidence["manifestBeforeSha256"]
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--host-port", type=int, default=19664)
    args = parser.parse_args()
    emulator = support["Emulator"](args.target, args.host_port)
    bridge = (f"tcp:{args.host_port}", "tcp:19592")
    if "Forwardport result:OK" not in emulator.hdc("fport", *bridge):
        raise SystemExit("Could not forward the loopback Web port")
    try:
        output = run(emulator, args)
    finally:
        emulator.hdc("fport", "rm", *bridge)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("selfPrivilege", "concurrentParentRename")},
                     ensure_ascii=False))
