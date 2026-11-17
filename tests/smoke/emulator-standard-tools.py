"""Real-model standard-preset tools, durable goals/team tasks, and public web retrieval."""
import argparse
import json
import os
from pathlib import Path
import runpy
import tempfile
import uuid

office = runpy.run_path(str(Path(__file__).with_name("emulator-office.py")))
support = office["support"]
toolkit = office["toolkit"]


def value(result):
    return json.loads(toolkit["texts"]([result]))


def run(emulator, output):
    evidence = {}
    sid = None
    goal_sid = None
    name = "mh-standard-" + uuid.uuid4().hex[:12]
    app = "alpine/workspace-native/" + name
    path = support["WORKSPACE"] + "/" + name
    remote = "/data/local/tmp/" + name + ".txt"
    try:
        evidence["readyMs"] = emulator.ready("normal")
        emulator.app(f"mkdir -p {app}")
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "result.txt"
            marker = "HARMONY_PRESENT_" + uuid.uuid4().hex.upper()
            fixture.write_text(marker + "\n")
            assert "FileTransfer finish" in emulator.hdc("file", "send", str(fixture), remote)
            emulator.app(f"cp {remote} {app}/result.txt")
        with support["model_key"](emulator):
            sid = support["session"](emulator, True)
            evidence["sessionId"] = sid

            todos = [{"content": name + " first", "status": "in_progress"},
                     {"content": name + " second", "status": "pending"}]
            office["invoke"](emulator, sid, "todo_write", {"todos": todos})
            rows = support["events"](emulator, sid)
            writes = [r["data"]["todos"] for r in rows if r["type"] == "todo/write"]
            assert writes[-1] == todos, writes
            evidence["todoExactSnapshot"] = True

            result, _ = office["invoke"](emulator, sid, "skill", {"name": "dsh-doc"})
            assert "skill_instructions" in toolkit["texts"]([result])
            evidence["bundledSkillLoaded"] = True

            office["invoke"](emulator, sid, "present", {"files": [{"path": path + "/result.txt", "description": marker}]})
            delivered = [r["data"] for r in support["events"](emulator, sid) if r["type"] == "deliverables/presented"]
            assert delivered[-1]["files"] == [{"path": path + "/result.txt", "description": marker}], delivered
            evidence["presentDurableEvent"] = True

            goal_sid = support["session"](emulator, True)
            result, _ = office["invoke"](emulator, goal_sid, "get_goal", {})
            assert value(result) == {"goal": None}, result
            objective = name + " durable goal acceptance; remain paused until explicitly resumed"
            calls, results = toolkit["prompt"](emulator, goal_sid,
                "For this isolated acceptance test, explicitly create a goal now with objective " + json.dumps(objective)
                + " and max_goal_rounds 1. Immediately pause it in this same turn using update_goal with its exact "
                "returned id and revision, action pause. Use exactly these two tools in this order, no other tools. "
                "Do not perform work on the goal. This is an explicit request to create and pause this test goal.")
            assert [c["name"] for c in calls] == ["create_goal", "update_goal"], calls
            assert len(results) == 2 and not any(r["isError"] for r in results), toolkit["texts"](results)
            current = emulator.rpc("goals/get", {"agentId": goal_sid})
            assert current["objective"] == objective and current["phase"] == "paused", current
            evidence["goalCreatedAndPaused"] = {"id": current["id"], "revision": current["revision"]}
            stale = {"goal_id": current["id"], "revision": current["revision"] - 1, "action": "edit", "objective": "STALE_MUST_NOT_APPLY"}
            result, _ = office["invoke"](emulator, goal_sid, "update_goal", stale, expect_error=True,
                preamble="This isolated test explicitly asks for one stale-revision edit to verify it is rejected. ")
            assert "stale" in toolkit["texts"]([result]).lower() or "revision" in toolkit["texts"]([result]).lower()
            assert emulator.rpc("goals/get", {"agentId": goal_sid})["objective"] == objective
            evidence["staleGoalUpdateRejected"] = True

            emulator.rpc("agentTeams/setEnabled", {"agentId": sid, "enabled": True})
            result, _ = office["invoke"](emulator, sid, "team_task_create", {"subject": name + " first", "description": "Controlled task board fixture."})
            first = value(result)
            result, _ = office["invoke"](emulator, sid, "team_task_create", {"subject": name + " second", "description": "Must wait for the first task.", "blocked_by": [first["id"]]})
            second = value(result)
            assert second["ready"] is False, second
            result, _ = office["invoke"](emulator, sid, "team_task_update", {"task_id": first["id"], "expected_revision": first["revision"], "action": "claim"})
            claimed = value(result)
            assert claimed["status"] == "in_progress", claimed
            result, _ = office["invoke"](emulator, sid, "team_task_update", {"task_id": first["id"], "expected_revision": claimed["revision"], "action": "complete"})
            assert value(result)["status"] == "completed"
            result, _ = office["invoke"](emulator, sid, "team_task_get", {"task_id": second["id"]})
            assert value(result)["ready"] is True
            evidence["teamDependencyClaimComplete"] = True

            emulator.stop(); emulator.start()
            evidence["restartReadyMs"] = emulator.ready("normal")
            current = emulator.rpc("goals/get", {"agentId": goal_sid})
            assert current["objective"] == objective and current["phase"] == "paused", current
            assert current["activation"] == "disarmed", current
            evidence["goalPersistedPausedAcrossRestart"] = True
            result, _ = office["invoke"](emulator, sid, "team_task_list", {})
            tasks = {t["id"]: t for t in value(result)["tasks"]}
            assert tasks[first["id"]]["status"] == "completed" and tasks[second["id"]]["ready"]
            evidence["teamPersistedAcrossRestart"] = True
            emulator.rpc("agentTeams/setEnabled", {"agentId": sid, "enabled": False})
            emulator.rpc("goals/clear", {"agentId": goal_sid, "ref": {"id": current["id"], "revision": current["revision"]}})
            evidence["testGoalClearedTeamDisabled"] = True

        evidence["temporaryModelCredentialRemoved"] = True
    finally:
        if goal_sid is not None:
            current = emulator.rpc("goals/get", {"agentId": goal_sid})
            if current:
                emulator.rpc("goals/clear", {"agentId": goal_sid, "ref": {"id": current["id"], "revision": current["revision"]}})
        if sid is not None:
            emulator.rpc("agentTeams/setEnabled", {"agentId": sid, "enabled": False})
        emulator.app(f"rm -rf {app}")
        emulator.hdc("shell", "rm", "-f", remote)
        output.write_text(json.dumps(evidence, indent=2) + "\n")


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
