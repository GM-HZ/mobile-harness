"""Real-model questions, cancellation, plan review, and approved plugin discovery."""
import argparse
import json
import os
from pathlib import Path
import queue
import runpy
import time
import uuid

office = runpy.run_path(str(Path(__file__).with_name("emulator-office.py")))
support = office["support"]
toolkit = office["toolkit"]
approval = toolkit["approval"]


def interact(emulator, sid, name, args, decision, record):
    old = support["events"](emulator, sid)
    before = sum(row["type"] == "turn/end" for row in old)
    old_calls = {row["data"]["callId"] for row in old if row["type"] == "tool/call"}
    context = ("The fully specified task is to verify this isolated test's plan-review UI can decline or approve "
               "the exact supplied plan. The plan is already decision-ready and its complete text is below. "
               "No repository changes, investigation, or additional user choices are needed for this UI test. "
               if name == "exit_plan_mode" else "")
    with approval["approval_events"](emulator) as (client, frames):
        emulator.rpc("session/prompt", {"request": {
            "sessionId": sid, "requestId": str(uuid.uuid4()), "mode": "queue",
            "content": [{"type": "text", "text": context + "This is an isolated acceptance test. Actually call " + name
                         + " exactly once now with precisely " + json.dumps(args)
                         + ". Do not answer the question yourself or summarize an earlier call. "
                         "Report its result and stop, without other tools or any implementation work."}],
        }})
        answered = None
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try: frame = frames.get_nowait()
            except queue.Empty: frame = None
            if isinstance(frame, BaseException): raise frame
            if frame and frame["type"] == "error": raise AssertionError(frame)
            if frame and frame["type"] == "waterfall":
                outcome = {"kind": "next"}
                expected = "approval/request" if name == "plugin_manager" else "user-questions/request"
                if frame["agentId"] == sid and frame["event"] == expected:
                    assert answered is None, frame
                    answered = frame
                    if name == "plugin_manager":
                        assert frame["request"]["toolName"] == name
                        outcome = {"kind": "result", "value": "allowed-once"}
                    elif decision == "cancel":
                        assert emulator.rpc("session/cancel", {"request": {"sessionId": sid}})["accepted"]
                    else:
                        questions = frame["request"]["questions"]
                        assert len(questions) == 1
                        if name == "exit_plan_mode":
                            assert questions[0]["detail"] == args["plan"]
                            assert questions[0]["intent"]["kind"] == "plan-review"
                        labels = [item["label"] for item in questions[0]["options"]]
                        assert decision in labels, labels
                        outcome = {"kind": "result", "value": {"answers": [{"id": questions[0]["id"], "selected": [decision]}]}}
                    record["questionOrApprovalObserved"] = True
                    record["decision"] = decision
                if decision != "cancel" or answered is not frame:
                    emulator.rpc("$events/result", {"clientId": client, "eventId": frame["eventId"], "outcome": outcome})
            rows = support["events"](emulator, sid)
            ends = [row for row in rows if row["type"] == "turn/end"]
            if len(ends) > before:
                calls = [row["data"] for row in rows if row["type"] == "tool/call" and row["data"]["callId"] not in old_calls]
                assert len(calls) == 1 and calls[0]["name"] == name, calls
                assert json.loads(calls[0]["arguments"]) == args, calls
                assert answered is not None, "No actual question or approval was observed"
                if name == "plugin_manager": assert answered["request"]["callId"] == calls[0]["callId"]
                record["callId"] = calls[0]["callId"]
                record["turn"] = ends[before]["data"]["reason"]["kind"]
                if decision == "cancel":
                    assert record["turn"] == "aborted"
                    return None
                results = [row["data"]["message"] for row in rows if row["type"] == "tool/result"
                           and row["data"]["message"].get("toolCallId") == calls[0]["callId"]]
                expected_error = name == "exit_plan_mode" and decision == "Keep planning"
                assert len(results) == 1 and bool(results[0]["isError"]) == expected_error, results
                if expected_error:
                    assert toolkit["texts"](results) == "Error: The user chose to keep planning; revise the plan and present it again."
                return results[0]
            time.sleep(.08)
    raise AssertionError("The interaction did not settle")


def run(emulator, output):
    evidence = {}
    sid = None
    try:
        evidence["readyMs"] = emulator.ready("normal")
        with support["model_key"](emulator):
            sid = support["session"](emulator, True); evidence["sessionId"] = sid
            args = {"questions": [{"id": "mh-question", "question": "Controlled fixture: choose one.",
                                   "options": [{"label": "A"}, {"label": "B"}]}]}
            for decision, label in [("A", "answered"), ("cancel", "cancelled"), ("B", "sameSessionAfterCancel")]:
                evidence[label] = record = {}
                result = interact(emulator, sid, "ask_user_question", args, decision, record)
                if result:
                    assert json.loads(toolkit["texts"]([result])) == {"answers": [{"id": "mh-question", "selected": [decision]}]}
            commands = emulator.rpc("commands/list", {"agentId": sid})
            assert "plan" in [row["name"] for row in commands], commands
            # `/plan <text>` submits <text> as a new human prompt; only `off` is a mode argument.
            # A bare `/plan` changes mode without starting an unrelated "on" turn.
            response = emulator.rpc("commands/execute", {"agentId": sid, "line": "/plan", "submittedAttachments": []})
            evidence["planCommand"] = response
            plan = "# Controlled plan acceptance\n\n1. Verify the plan decision.\n2. Report the test result.\nNo files or external services will be changed."
            for decision, label in [("Keep planning", "planRejected"), ("Approve", "planApproved")]:
                evidence[label] = record = {}
                interact(emulator, sid, "exit_plan_mode", {"plan": plan}, decision, record)
                modes = [row["data"]["active"] for row in support["events"](emulator, sid) if row["type"] == "plan/mode"]
                assert modes[-1] == (decision != "Approve"), modes
                record["active"] = modes[-1]
            evidence["pluginDiscovery"] = record = {}
            result = interact(emulator, sid, "plugin_manager", {"action": "list_bundles", "limit": 100}, "allowed-once", record)
            listing = json.loads(toolkit["texts"]([result]))
            assert listing["total"] > 0 and listing["entries"], listing
            record["totalBundles"] = listing["total"]
        evidence["temporaryModelCredentialRemoved"] = True
    except BaseException:
        if sid: output.with_suffix(".events.json").write_text(json.dumps(support["events"](emulator, sid), indent=2) + "\n")
        raise
    finally:
        try:
            if sid: emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
        finally: output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target"); parser.add_argument("output", type=Path)
    options = parser.parse_args()
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"): parser.error("MH_TEST_DEEPSEEK_API_KEY is required")
    emulator = support["Emulator"](options.target, 19643)
    forward = ("tcp:19643", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc("fport", "rm", *forward)
