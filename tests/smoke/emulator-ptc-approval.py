"""Exercise one-shot PTC escalation through the authenticated DSH Remote Event stream."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import runpy
import subprocess
import threading
import time
import uuid

ptc = runpy.run_path(str(Path(__file__).with_name("emulator-ptc-host.py")))
support = ptc["support"]
ROOT = Path(__file__).resolve().parents[2]


def ws_module():
    lock = json.loads((ROOT / "runtime/harmonyos/dsh/package-lock.json").read_text())
    version = lock["packages"]["node_modules/ws"]["version"]
    candidates = [ROOT / ".build/dsh-rc3-deps/node_modules/ws"]
    candidates.extend((ROOT / ".build/dsh-runtime").glob("*/node_modules/ws"))
    for candidate in candidates:
        manifest = candidate / "package.json"
        if manifest.exists() and json.loads(manifest.read_text())["version"] == version:
            return candidate
    raise RuntimeError("Build the pinned DSH runtime to provide the locked ws dependency")


@contextmanager
def approval_events(emulator):
    node = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents")) / "tools/node/bin/node"
    fixture = Path(__file__).with_name("fixtures") / "approval-events.cjs"
    process = subprocess.Popen([str(node), str(fixture), str(ws_module())], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    frames = queue.Queue()

    def consume():
        try:
            for line in process.stdout:
                frames.put(json.loads(line))
        except BaseException as error:
            frames.put(error)
        finally:
            frames.put(RuntimeError("The approval event stream ended"))

    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    try:
        process.stdin.write(json.dumps({
            "url": emulator.url.replace("http:", "ws:"), "host": "127.0.0.1:19592", "cookie": emulator.cookie(),
        }) + "\n")
        process.stdin.flush()
        ready = frames.get(timeout=15)
        if isinstance(ready, BaseException):
            raise ready
        assert ready["type"] == "ready", ready
        yield ready["clientId"], frames
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
        reader.join(timeout=5)


def run_code(emulator, sid, script, expect_error, answerer=None, decision=None, target_file=None,
             requested_mode="danger-full-access"):
    previous = support["events"](emulator, sid)
    old_calls = {row["data"]["callId"] for row in previous if row["type"] == "tool/call"}
    old_turns = sum(row["type"] == "turn/end" for row in previous)
    old_workers = {row["id"] for row in ptc["workers"](emulator)}
    args = {"description": "Exercise the local one-shot approval fixture", "code": script}
    if answerer:
        args.update(sandbox_permissions=requested_mode, justification="本次回归需要以扩大后的文件权限写入临时测试夹具。")
    emulator.rpc("session/prompt", {"request": {
        "sessionId": sid, "requestId": str(uuid.uuid4()), "mode": "queue",
        "content": [{"type": "text", "text": "Call run_code exactly once with this JSON, then stop regardless of "
                     "success or failure. Do not retry and do not use any other tool: " + json.dumps(args)}],
    }})
    answered = False
    call_id = None
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if answerer and not answered:
            client_id, frames = answerer
            try:
                frame = frames.get_nowait()
            except queue.Empty:
                frame = None
            if isinstance(frame, BaseException):
                raise frame
            if frame and frame["type"] == "error":
                raise RuntimeError(frame)
            if frame and frame["type"] == "waterfall":
                if frame["event"] == "approval/request" and frame["agentId"] == sid:
                    assert frame["request"]["toolName"] == "run_code", frame
                    call_id = frame["request"]["callId"]
                    assert emulator.app(f"cat {target_file}") == "ORIGINAL"
                    assert not any(row["event"] == "ptc-worker-admitted" and row["id"] not in old_workers
                                   for row in ptc["workers"](emulator)), "A worker started before the approval decision"
                    if decision == "cancel":
                        assert emulator.rpc("session/cancel", {"request": {"sessionId": sid}})["accepted"]
                    else:
                        emulator.rpc("$events/result", {
                            "clientId": client_id, "eventId": frame["eventId"],
                            "outcome": {"kind": "result", "value": decision},
                        })
                    answered = True
                else:
                    emulator.rpc("$events/result", {
                        "clientId": client_id, "eventId": frame["eventId"], "outcome": {"kind": "next"},
                    })
        rows = support["events"](emulator, sid)
        if sum(row["type"] == "turn/end" for row in rows) > old_turns:
            calls = {row["data"]["callId"] for row in rows
                     if row["type"] == "tool/call" and row["data"]["name"] == "run_code"} - old_calls
            assert len(calls) == 1, calls
            actual = next(row["data"] for row in rows if row["type"] == "tool/call" and row["data"]["callId"] in calls)
            actual_args = json.loads(actual["arguments"])
            for key in ("code", "sandbox_permissions", "justification"):
                assert actual_args.get(key) == args.get(key), f"The model changed the fixture's {key}"
            if answerer:
                assert answered and call_id in calls, "The approval was not bound to the actual run_code call"
            if decision == "cancel":
                turns = [row for row in rows if row["type"] == "turn/end"]
                assert turns[old_turns]["data"]["reason"]["kind"] == "aborted", turns[old_turns]
                return "CANCELLED_APPROVAL"
            for row in rows:
                if row["type"] != "tool/result":
                    continue
                message = row["data"]["message"]
                if message.get("toolCallId") in calls:
                    text = "\n".join(item.get("text", "") for item in message["content"])
                    assert bool(message["isError"]) == expect_error, text[:1800]
                    return text
            break
        time.sleep(0.1)
    raise AssertionError("The PTC approval fixture did not settle")


def verify(emulator, read_only, retained, evidence):
    workspace = emulator.rpc("workspace/create", {"request": {"path": support["WORKSPACE"]}})["workspace"]["workspaceId"]
    sid = ptc["model_session"](emulator, workspace)
    name = "mh-ptc-approval-" + uuid.uuid4().hex[:12]
    target = f"alpine/{'workspace-native/' if read_only else ''}{name}.txt"
    worker_path = f"{'' if read_only else '../'}{name}.txt"
    requested_mode = "workspace-write" if read_only else "danger-full-access"
    marker = "MH_APPROVED_" + uuid.uuid4().hex.upper()
    result = "" if retained else "return "
    script = ("var approvalFs = await import('node:fs/promises'); "
              f"await approvalFs.writeFile('{worker_path}', '{marker}'); "
              f"{result}'MH_APPROVED_WRITE:' + typeof scopedSecret;")
    try:
        emulator.app(f"printf ORIGINAL > {target}")
        if retained:
            ptc["complete_code"](emulator, sid, "Initialize retained state under the standing file policy",
                                 f"var scopedSecret: string = '{marker}'; scopedSecret", marker)
        denied = run_code(emulator, sid, script, True)
        assert "EACCES" in denied or "EXDEV" in denied, denied
        assert emulator.app(f"cat {target}") == "ORIGINAL"
        evidence["defaultPolicyDenied"] = True
        with approval_events(emulator) as events:
            prior = {row["id"] for row in ptc["workers"](emulator)}
            rejected = run_code(emulator, sid, script, True, events, "rejected", target, requested_mode)
            assert "reject" in rejected.lower(), rejected
            assert emulator.app(f"cat {target}") == "ORIGINAL"
            assert not any(row["event"] == "ptc-worker-admitted" and row["id"] not in prior
                           for row in ptc["workers"](emulator))
            evidence["rejectionPreventedExecution"] = True
            run_code(emulator, sid, script, True, events, "cancel", target, requested_mode)
            assert emulator.app(f"cat {target}") == "ORIGINAL"
            assert not any(row["event"] == "ptc-worker-admitted" and row["id"] not in prior
                           for row in ptc["workers"](emulator))
            evidence["cancellationPreventedExecution"] = True
            approved = run_code(emulator, sid, script, False, events, "allowed-once", target, requested_mode)
            assert "MH_APPROVED_WRITE:undefined" in approved, approved
            assert emulator.app(f"cat {target}") == marker
            trace = ptc["workers"](emulator)
            admitted = [row["id"] for row in trace if row["event"] == "ptc-worker-admitted"
                        and row["id"] not in prior and row["mode"] == requested_mode]
            assert len(admitted) == 1 and any(row["event"] == "ptc-worker-reaped" and row["id"] == admitted[0]
                                            for row in trace), trace
            evidence["approvedOnceExecutedAndReaped"] = True
        denied_again = run_code(emulator, sid, script, True)
        assert "EACCES" in denied_again or "EXDEV" in denied_again, denied_again
        assert emulator.app(f"cat {target}") == marker
        evidence.update(standingPolicyPreserved=True, approvalsBoundToCallAndSession=True,
                        standingMode="read-only" if read_only else "workspace-write", approvedMode=requested_mode)
        if retained:
            ptc["complete_code"](emulator, sid, "Read the original scoped value after the one-shot escalation",
                                 "scopedSecret", marker)
            evidence["retainedStatePreservedAcrossEscalation"] = True
            evidence["escalationUsedFreshProgramState"] = True
    finally:
        emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
        emulator.app(f"rm -f {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--retained", action="store_true")
    options = parser.parse_args()
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"):
        parser.error("MH_TEST_DEEPSEEK_API_KEY is required")
    emulator = support["Emulator"](options.target, 19651)
    forward = ("tcp:19651", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    evidence = {}
    try:
        mode = "persistent-in-memory" if options.retained else None
        with ptc["profile_mode"](emulator, mode, False, options.read_only):
            evidence["readyMs"] = emulator.ready("normal")
            with support["model_key"](emulator):
                verify(emulator, options.read_only, options.retained, evidence)
            evidence["temporaryModelCredentialRemoved"] = True
        if options.read_only or options.retained:
            assert emulator.app(f"test ! -e {ptc['PTC_PROFILE_PATCH']} && printf OK") == "OK"
            evidence["temporaryProfilePatchRemoved"] = True
    finally:
        emulator.hdc("fport", "rm", *forward)
        options.output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
