"""Exercise the production DSH Workflow tool on an isolated HarmonyOS Phone emulator."""
import argparse
import json
import os
from pathlib import Path
import runpy
import time
import uuid

capabilities = runpy.run_path(str(Path(__file__).with_name("emulator-dsh-capabilities.py")))
Emulator = capabilities["Emulator"]
model_key = capabilities["model_key"]
session = capabilities["session"]
events = capabilities["events"]


def start_workflow(emulator, script, name, background=False):
    session_id = session(emulator, True)
    arguments = json.dumps({
        "meta": {"name": name, "description": "HarmonyOS Workflow acceptance"},
        "script": script, "run_in_background": background,
    })
    prompt = f"Run the local acceptance fixture by calling workflow once with exactly these arguments: {arguments}. Use no other tool."
    emulator.rpc("session/prompt", {"request": {
        "sessionId": session_id, "requestId": str(uuid.uuid4()), "mode": "queue",
        "content": [{"type": "text", "text": prompt}],
    }})
    return session_id


def wait_for(emulator, session_id, predicate, timeout=55):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = events(emulator, session_id)
        if predicate(records):
            return records
        time.sleep(0.15)
    types = [event["type"] for event in records]
    raise AssertionError(f"Workflow did not reach the expected state: {types}")


def of_type(records, event_type):
    return [event for event in records if event["type"] == event_type]


def run_result(records, outcome):
    return any(event["data"]["stopReason"] == outcome for event in of_type(records, "tool-workflow/run-end"))


def verify_workflow(emulator, evidence):
    child_markers = ["MH_WORKFLOW_CHILD_A", "MH_WORKFLOW_CHILD_B"]
    child_prompts = [f"Reply with exactly {marker}. Do not call tools." for marker in child_markers]
    script = "phase('Acceptance'); return await parallel([" + ",".join(
        "() => agent(" + json.dumps(prompt) + ")" for prompt in child_prompts
    ) + "]);"
    sid = start_workflow(emulator, script, "mh-workflow-parallel")
    records = wait_for(emulator, sid, lambda rows: bool(of_type(rows, "tool-workflow/run-end")
                                                       and of_type(rows, "tool/result")))
    ended = of_type(records, "tool-workflow/run-end")
    starts = of_type(records, "tool-workflow/agent-start")
    children = of_type(records, "tool-workflow/agent-end")
    result = json.dumps(of_type(records, "tool/result"))
    diagnostic = json.dumps({"end": ended, "toolResults": of_type(records, "tool/result")})[:2500]
    assert run_result(records, "completed"), diagnostic
    assert len(starts) == len(children) == 2 and all("completed" in json.dumps(event) for event in children), diagnostic
    assert all(marker in result for marker in child_markers), diagnostic
    types = [event["type"] for event in records]
    assert max(i for i, name in enumerate(types) if name == "tool-workflow/agent-start") < types.index("tool-workflow/agent-end")
    evidence["foreground"] = {"actualSubagentsStarted": 2, "completed": True, "bothResultsReturned": True, "parallel": True}

    sid = start_workflow(emulator, "while (true) {}", "mh-workflow-timeout")
    records = wait_for(emulator, sid, lambda rows: bool(of_type(rows, "tool-workflow/run-end")
                                                       and of_type(rows, "tool/result")))
    result = json.dumps(of_type(records, "tool/result"))
    assert run_result(records, "error") and "Workflow synchronous execution exceeded" in result, result[:1500]
    evidence["timeout"] = True

    sid = start_workflow(emulator, "while (true) {}", "mh-workflow-cancel")
    wait_for(emulator, sid, lambda rows: bool(of_type(rows, "tool-workflow/run-start")))
    assert emulator.rpc("session/cancel", {"request": {"sessionId": sid}})["accepted"]
    records = wait_for(emulator, sid, lambda rows: bool(of_type(rows, "tool-workflow/run-end")))
    assert run_result(records, "cancelled"), of_type(records, "tool-workflow/run-end")
    evidence["cancelledDuringSyncSlice"] = True

    sid = start_workflow(emulator, """await agent('Write a long essay, with 600 words, about the history of paper.');
        await new Promise(() => {});""", "mh-workflow-cancel-child")
    wait_for(emulator, sid, lambda rows: bool(of_type(rows, "tool-workflow/agent-start")))
    assert emulator.rpc("session/cancel", {"request": {"sessionId": sid}})["accepted"]
    records = wait_for(emulator, sid, lambda rows: bool(of_type(rows, "tool-workflow/run-end")))
    assert run_result(records, "cancelled")
    child_end = of_type(records, "tool-workflow/agent-end")
    assert len(child_end) == 1 and child_end[0]["data"]["outcome"] == "cancelled", child_end
    evidence["cancelledWithActiveChild"] = True

    sid = start_workflow(emulator, "return ['MH', 'WORKFLOW', 'BACKGROUND', 'OK'].join('_');",
                         "mh-workflow-background", background=True)
    marker = "MH_WORKFLOW_BACKGROUND_OK"
    records = wait_for(emulator, sid, lambda rows: run_result(rows, "completed") and any(
        marker in json.dumps(event) for event in rows if event["type"] in {"agent/inbox/spliced", "user/message"}
    ))
    assert "started in the background as job " in json.dumps(of_type(records, "tool/result"))
    evidence["backgroundJob"] = {"started": True, "completed": True, "resultDelivered": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--host-port", type=int, default=19641)
    options = parser.parse_args()
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"):
        raise SystemExit("MH_TEST_DEEPSEEK_API_KEY is required for real subagent verification")
    emulator = Emulator(options.target, options.host_port)
    forward = (f"tcp:{options.host_port}", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    evidence = {}
    try:
        evidence["startupMs"] = emulator.ready("normal")
        assert emulator.web_status(False) == 401
        with model_key(emulator):
            verify_workflow(emulator, evidence)
        evidence["temporaryModelCredentialRemoved"] = True
    finally:
        options.output.write_text(json.dumps(evidence, indent=2) + "\n")
        emulator.hdc("fport", "rm", *forward)


if __name__ == "__main__":
    main()
