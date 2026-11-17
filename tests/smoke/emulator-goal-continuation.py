"""Require an automatically scheduled DSH goal round to perform real file work and complete."""
import argparse
import json
import os
from pathlib import Path
import runpy
import tempfile
import time
import uuid

agent = runpy.run_path(str(Path(__file__).with_name("emulator-agent-continuation.py")))
support = agent["support"]


def run(emulator, output):
    name = "mh-goal-loop-" + uuid.uuid4().hex[:10]
    app = "alpine/workspace-native/" + name
    path = support["WORKSPACE"] + "/" + name
    marker = "GOALCONTENT" + uuid.uuid4().hex.upper()
    remote = "/data/local/tmp/" + name + ".txt"
    evidence = {"fixture": name}
    sid = None
    try:
        evidence["readyMs"] = emulator.ready("normal")
        emulator.app(f"mkdir -p {app}")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "input.txt"; fixture.write_text(marker)
            assert "FileTransfer finish" in emulator.hdc("file", "send", str(fixture), remote)
            emulator.app(f"cp {remote} {app}/input.txt")
        with support["model_key"](emulator):
            sid = support["session"](emulator, True); evidence["sessionId"] = sid
            try:
                objective = ("In this isolated acceptance directory, use read to read " + path + "/input.txt, then use write to create "
                             + path + "/output.txt with exactly the same text. Do not use other execution tools, change directories, "
                             "or touch other files. After the actual read and write have succeeded, use get_goal and update_goal "
                             "with the current id/revision to mark this goal complete. This is the entire acceptance goal.")
                args = {"objective": objective, "max_goal_rounds": 2}
                calls, results, _ = agent["prompt"](emulator, sid,
                    "I explicitly request this persisted test goal. For this initial turn, call create_goal exactly once with precisely "
                    + json.dumps(args) + ". Then stop this initial turn without performing the file work or calling other tools. "
                    "The automatic goal continuation driver must start the next turn itself and carry out the objective. "
                    "Do not create subagents, workflows, or scheduled tasks.")
                assert len(calls) == len(results) == 1 and calls[0]["name"] == "create_goal", calls
                assert json.loads(calls[0]["arguments"]) == args
                created = json.loads(agent["toolkit"]["texts"](results))["goal"]
                evidence["createdGoal"] = {"id": created["id"], "revision": created["revision"]}
                deadline = time.monotonic() + 80
                while time.monotonic() < deadline:
                    current = emulator.rpc("goals/get", {"agentId": sid})
                    if current and current["phase"] == "complete": break
                    time.sleep(.15)
                else: raise AssertionError("No automatic round completed the actual file-copy goal")
                rows = support["events"](emulator, sid)
                automatic = [r for r in rows if r["type"] == "user/message" and r["data"]["source"].get("kind") == "goal"]
                assert automatic and all(r["data"]["source"]["goalId"] == created["id"] for r in automatic), automatic
                assert 1 <= current["roundsStarted"] <= 2
                turns = set()
                for message in automatic:
                    starts = [r for r in rows if r["type"] == "turn/start" and r["seq"] < message["seq"]]
                    turns.add(starts[-1]["data"]["turn"])
                tool_calls = [r["data"] for r in rows if r["type"] == "tool/call" and r["data"]["turn"] in turns]
                assert {"read", "write", "get_goal", "update_goal"} <= {r["name"] for r in tool_calls}, tool_calls
                assert all(r["name"] in {"read", "write", "get_goal", "update_goal"} for r in tool_calls), tool_calls
                updates = [json.loads(c["arguments"]) for c in tool_calls if c["name"] == "update_goal"]
                assert updates[-1]["goal_id"] == created["id"] and updates[-1]["action"] == "complete", updates
                ids = {c["callId"] for c in tool_calls}
                settled = [r["data"]["message"] for r in rows if r["type"] == "tool/result" and r["data"]["message"].get("toolCallId") in ids]
                assert len(settled) == len(tool_calls) and not any(r["isError"] for r in settled), settled
                assert marker in agent["toolkit"]["texts"](settled)
                assert emulator.app(f"cat {app}/output.txt") == marker
                evidence["automaticRoundDidRealReadAndWrite"] = True
                evidence["automaticSource"] = [r["data"]["source"] for r in automatic]
                evidence["actualTools"] = [{"name": r["name"], "arguments": json.loads(r["arguments"])} for r in tool_calls]
                evidence["completedGoal"] = current
                evidence["outputEqualsHiddenFixtureContent"] = True
            finally:
                current = emulator.rpc("goals/get", {"agentId": sid})
                if current:
                    emulator.rpc("goals/clear", {"agentId": sid, "ref": {"id": current["id"], "revision": current["revision"]}})
                emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
                evidence["testGoalCleared"] = emulator.rpc("goals/get", {"agentId": sid}) is None
        evidence["temporaryModelCredentialRemoved"] = True
    except BaseException:
        if sid: output.with_suffix(".events.json").write_text(json.dumps(support["events"](emulator, sid), indent=2) + "\n")
        raise
    finally:
        try:
            emulator.app(f"rm -rf {app}"); emulator.hdc("shell", "rm", "-f", remote)
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
