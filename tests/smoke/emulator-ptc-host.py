"""Run the experimental HarmonyOS PTC adapter through an actual DSH session."""
import argparse
import json
import os
from pathlib import Path
import runpy
import re
import time
import uuid

support = runpy.run_path(str(Path(__file__).with_name("emulator-dsh-capabilities.py")))


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
let denied: boolean = false;
try {{ await fs.readFile('../{name}.txt', 'utf8'); }}
catch (error) {{ denied = error.code === 'EXDEV' || error.code === 'EACCES' || error.code === 'EPERM'; }}
return {{ text, denied, nestedRead }};
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
                assert re.search(r'\"nestedRead\"\s*:\s*true', result), result[:2200]
                evidence.update(typeScriptResultReturned=True, fileContentsMatched=True, outsideReadDenied=True,
                                nestedHostToolMatched=True)
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
    options = parser.parse_args()
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"):
        raise SystemExit("MH_TEST_DEEPSEEK_API_KEY is required")
    emulator = support["Emulator"](options.target, 19647)
    forward = ("tcp:19647", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    evidence = {}
    try:
        evidence["readyMs"] = emulator.ready("normal")
        with support["model_key"](emulator):
            verify(emulator, evidence)
        evidence["temporaryModelCredentialRemoved"] = True
    finally:
        emulator.hdc("fport", "rm", *forward)
        options.output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
