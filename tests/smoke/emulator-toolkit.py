"""Exercise files and approved Bash/toolkit commands through real DSH model calls."""
import argparse
import json
import os
from pathlib import Path
import queue
import runpy
import shlex
import time
import uuid

approval = runpy.run_path(str(Path(__file__).with_name("emulator-ptc-approval.py")))
support = approval["support"]


def prompt(emulator, sid, text, answerer=None, expected_command=None, timeout=100):
    old = support["events"](emulator, sid)
    before = sum(row["type"] == "turn/end" for row in old)
    calls = {row["data"]["callId"] for row in old if row["type"] == "tool/call"}
    emulator.rpc("session/prompt", {"request": {
        "sessionId": sid, "requestId": str(uuid.uuid4()), "mode": "queue",
        "content": [{"type": "text", "text": text}],
    }})
    accepted = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if answerer:
            client, frames = answerer
            try:
                frame = frames.get_nowait()
            except queue.Empty:
                frame = None
            if isinstance(frame, BaseException):
                raise frame
            if frame and frame["type"] == "waterfall":
                outcome = {"kind": "next"}
                if frame["event"] == "approval/request" and frame["agentId"] == sid:
                    assert frame["request"]["toolName"] == "bash", frame
                    rows = support["events"](emulator, sid)
                    call = next(row["data"] for row in rows if row["type"] == "tool/call"
                                and row["data"]["callId"] == frame["request"]["callId"])
                    args = json.loads(call["arguments"])
                    assert args["command"] == expected_command, args
                    assert args["sandbox_permissions"] == "danger-full-access", args
                    accepted.append(call["callId"])
                    outcome = {"kind": "result", "value": "allowed-once"}
                emulator.rpc("$events/result", {"clientId": client, "eventId": frame["eventId"], "outcome": outcome})
        rows = support["events"](emulator, sid)
        if sum(row["type"] == "turn/end" for row in rows) > before:
            current = {row["data"]["callId"] for row in rows if row["type"] == "tool/call"} - calls
            invoked = [row["data"] for row in rows if row["type"] == "tool/call"
                       and row["data"]["callId"] in current]
            results = [row["data"]["message"] for row in rows if row["type"] == "tool/result"
                       and row["data"]["message"].get("toolCallId") in current]
            if answerer:
                assert len(accepted) == 1 and accepted[0] in current, accepted
            return invoked, results
        time.sleep(.15)
    raise AssertionError("DSH toolkit fixture timed out")


def texts(results):
    return "\n".join(item.get("text", "") for result in results for item in result["content"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--port", type=int, default=19643)
    options = parser.parse_args()
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"):
        raise SystemExit("A model test credential is required")
    emulator = support["Emulator"](options.target, options.port)
    forward = (f"tcp:{options.port}", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    name = "mh-toolkit-" + uuid.uuid4().hex[:12]
    remote = "/data/local/tmp/" + name + ".sh"
    fixture = Path(__file__).resolve().parents[1] / "contract/smoke-guest-tools.sh"
    report = {}
    sessions = []
    try:
        emulator.ready("normal")
        assert "FileTransfer finish" in emulator.hdc("file", "send", str(fixture), remote)
        emulator.app(f"cp {remote} alpine/workspace-native/{name}.sh")
        with support["model_key"](emulator):
            sid = support["session"](emulator, True)
            sessions.append(sid)
            tool_args = {"command": "printf HARMONY_DEFAULT_BASH_MUST_BE_REFUSED", "description": "Test default confinement"}
            calls, results = prompt(emulator, sid, "Call bash exactly once with this JSON. Stop after its result; "
                                    "do not retry or escalate: " + json.dumps(tool_args))
            assert len(calls) == len(results) == 1 and calls[0]["name"] == "bash"
            assert json.loads(calls[0]["arguments"]).get("sandbox_permissions") is None
            assert results[0]["isError"] and "no sandbox backend" in texts(results), texts(results)
            report["defaultBashRefusedWithoutBackend"] = True

            command = (f"bash {shlex.quote(name + '.sh')} && git --version && "
                       "printf HARMONY_APPROVED_TOOLKIT_OK")
            tool_args = {"command": command, "description": "Run local tool and virtual environment fixtures",
                         "timeoutMs": 180000, "sandbox_permissions": "danger-full-access",
                         "justification": "仅运行本次模拟器的临时工具链夹具。"}
            with approval["approval_events"](emulator) as events:
                calls, results = prompt(emulator, sid, "Call bash exactly once with precisely this JSON; "
                                        "return its result and stop: " + json.dumps(tool_args), events, command, timeout=200)
            report["approvedCommandObservedTools"] = [row["name"] for row in calls]
            assert len(calls) == len(results) == 1 and calls[0]["name"] == "bash", calls
            output = texts(results)
            assert not results[0]["isError"], output
            assert all(marker in output for marker in ["HARMONY_TOOLKIT_OK", "HARMONY_PYTHON_VENV_OK",
                                                       "git version", "HARMONY_APPROVED_TOOLKIT_OK"]), output
            report["approvedToolkit"] = {"bash": True, "git": True, "pythonPip": True,
                                          "twoIsolatedVenvs": True, "nodeFetch": True,
                                          "curl": True, "sqlite": True, "timezone": True}

            sid = support["session"](emulator, True)
            sessions.append(sid)
            original, changed = "MH_ORIGINAL_" + name, "MH_CHANGED_" + name
            calls, results = prompt(emulator, sid,
                f"Use only DSH file tools: write {name}.txt with content {original}; edit that file replacing "
                f"{original} with {changed}; grep for {changed} in {name}.txt; glob for {name}.txt; "
                "read the file. Call all five tools and stop. Do not use bash or run_code.")
            assert {row["name"] for row in calls} == {"write", "edit", "grep", "glob", "read"}, calls
            assert len(results) == len(calls) and not any(row["isError"] for row in results), results
            assert emulator.app(f"cat alpine/workspace-native/{name}.txt").strip() == changed
            report["fileTools"] = sorted({row["name"] for row in calls})
        report["temporaryModelCredentialRemoved"] = True
    finally:
        try:
            for sid in sessions:
                emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
            emulator.app(f"rm -f alpine/workspace-native/{name}.sh alpine/workspace-native/{name}.txt")
            emulator.hdc("shell", "rm", "-f", remote)
        finally:
            emulator.hdc("fport", "rm", *forward)
            options.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
