"""Actual working-directory and fork/message semantics on the native HarmonyOS Host."""
import argparse
import base64
import json
import os
from pathlib import Path
import runpy
import time
import uuid

office = runpy.run_path(str(Path(__file__).with_name("emulator-office.py")))
support = office["support"]
toolkit = office["toolkit"]


def prompt(emulator, sid, instruction, timeout=80, allow_error=False):
    text = "ACCEPTANCE" + uuid.uuid4().hex.upper() + ": " + instruction
    emulator.rpc("session/prompt", {"request": {
        "sessionId": sid, "requestId": str(uuid.uuid4()), "mode": "queue",
        "content": [{"type": "text", "text": text}],
    }})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = support["events"](emulator, sid)
        anchor = next((r for r in rows if r["type"] == "user/message" and
                       any(item.get("text") == text for item in r["data"].get("content", []))), None)
        if anchor:
            starts = [r for r in rows if r["type"] == "turn/start" and r["seq"] < anchor["seq"]]
            assert starts, anchor
            turn = starts[-1]["data"]["turn"]
            ended = next((r for r in rows if r["type"] == "turn/end" and r["data"]["turn"] == turn), None)
            if ended:
                assert ended["data"]["reason"]["kind"] == "completed", ended
                calls = [r["data"] for r in rows if r["type"] == "tool/call" and r["data"]["turn"] == turn]
                ids = {c["callId"] for c in calls}
                results = [r["data"]["message"] for r in rows if r["type"] == "tool/result"
                           and r["data"]["message"].get("toolCallId") in ids]
                assert len(calls) == len(results), results
                assert allow_error or not any(r["isError"] for r in results), results
                return calls, results, rows
        time.sleep(.1)
    raise AssertionError("The specifically addressed acceptance request did not finish")


def tool(emulator, sid, name, args, may_wait=False, expect_error=False, literal_unicode=False):
    instruction = "Actually call " + name + " exactly once now with precisely " + json.dumps(args, ensure_ascii=not literal_unicode) + ". "
    if name == "working_directory" and not args:
        instruction += "This is READ ONLY: {} is an empty object. Omit cd entirely; do not add a default directory or change it. "
    instruction += ("You may use wait_agent if required to collect that child's completion; use no other tools. " if may_wait
                    else "Use no other tools. ")
    calls, results, rows = prompt(emulator, sid, instruction + "Report the result and stop.", allow_error=expect_error)
    selected = [c for c in calls if c["name"] == name]
    assert len(selected) == 1 and json.loads(selected[0]["arguments"]) == args, calls
    assert all(c["name"] in ({name, "wait_agent"} if may_wait else {name}) for c in calls), calls
    result = next(r for r in results if r["toolCallId"] == selected[0]["callId"])
    assert bool(result["isError"]) == expect_error, result
    assert not any(r["isError"] for r in results if r is not result), results
    return result, rows


def child_events(emulator, parent, child):
    page = emulator.rpc("session/events", {"request": {"address": {
        "kind": "subagent", "parentSessionId": parent, "childSessionId": child, "mode": "continuable",
    }}})
    return [row["event"] for row in page["records"] if row.get("event")]


def child_end(emulator, parent, child, after_seq, predicate, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = child_events(emulator, parent, child)
        # Fork histories contain real parent events: only the new child segment is evidence.
        cutoff = after_seq if after_seq is not None else max(r["seq"] for r in rows if r["type"] == "subagent/descriptor")
        new = [r for r in rows if r["seq"] > cutoff]
        ends = [r for r in new if r["type"] == "turn/end"]
        if ends:
            assert ends[-1]["data"]["reason"]["kind"] == "completed", ends[-1]
            if predicate(new): return rows
        time.sleep(.1)
    raise AssertionError("The actual fork child did not complete the expected operation")


def assistant_texts(rows):
    return "\n".join(item.get("text", "") for row in rows if row["type"] == "assistant/message"
                     for item in row["data"]["message"]["content"])


def read_bytes(emulator, app_path):
    # HDC's text helper strips whitespace; base64 makes trailing bytes observable.
    return base64.b64decode(emulator.app("base64 " + app_path), validate=False)


def run(emulator, output):
    name = "mh-continuation-" + uuid.uuid4().hex[:10]
    path = support["WORKSPACE"] + "/" + name
    app = "alpine/workspace-native/" + name
    token = "FORKMEMORY" + uuid.uuid4().hex.upper()
    followup = "FORKFOLLOWUP" + uuid.uuid4().hex.upper()
    record = {"fixture": name}
    sid = None
    try:
        record["readyMs"] = emulator.ready("normal")
        emulator.app(f"mkdir -p {app}/parent {app}/child")
        with support["model_key"](emulator):
            sid = support["session"](emulator, True); record["sessionId"] = sid
            result, _ = tool(emulator, sid, "working_directory", {})
            assert toolkit["texts"]([result]) == support["WORKSPACE"]
            result, _ = tool(emulator, sid, "working_directory", {"cd": path + "/parent"})
            assert toolkit["texts"]([result]) == path + "/parent"
            tool(emulator, sid, "write", {"file_path": "parent.txt", "content": "PARENT"})
            assert read_bytes(emulator, f"{app}/parent/parent.txt") == b"PARENT"
            record["relativeFileUsesSessionCwd"] = True
            calls, _, _ = prompt(emulator, sid, "Remember this harmless acceptance token in our conversation: " + token
                                  + ". Reply ACK only; do not call any tools or create a goal.")
            assert not calls
            fork_args = {"description": "Verify inherited conversation token", "name": "memory-child", "cwd": path + "/child",
                         "prompt": "Our earlier human conversation contains a token beginning FORKMEMORY. Reply with exactly that entire token. Use no tools and take no other action."}
            result, rows = tool(emulator, sid, "subagent_fork", fork_args, may_wait=True)
            assert "started subagent memory-child" in toolkit["texts"]([result])
            child = next(r["data"]["childId"] for r in rows if r["type"] == "subagent/catalog" and r["data"].get("name") == "memory-child")
            record["childSessionId"] = child
            child_rows = child_end(emulator, sid, child, None, lambda rows: token in assistant_texts(rows))
            record["forkInheritedConversation"] = True
            before = child_rows[-1]["seq"]
            result, _ = tool(emulator, sid, "list_agents", {})
            assert "memory-child [inactive]" in toolkit["texts"]([result])
            record["childDiscoveredByListTool"] = True
            # Changing the parent after creation must not change the child's independent cwd.
            tool(emulator, sid, "working_directory", {"cd": path})
            followup_args = {"agent": "memory-child", "message": "This is a new, explicitly requested continuation. Use write exactly once with precisely "
                             + json.dumps({"file_path": "followup.txt", "content": followup})
                             + ". Keep the file_path relative and do not change directories. Then reply with the exact FORKMEMORY token from our inherited earlier conversation, without other tools."}
            result, _ = tool(emulator, sid, "send_message", followup_args, may_wait=True)
            assert "message delivered to agent memory-child" in toolkit["texts"]([result])
            child_rows = child_end(emulator, sid, child, before, lambda rows: token in assistant_texts(rows))
            assert read_bytes(emulator, f"{app}/child/followup.txt") == followup.encode()
            assert emulator.app(f"test ! -e {app}/followup.txt && printf ABSENT") == "ABSENT"
            assert emulator.app(f"test ! -e {app}/parent/followup.txt && printf ABSENT") == "ABSENT"
            writes = [r["data"] for r in child_rows if r["seq"] > before and r["type"] == "tool/call" and r["data"]["name"] == "write"]
            assert len(writes) == 1 and json.loads(writes[0]["arguments"]) == {"file_path": "followup.txt", "content": followup}, writes
            record["messageContinuedSameChild"] = True
            record["childCwdIndependentOfParent"] = True
            record["childMemoryAfterContinuation"] = token in assistant_texts([r for r in child_rows if r["seq"] > before])
            before_restart = child_rows[-1]["seq"]
            tool(emulator, sid, "working_directory", {"cd": support["WORKSPACE"]})
            emulator.stop(); emulator.start(); record["restartReadyMs"] = emulator.ready("normal")
            parent_rows = support["events"](emulator, sid)
            assert any(r["type"] == "subagent/catalog" and r["data"].get("childId") == child for r in parent_rows)
            record["childCatalogSurvivedRestart"] = True
            result, _ = tool(emulator, sid, "list_agents", {})
            assert "memory-child [inactive]" in toolkit["texts"]([result])
            record["childDiscoveredAfterRestart"] = True
            resumed = "FORKRESTART" + uuid.uuid4().hex.upper()
            tool(emulator, sid, "send_message", {"agent": "memory-child", "message":
                 "Continue after the application restart. Without changing directories, use write exactly once with precisely "
                 + json.dumps({"file_path": "restart.txt", "content": resumed})
                 + ". Keep file_path relative. Then reply with the exact FORKMEMORY token remembered from our earlier inherited conversation; use no other tools."}, may_wait=True)
            child_rows = child_end(emulator, sid, child, before_restart, lambda rows: token in assistant_texts(rows))
            assert read_bytes(emulator, f"{app}/child/restart.txt") == resumed.encode()
            record["sameChildMemoryAndCwdAfterRestart"] = True
            emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
        record["temporaryModelCredentialRemoved"] = True
    except BaseException:
        if sid: output.with_suffix(".events.json").write_text(json.dumps(support["events"](emulator, sid), indent=2) + "\n")
        raise
    finally:
        try:
            if sid: emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
            emulator.app(f"rm -rf {app}")
        finally: output.write_text(json.dumps(record, indent=2) + "\n")


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
