"""Run the experimental HarmonyOS PTC adapter through an actual DSH session."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import runpy
import re
import shlex
import time
import uuid

support = runpy.run_path(str(Path(__file__).with_name("emulator-dsh-capabilities.py")))
PTC_PROFILE_PATCH = "alpine/native-benchmark-home/cordis.patch.yml"


def model_session(emulator, workspace):
    session = emulator.rpc("session/create", {"request": {"workspaceId": workspace, "agentPreset": "ptc"}})
    assert session.get("agentPreset") == "ptc", session
    sid = session["sessionId"]
    emulator.rpc("session/selectModel", {"request": {
        "sessionId": sid, "provider": "deepseek-official", "model": "deepseek-flash", "reasoningEffort": "off",
    }})
    return sid


def prompt_run_code(emulator, sid, description, script):
    prompt = "This is a local PTC regression fixture. Call run_code once, using precisely this JSON: " + json.dumps({
        "description": description, "code": script,
    }) + ". Use the tool to get the result."
    emulator.rpc("session/prompt", {"request": {
        "sessionId": sid, "requestId": str(uuid.uuid4()), "mode": "queue",
        "content": [{"type": "text", "text": prompt}],
    }})


def workers(emulator):
    trace = emulator.app("grep ptc-worker alpine/tmp/dsh-native-timeline.log || true")
    return [json.loads(row) for row in trace.splitlines()]


@contextmanager
def profile_mode(emulator, execution_mode, script_persistence, read_only):
    if not (execution_mode or read_only):
        yield
        return
    patch = ""
    if execution_mode:
        patch += ("- id: ptc-runtime\n  config:\n"
                  f"    executionMode: {execution_mode}\n"
                  f"    scriptPersistence: {str(script_persistence).lower()}\n")
    if read_only:
        patch += "- id: sandbox-policy\n  config:\n    mode: read-only\n"
    emulator.stop()
    try:
        # noclobber ensures an existing user patch never changes.
        result = emulator.app(f"set -C; printf %s {shlex.quote(patch)} > {PTC_PROFILE_PATCH} && printf CREATED")
        if result != "CREATED":
            raise RuntimeError("The mode fixture requires an empty profile patch slot")
        try:
            emulator.start()
            yield
        finally:
            try:
                emulator.stop()
            finally:
                emulator.app(f"rm -f {PTC_PROFILE_PATCH}")
    finally:
        emulator.start()
        emulator.ready("normal")


def complete_code(emulator, sid, description, script, result_marker):
    prior = support["events"](emulator, sid)
    before = sum(row["type"] == "turn/end" for row in prior)
    previous = {row["data"]["callId"] for row in prior if row["type"] == "tool/call"}
    prompt_run_code(emulator, sid, description, script)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        events = support["events"](emulator, sid)
        if sum(row["type"] == "turn/end" for row in events) > before:
            calls = {row["data"]["callId"] for row in events
                     if row["type"] == "tool/call" and row["data"]["name"] == "run_code"} - previous
            for row in events:
                if row["type"] != "tool/result":
                    continue
                message = row["data"]["message"]
                if message.get("toolCallId") not in calls:
                    continue
                result = "\n".join(item.get("text", "") for item in message["content"])
                assert not message["isError"] and result_marker in result, result[:1400]
                return
            break
        time.sleep(0.25)
    raise AssertionError(f"No completed run_code result for {description}")


def abort_retained_turn(emulator, sid, fixture, script, after_cancel):
    before = sum(row["type"] == "turn/end" for row in support["events"](emulator, sid))
    prompt_run_code(emulator, sid, "Run a controlled cancellation fixture", script)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if emulator.app(f"test -f {fixture} && printf READY") == "READY":
            break
        events = support["events"](emulator, sid)
        if sum(row["type"] == "turn/end" for row in events) > before:
            raise AssertionError("The cancellation program ended without reaching its ready marker")
        time.sleep(0.1)
    else:
        raise AssertionError("The cancellation program never wrote its ready marker")

    started = time.monotonic()
    assert emulator.rpc("session/cancel", {"request": {"sessionId": sid}})["accepted"]
    after_cancel()
    deadline = started + 12
    while time.monotonic() < deadline:
        turns = [row["data"]["reason"]["kind"] for row in support["events"](emulator, sid) if row["type"] == "turn/end"]
        if len(turns) > before:
            assert turns[before] == "aborted", turns[before]
            return round((time.monotonic() - started) * 1000)
        time.sleep(0.15)
    raise AssertionError("DSH did not settle the canceled retained turn")


def verify_retained_cancellation(emulator, sid, worker_id, marker, evidence):
    name = "mh-ptc-cancel-" + uuid.uuid4().hex[:12]
    ready = f"alpine/workspace-native/{name}-ready"
    gate = f"alpine/workspace-native/{name}-gate"
    stopped = f"alpine/workspace-native/{name}-stopped"
    try:
        cooperative = f"""
var workerFs = await import('node:fs/promises');
await workerFs.writeFile('{name}-ready', 'ready', {{ flag: 'wx' }});
for (;;) {{
  try {{ await workerFs.readFile('{name}-gate'); break; }}
  catch (error) {{ if (error.code !== 'ENOENT') throw error; }}
  await new Promise(resolve => setTimeout(resolve, 30));
}}
fixtureValue
""".strip()
        coop_ms = abort_retained_turn(emulator, sid, ready, cooperative,
                                     lambda: emulator.app(f"printf done > {gate}"))
        complete_code(emulator, sid, "Read the retained value after cooperative cancellation", "fixtureValue", marker)
        trace = workers(emulator)
        assert not any(row["event"] == "ptc-worker-reaped" and row["id"] == worker_id for row in trace)

        blocking = f"""
await workerFs.writeFile('{name}-stopped', 'ready', {{ flag: 'wx' }});
for (;;) {{}}
""".strip()
        forced_ms = abort_retained_turn(emulator, sid, stopped, blocking, lambda: None)
        trace = workers(emulator)
        assert any(row["event"] == "ptc-worker-reaped" and row["id"] == worker_id for row in trace)
        previous = {row["id"] for row in trace}
        complete_code(emulator, sid, "Verify forced cancellation cleared the retained variables",
                      '"MH_TYPE_" + typeof fixtureValue', "MH_TYPE_undefined")
        assert sum(row["event"] == "ptc-worker-admitted" and row["id"] not in previous for row in workers(emulator)) == 1
        evidence.update(cooperativeCancellationPreservedState=True, cooperativeCancellationMs=coop_ms,
                        blockingCancellationReapedWorker=True, blockingCancellationMs=forced_ms,
                        nextTurnStartedWithFreshState=True)
    finally:
        emulator.app(f"rm -f {ready} {gate} {stopped}")


def verify_mode(emulator, execution_mode, script_persistence, evidence):
    retained = script_persistence or execution_mode == "persistent-in-memory"
    marker = "MH_RETAINED_" + uuid.uuid4().hex.upper()
    ws = emulator.rpc("workspace/create", {"request": {"path": support["WORKSPACE"]}})["workspace"]["workspaceId"]
    sid = model_session(emulator, ws)
    other = model_session(emulator, ws)
    def admitted():
        return {row["id"] for row in workers(emulator) if row["event"] == "ptc-worker-admitted"}

    baseline = admitted()
    complete_code(emulator, sid, "Declare a typed variable with top-level await",
                  f'var fixtureValue: string = await Promise.resolve("{marker}"); fixtureValue', marker)
    first = admitted() - baseline
    assert len(first) == 1, first
    query = '"MH_TYPE_" + typeof fixtureValue'
    complete_code(emulator, sid, "Read the variable from the previous turn", query,
                  "MH_TYPE_string" if retained else "MH_TYPE_undefined")
    expected_workers = 1 if retained else 2
    assert len(admitted() - baseline) == expected_workers
    complete_code(emulator, other, "Check state isolation in a different session", query, "MH_TYPE_undefined")
    assert len(admitted() - baseline) == expected_workers + 1
    evidence.update(executionMode=execution_mode, scriptPersistence=script_persistence, topLevelAwait=True,
                    sameSessionRetained=retained, otherSessionIsolated=True,
                    admittedWorkers=len(admitted() - baseline))
    if retained:
        verify_retained_cancellation(emulator, sid, next(iter(first)), marker, evidence)
        verify_working_directory(emulator, ws, evidence, sid, True)


def verify_cancel(emulator, workspace, evidence):
    prior = {entry["id"] for entry in workers(emulator)}
    sid = model_session(emulator, workspace)
    prompt_run_code(emulator, sid, "Start a timer so the test can cancel the worker",
                    "const delay: number = 12000; await new Promise(resolve => setTimeout(resolve, delay)); return 7;")
    deadline = time.monotonic() + 25
    active = []
    while time.monotonic() < deadline:
        trace = workers(emulator)
        retired = {entry["id"] for entry in trace if entry["event"] == "ptc-worker-reaped"}
        active = [entry["id"] for entry in trace if entry["event"] == "ptc-worker-admitted"
                  and entry["id"] not in prior | retired]
        if active:
            break
        if any(event["type"] == "turn/end" for event in support["events"](emulator, sid)):
            break
        time.sleep(0.2)
    assert len(active) == 1, "No active PTC worker to cancel"
    assert emulator.rpc("session/cancel", {"request": {"sessionId": sid}})["accepted"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        events = support["events"](emulator, sid)
        aborted = any(row["type"] == "turn/end" and row["data"]["reason"]["kind"] == "aborted" for row in events)
        reaped = any(entry["event"] == "ptc-worker-reaped" and entry["id"] == active[0] for entry in workers(emulator))
        if aborted and reaped:
            evidence.update(cancelledViaSession=True, cancelledWorkerReaped=True)
            return
        time.sleep(0.2)
    raise AssertionError("The session did not report cancellation and confirmed worker exit")


def verify_read_only(emulator, evidence):
    name = "mh-ptc-read-only-" + uuid.uuid4().hex[:12]
    original = f"alpine/workspace-native/{name}.txt"
    new = f"alpine/workspace-native/{name}-new.txt"
    directory = f"alpine/workspace-native/{name}"
    ws = emulator.rpc("workspace/create", {"request": {"path": support["WORKSPACE"]}})["workspace"]["workspaceId"]
    try:
        emulator.app(f"printf frozen > {original} && mkdir {directory}")
        script = f"""
const fs = await import('node:fs/promises');
const metadata: boolean = (await fs.stat('{name}.txt')).isFile() && (await fs.lstat('{name}')).isDirectory();
const denied: string[] = [];
for (const [name, operation] of [
  ['overwrite', () => fs.writeFile('{name}.txt', 'changed')],
  ['append', () => fs.appendFile('{name}.txt', 'changed')],
  ['create', () => fs.writeFile('{name}-new.txt', 'changed', {{flag: 'wx'}})],
  ['rename', () => fs.rename('{name}.txt', '{name}-new.txt')],
  ['unlink', () => fs.unlink('{name}.txt')],
  ['mkdir', () => fs.mkdir('{name}-new-dir')],
  ['rmdir', () => fs.rmdir('{name}')]
]) {{
  try {{ await operation(); }}
  catch (error) {{ if (error.code === 'EACCES') denied.push(name); else throw error; }}
}}
return (await fs.readFile('{name}.txt', 'utf8')) + ':' + denied.join(',') + ':' + metadata;
""".strip()
        complete_code(emulator, model_session(emulator, ws), "Verify read-only write restrictions",
                      script, "frozen:overwrite,append,create,rename,unlink,mkdir,rmdir:true")
        assert emulator.app(f"cat {original}; test ! -e {new} && test -d {directory} "
                            f"&& test ! -e {directory}-new-dir && printf ':unchanged'") == "frozen:unchanged"
        assert any(row.get("mode") == "read-only" for row in workers(emulator))
        evidence.update(readOnlyReadsAllowed=True, readOnlyWritesDenied=True, readOnlyDirectoryMutationsDenied=True,
                        readOnlyDiskUnchanged=True, readOnlyMetadataAllowed=True)
    finally:
        emulator.app(f"rm -f {original} {new}; rm -rf {directory} {directory}-new-dir")


def verify_directory_operations(emulator, workspace, evidence):
    name = "mh-ptc-directory-" + uuid.uuid4().hex[:12]
    marker = "HARMONY_MOVED_" + uuid.uuid4().hex.upper()
    absolute = f"{support['WORKSPACE']}/{name}"
    root = f"alpine/workspace-native/{name}"
    outside = f"alpine/{name}"
    try:
        emulator.app(f"mkdir {outside}; printf %s {marker} > {outside}/outside.txt; "
                     f"printf %s {marker} > {root}.txt")
        script = f"""
const fs = await import('node:fs/promises');
await fs.mkdir('{name}');
await fs.mkdir('{name}/left');
await fs.mkdir('{name}/right');
await fs.rename('{name}.txt', '{name}/left/input.txt');
const moved = await fs.readFile('{name}/left/input.txt', 'utf8');
await fs.rename('{name}/left/input.txt', '{absolute}/right/moved.txt');
const denied: string[] = [];
for (const [name, operation] of [
  ['move-out', () => fs.rename('{name}/right/moved.txt', '../{name}/target.txt')],
  ['move-in', () => fs.rename('../{name}/outside.txt', '{name}/right/stolen.txt')],
  ['unlink-out', () => fs.unlink('../{name}/outside.txt')],
  ['mkdir-out', () => fs.mkdir('../{name}/directory')],
  ['remove-root', () => fs.rmdir('.')]
]) {{
  try {{ await operation(); }}
  catch (error) {{
    if (['EACCES', 'EXDEV', 'EPERM'].includes(error.code)) denied.push(name);
    else throw error;
  }}
}}
let notEmpty = false;
try {{ await fs.rmdir('{name}/right'); }}
catch (error) {{ if (error.code !== 'ENOTEMPTY') throw error; notEmpty = true; }}
const contents = await fs.readFile('{name}/right/moved.txt', 'utf8');
await fs.unlink('{name}/right/moved.txt');
await fs.rmdir('{name}/right');
await fs.rename('{name}/left', '{name}/renamed');
await fs.rmdir('{name}/renamed');
await fs.rmdir('{name}');
return [moved, contents, denied.join(','), String(notEmpty)].join(':');
""".strip()
        complete_code(emulator, model_session(emulator, workspace),
                      "Verify directory operations under workspace-write", script,
                      f"{marker}:{marker}:move-out,move-in,unlink-out,mkdir-out,remove-root:true")
        assert emulator.app(f"test ! -e {root} && test ! -e {root}.txt && cat {outside}/outside.txt") == marker
        assert emulator.app(f"test ! -e {outside}/target.txt && test ! -e {outside}/directory && printf OK") == "OK"
        evidence.update(directoryOperationsMatched=True, crossBoundaryDirectoryMutationsDenied=True,
                        nonemptyDirectoryPreserved=True)
    finally:
        emulator.app(f"rm -rf {root} {root}.txt {outside}")


def verify_recursive_metadata(emulator, workspace, evidence):
    name = "mh-ptc-recursive-" + uuid.uuid4().hex[:12]
    directory = f"alpine/workspace-native/{name}"
    outside = f"alpine/{name}"
    marker = "MH_RECURSIVE_" + uuid.uuid4().hex.upper()
    try:
        emulator.app(f"mkdir {outside} && printf %s {marker} > {outside}/private.txt")
        script = f"""
const fs = await import('node:fs/promises');
await fs.mkdir('{name}/left/right', {{ recursive: true }});
await fs.mkdir('{name}/left/right', {{ recursive: true }});
await fs.writeFile('{name}/left/right/item.txt', '{marker}');
const info = await fs.stat('{name}/left/right/item.txt');
const directory = await fs.lstat('{name}/left/right');
const files = (await fs.readdir('{name}', {{ recursive: true }})).sort().join(',');
let missing = false;
try {{ await fs.stat('{name}/missing'); }}
catch (error) {{ if (error.code !== 'ENOENT') throw error; missing = true; }}
const denied: string[] = [];
for (const [name, operation] of [
  ['stat', () => fs.stat('../{name}/private.txt')],
  ['lstat', () => fs.lstat('../{name}/private.txt')],
  ['readdir', () => fs.readdir('../{name}', {{ recursive: true }})],
  ['rm', () => fs.rm('../{name}', {{ recursive: true }})]
]) {{
  try {{ await operation(); }}
  catch (error) {{
    if (['EACCES', 'EXDEV', 'EPERM'].includes(error.code)) denied.push(name);
    else throw error;
  }}
}}
const text = await fs.readFile('{name}/left/right/item.txt', 'utf8');
await fs.rm('{name}', {{ recursive: true }});
return [text, info.isFile(), info.size, directory.isDirectory(), files, missing, denied.join(',')].join(':');
""".strip()
        complete_code(emulator, model_session(emulator, workspace), "Verify recursive file operations and metadata",
                      script, f"{marker}:true:{len(marker)}:true:left,left/right,left/right/item.txt:true:stat,lstat,readdir,rm")
        assert emulator.app(f"test ! -e {directory} && cat {outside}/private.txt") == marker
        evidence.update(metadataMatched=True, recursiveDirectoryOperationsMatched=True,
                        outsideMetadataAndTraversalDenied=True)
    finally:
        emulator.app(f"rm -rf {directory} {outside}")


def verify_working_directory(emulator, workspace, evidence, sid=None, retained=False):
    name = "mh-ptc-cwd-" + uuid.uuid4().hex[:12]
    marker = "MH_CWD_" + uuid.uuid4().hex.upper()
    directory = f"alpine/workspace-native/{name}"
    absolute = f"{support['WORKSPACE']}/{name}"
    if sid is None:
        sid = model_session(emulator, workspace)
    result = "" if retained else "return "
    try:
        emulator.app(f"mkdir {directory}; printf %s {marker} > {directory}/input.txt")
        script = f"""
var cwdFs = await import('node:fs/promises');
process.chdir('{name}');
var cwdText = await cwdFs.readFile('input.txt', 'utf8');
await cwdFs.writeFile('output.txt', cwdText);
var cwdDenied = false;
try {{ process.chdir('../..'); }} catch (error) {{ cwdDenied = true; }}
var cwdMatches = process.cwd() === '{absolute}';
process.chdir('..');
{result}[cwdText, cwdDenied, cwdMatches, process.cwd() === '{support['WORKSPACE']}'].join(':');
""".strip()
        complete_code(emulator, sid, "Verify process working directory changes", script, f"{marker}:true:true:true")
        assert emulator.app(f"cat {directory}/output.txt") == marker
        complete_code(emulator, sid, "Select a subdirectory for the next session program",
                      f"await tools.working_directory({{ cd: '{name}' }}); {result}'MH_DIRECTORY_SELECTED';",
                      "MH_DIRECTORY_SELECTED")
        complete_code(emulator, sid, "Run the next PTC process in the selected directory",
                      f"var cwdFs = await import('node:fs/promises'); "
                      f"var cwdText = await cwdFs.readFile('input.txt', 'utf8'); "
                      f"await tools.working_directory({{ cd: '..' }}); {result}cwdText;", marker)
        evidence.update(processDirectoryChangesMatched=True, outsideDirectoryChangeDenied=True,
                        nextTurnStartedInSubdirectory=True)
        if retained:
            complete_code(emulator, sid, "Check retained program state after the session directory changes",
                          "cwdText", marker)
            evidence["retainedStateSurvivedDirectoryChange"] = True
    finally:
        emulator.app(f"rm -rf {directory}")


def verify(emulator, evidence):
    name = "mh-ptc-" + uuid.uuid4().hex[:12]
    marker = "HARMONY_PTC_" + uuid.uuid4().hex.upper()
    inside = f"alpine/workspace-native/{name}.txt"
    outside = f"alpine/{name}.txt"
    created = f"alpine/workspace-native/{name}-created.txt"
    try:
        emulator.app(f"printf %s {marker} > {inside} && printf %s outside > {outside}")
        ws = emulator.rpc("workspace/create", {"request": {"path": support["WORKSPACE"]}})["workspace"]
        sid = model_session(emulator, ws["workspaceId"])
        script = f"""
const fs = await import('node:fs/promises');
const text: string = await fs.readFile('{name}.txt', 'utf8');
const nested = await tools.read({{ file_path: '{name}.txt' }});
const nestedRead: boolean = JSON.stringify(nested).includes(text);
await fs.writeFile('{name}-created.txt', text, {{ flag: 'wx' }});
await fs.writeFile('{name}.txt', 'replaced');
await fs.appendFile('{name}.txt', ':appended');
let denied: boolean = false;
try {{ await fs.readFile('../{name}.txt', 'utf8'); }}
catch (error) {{ denied = error.code === 'EXDEV' || error.code === 'EACCES' || error.code === 'EPERM'; }}
let outsideWriteDenied: boolean = false;
try {{ await fs.writeFile('../{name}.txt', 'changed'); }}
catch (error) {{ outsideWriteDenied = error.code === 'EXDEV' || error.code === 'EACCES' || error.code === 'EPERM'; }}
let duplicateDenied: boolean = false;
try {{ await fs.writeFile('{name}-created.txt', 'changed', {{ flag: 'wx' }}); }}
catch (error) {{ duplicateDenied = error.code === 'EEXIST'; }}
return {{ text, denied, nestedRead, outsideWriteDenied, duplicateDenied }};
""".strip()
        prompt_run_code(emulator, sid, "Verify workspace read, write and denial", script)
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            events = support["events"](emulator, sid)
            calls = {event["data"]["callId"] for event in events
                     if event["type"] == "tool/call" and event["data"]["name"] == "run_code"}
            results = [event["data"]["message"] for event in events if event["type"] == "tool/result"
                       and event["data"]["message"].get("toolCallId") in calls]
            if results:
                evidence["runCodeObserved"] = True
                result = "\n".join(item.get("text", "") for item in results[0]["content"])
                assert not results[0]["isError"] and marker in result and re.search(r'\"denied\"\s*:\s*true', result), result[:2200]
                assert emulator.app(f"cat {created}") == marker
                assert emulator.app(f"cat {inside}") == "replaced:appended"
                assert emulator.app(f"cat {outside}") == "outside"
                assert re.search(r'\"nestedRead\"\s*:\s*true', result), result[:2200]
                assert re.search(r'\"outsideWriteDenied\"\s*:\s*true', result), result[:2200]
                assert re.search(r'\"duplicateDenied\"\s*:\s*true', result), result[:2200]
                evidence.update(typeScriptResultReturned=True, fileContentsMatched=True, outsideReadDenied=True,
                                nestedHostToolMatched=True, overwriteAndAppendMatched=True,
                                outsideWriteDenied=True, exclusiveCreatePreservedExisting=True)
                verify_directory_operations(emulator, ws["workspaceId"], evidence)
                verify_recursive_metadata(emulator, ws["workspaceId"], evidence)
                verify_working_directory(emulator, ws["workspaceId"], evidence)
                verify_cancel(emulator, ws["workspaceId"], evidence)
                return
            if any(event["type"] == "turn/end" for event in events):
                break
            time.sleep(0.25)
        raise AssertionError(f"run_code did not complete: {[event['type'] for event in events]}")
    finally:
        emulator.app(f"rm -f {inside} {outside} {created}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=("persistent-in-memory", "vm-script"))
    parser.add_argument("--script-persistence", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    options = parser.parse_args()
    if options.script_persistence and options.mode != "vm-script":
        parser.error("--script-persistence requires --mode vm-script")
    if options.mode and options.read_only:
        parser.error("--read-only exercises per-call mode")
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"):
        raise SystemExit("MH_TEST_DEEPSEEK_API_KEY is required")
    emulator = support["Emulator"](options.target, 19647)
    forward = ("tcp:19647", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    evidence = {}
    try:
        with profile_mode(emulator, options.mode, options.script_persistence, options.read_only):
            evidence["readyMs"] = emulator.ready("normal")
            with support["model_key"](emulator):
                if options.mode:
                    verify_mode(emulator, options.mode, options.script_persistence, evidence)
                elif options.read_only:
                    verify_read_only(emulator, evidence)
                else:
                    verify(emulator, evidence)
            evidence["temporaryModelCredentialRemoved"] = True
        if options.mode or options.read_only:
            evidence["temporaryProfilePatchRemoved"] = emulator.app(f"test ! -e {PTC_PROFILE_PATCH} && printf OK") == "OK"
            assert evidence["temporaryProfilePatchRemoved"]
    finally:
        emulator.hdc("fport", "rm", *forward)
        options.output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
