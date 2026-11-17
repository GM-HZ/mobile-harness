"""Cancel a real model's Office tool through session/cancel, then use the same Session again."""
import argparse
import json
import os
from pathlib import Path
import runpy
import tempfile
import time
import uuid

office = runpy.run_path(str(Path(__file__).with_name("emulator-office.py")))
toolkit = office["toolkit"]
support = office["support"]


def scratch(emulator):
    return set(emulator.app("ls -d alpine/tmp/dsh-office-kit-* 2>/dev/null || true").splitlines())


def run(emulator, output):
    name = "mh-office-cancel-" + uuid.uuid4().hex[:10]
    app = "alpine/workspace-native/" + name
    path = support["WORKSPACE"] + "/" + name + "/input.docx"
    remote = "/data/local/tmp/" + name + ".docx"
    evidence = {}
    sid = None
    try:
        emulator.ready("normal"); emulator.app(f"mkdir -p {app}")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            office["fixtures"](folder, "HARMONY_OFFICE_CANCEL_" + uuid.uuid4().hex.upper())
            assert "FileTransfer finish" in emulator.hdc("file", "send", str(folder / "input.docx"), remote)
            emulator.app(f"cp {remote} {app}/input.docx")
        with support["model_key"](emulator):
            sid = support["session"](emulator, True)
            evidence["sessionId"] = sid
            office["invoke"](emulator, sid, "skill", {"name": "office"})
            old = support["events"](emulator, sid)
            previous_turns = sum(row["type"] == "turn/end" for row in old)
            before = {row["request"] for row in office["trace"](emulator) if row["event"] == "office-operation-running"}
            initial_scratch = scratch(emulator)
            args = {"input": path, "format": "pdf"}
            emulator.rpc("session/prompt", {"request": {
                "sessionId": sid, "requestId": str(uuid.uuid4()), "mode": "queue",
                "content": [{"type": "text", "text": "Call office_convert once with exactly " + json.dumps(args)
                             + ". This is a controlled cancellation fixture. Do not retry or call other tools."}],
            }})
            end = time.monotonic() + 35
            while time.monotonic() < end:
                running = [row for row in office["trace"](emulator)
                           if row["event"] == "office-operation-running" and row["request"] not in before]
                if running: break
                time.sleep(.02)
            else: raise AssertionError("The real Office tool never started its engine operation")
            request = running[0]["request"]
            assert not any(row["event"] == "office-operation-ended" and row["request"] == request
                           for row in office["trace"](emulator)), "The fixture missed the in-flight operation"
            started = time.monotonic()
            assert emulator.rpc("session/cancel", {"request": {"sessionId": sid}})["accepted"]
            end = started + 12
            while time.monotonic() < end:
                rows = support["events"](emulator, sid)
                turns = [row for row in rows if row["type"] == "turn/end"]
                finished = [row for row in office["trace"](emulator)
                            if row["event"] == "office-operation-ended" and row["request"] == request]
                if len(turns) > previous_turns and finished and scratch(emulator) <= initial_scratch:
                    assert turns[previous_turns]["data"]["reason"]["kind"] == "aborted"
                    assert finished[0]["code"] != "completed"
                    break
                time.sleep(.05)
            else: raise AssertionError("Session cancellation did not settle the Office operation and scratch cleanup")
            evidence["gatewayCancellation"] = {"accepted": True, "observedInFlight": True, "turn": "aborted",
                                               "engineSettled": True, "scratchRemoved": True,
                                               "elapsedMs": round((time.monotonic() - started) * 1000)}
            result, elapsed = office["invoke"](emulator, sid, "office_convert", args, preamble=(
                "The previous conversion was deliberately cancelled and that request is finished. "
                "This is a NEW request to actually execute a new conversion now in this same session. "
                "Do not summarize the previous call or report its cancelled result. "))
            destination = output.with_suffix(".pdf")
            record = office["file_result"](emulator, result, destination)
            assert destination.read_bytes().startswith(b"%PDF-")
            evidence["sameSessionAfterCancel"] = {**record, "promptElapsedMs": elapsed}
        evidence["temporaryModelCredentialRemoved"] = True
        evidence["trace"] = office["trace"](emulator)
    finally:
        try:
            if sid is not None: emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
            emulator.app(f"rm -rf {app}"); emulator.hdc("shell", "rm", "-f", remote)
        finally: output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target"); parser.add_argument("output", type=Path)
    options = parser.parse_args()
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"): parser.error("MH_TEST_DEEPSEEK_API_KEY is required")
    emulator = support["Emulator"](options.target, 19643); forward = ("tcp:19643", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc("fport", "rm", *forward)
