"""Mount official Ralph/session-search bundles temporarily and exercise actual phone tools."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import tempfile
import time
import uuid

agent = runpy.run_path(str(Path(__file__).with_name("emulator-agent-continuation.py")))
support = agent["support"]
toolkit = agent["toolkit"]
PROFILE = "alpine/native-benchmark-home/profiles/web"
BUNDLES = ["@deepseek-ai/dsh-experimental-ralph-bundle", "@deepseek-ai/dsh-experimental-session-search"]


def ralph(emulator, evidence, name):
    path = support["WORKSPACE"] + "/" + name
    app = "alpine/workspace-native/" + name
    marker = "RALPHFILE" + uuid.uuid4().hex.upper()
    secret = "PARENTONLY" + uuid.uuid4().hex.upper()
    sid = support["session"](emulator, True); evidence["sessionId"] = sid
    try:
        calls, _, _ = agent["prompt"](emulator, sid, "Remember this harmless parent-only token in this conversation: " + secret + ". Reply ACK without tools.")
        assert not calls
        objective = ("This explicitly requested Ralph acceptance task requires TWO fresh rounds and only two owned files. "
                     "In Ralph round1, use write exactly once with " + json.dumps({"file_path": path + "/stage.txt", "content": marker})
                     + ". Keep content exact, with no final newline. Then report status continue, evidence of that write, "
                     "one nextSteps entry to verify the file in round2, and an empty blocker. Do not create verified.txt in round1. "
                     "In Ralph round2, read " + path + "/stage.txt, verify its marker, then use write exactly once with "
                     + json.dumps({"file_path": path + "/verified.txt", "content": marker})
                     + ". Report complete with evidence and no nextSteps, blocker empty. Use the required structured report tool. "
                     "Do not use Bash, create other agents or goals, or touch other files.")
        result, rows = agent["tool"](emulator, sid, "ralph", {"objective": objective, "maxRounds": 2})
        text = toolkit["texts"]([result])
        assert text.startswith("Ralph worker reported completion after 2 rounds."), text
        assert agent["read_bytes"](emulator, app + "/stage.txt") == marker.encode()
        assert agent["read_bytes"](emulator, app + "/verified.txt") == marker.encode()
        catalogs = [r["data"] for r in rows if r["type"] == "subagent/catalog"]
        assert len(catalogs) == 2 and len({c["childId"] for c in catalogs}) == 2, catalogs
        evidence["twoDistinctFreshChildren"] = []
        for index, child in enumerate(catalogs):
            child_rows = agent["child_events"](emulator, sid, child["childId"])
            descriptors = [r for r in child_rows if r["type"] == "subagent/descriptor"]
            assert len(descriptors) == 1 and descriptors[0]["data"]["provider"] == "spawn", descriptors
            assert not any(r["type"] in {"user/message", "assistant/message"} and r["seq"] < descriptors[0]["seq"] for r in child_rows)
            assert secret not in json.dumps(child_rows), "A fresh Ralph child inherited parent-only conversation"
            names = [r["data"]["name"] for r in child_rows if r["type"] == "tool/call"]
            assert "write" in names and (index == 0 or "read" in names), names
            ends = [r for r in child_rows if r["type"] == "turn/end"]
            assert ends[-1]["data"]["reason"]["kind"] == "completed", ends
            evidence["twoDistinctFreshChildren"].append({"id": child["childId"], "provider": "spawn", "noParentSeed": True, "actualTools": names})
        evidence["actualFilesByteEqual"] = True
        evidence["actualFileBytes"] = len(marker.encode())
        evidence["report"] = json.loads(text.split("Final report:\n", 1)[1])
    finally:
        emulator.rpc("session/cancel", {"request": {"sessionId": sid}})


def worker_trace(emulator):
    return [json.loads(row) for row in emulator.app("grep workflow-worker- alpine/tmp/dsh-native-timeline.log || true").splitlines()]


def cancel_ralph(emulator, evidence):
    sid = support["session"](emulator, True); evidence["sessionId"] = sid
    before = {row["id"] for row in worker_trace(emulator)}
    try:
        args = {"objective": "This explicitly requested, read-only Ralph cancellation acceptance asks the fresh child to compose a detailed 1200-word history of paper as its structured report summary. Do not call tools, modify files, create other agents or goals. The acceptance harness will cancel during the actual child model request.", "maxRounds": 1}
        emulator.rpc("session/prompt", {"request": {
            "sessionId": sid, "requestId": str(uuid.uuid4()), "mode": "queue",
            "content": [{"type": "text", "text": "Actually call ralph exactly once now with precisely " + json.dumps(args)
                         + ". This is the explicitly authorized isolated cancellation test; call no other tool and do not retry."}],
        }})
        deadline = time.monotonic() + 30
        child = None
        while time.monotonic() < deadline:
            rows = support["events"](emulator, sid)
            children = [r["data"]["childId"] for r in rows if r["type"] == "subagent/catalog"]
            if children:
                assert len(children) == 1
                child = children[0]; child_rows = agent["child_events"](emulator, sid, child)
                if any(r["type"] == "request/header" for r in child_rows):
                    assert not any(r["type"] == "turn/end" for r in child_rows), "Missed the active child"
                    break
            time.sleep(.03)
        else: raise AssertionError("Ralph never reached a real child model request")
        calls = [r["data"] for r in rows if r["type"] == "tool/call"]
        assert len(calls) == 1 and calls[0]["name"] == "ralph" and json.loads(calls[0]["arguments"]) == args, calls
        started = time.monotonic()
        assert emulator.rpc("session/cancel", {"request": {"sessionId": sid}})["accepted"]
        deadline = started + 12
        while time.monotonic() < deadline:
            rows = support["events"](emulator, sid)
            ends = [r for r in rows if r["type"] == "turn/end"]
            trace = worker_trace(emulator)
            created = {r["id"] for r in trace if r["id"] not in before}
            reaped = {r["id"] for r in trace if r["event"] == "workflow-worker-reaped"}
            child_rows = agent["child_events"](emulator, sid, child)
            child_ends = [r for r in child_rows if r["type"] == "turn/end"]
            if ends and created and created <= reaped and child_ends:
                assert ends[-1]["data"]["reason"]["kind"] == "aborted", ends
                assert child_ends[-1]["data"]["reason"]["kind"] == "aborted", child_ends
                break
            time.sleep(.05)
        else: raise AssertionError("Cancelled Ralph did not settle both the child and all helper processes")
        evidence.update(actualChildRequestObserved=True, childSessionId=child, rootAndChildAborted=True,
                        helpersCreatedAndReaped=sorted(created), elapsedMs=round((time.monotonic()-started)*1000))
    finally:
        emulator.rpc("session/cancel", {"request": {"sessionId": sid}})


def search_scope(emulator, evidence, name):
    foreign_app = "alpine/" + name + "-foreign"
    foreign_path = support["WORKSPACE"].rsplit("/", 1)[0] + "/" + name + "-foreign"
    private = "SESSIONPRIVATE" + uuid.uuid4().hex.upper()
    foreign = None; caller = None
    try:
        emulator.app(f"mkdir -p {foreign_app}")
        workspace = emulator.rpc("workspace/create", {"request": {"path": foreign_path}})["workspace"]
        foreign = emulator.rpc("session/create", {"request": {"workspaceId": workspace["workspaceId"]}})["sessionId"]
        emulator.rpc("session/selectModel", {"request": {"sessionId": foreign, "provider": "deepseek-official", "model": "deepseek-flash", "reasoningEffort": "off"}})
        _, _, rows = agent["prompt"](emulator, foreign, "Reply with exactly " + private + ". Do not use tools.")
        answer = next(r for r in rows if r["type"] == "assistant/message" and private in json.dumps(r["data"]["message"]["content"]))
        caller = support["session"](emulator, True)
        result, _ = agent["tool"](emulator, caller, "session_search", {"query": "SESSIONPRIVATE", "session_ids": [foreign]})
        assert toolkit["texts"]([result]) == "No prior session matches found.", result
        result, _ = agent["tool"](emulator, caller, "session_event_read", {"session_id": foreign, "seq": answer["seq"]}, expect_error=True)
        text = toolkit["texts"]([result])
        assert text == "Error: session target is outside the caller workspace", text
        assert private not in text
        evidence.update(foreignSessionId=foreign, callerSessionId=caller, crossWorkspaceSearchEmpty=True, explicitForeignReadDenied=True, privateContentNotReturned=True)
    finally:
        if caller: emulator.rpc("session/cancel", {"request": {"sessionId": caller}})
        if foreign:
            emulator.rpc("session/cancel", {"request": {"sessionId": foreign}})
            emulator.rpc("workspace/archiveSession", {"request": {"sessionId": foreign}})
        emulator.app(f"rm -rf {foreign_app}")


def search(emulator, evidence):
    marker = "SESSIONHISTORY" + uuid.uuid4().hex.upper()
    history_sid = support["session"](emulator, True)
    calls, _, rows = agent["prompt"](emulator, history_sid, "Reply with exactly " + marker + ". Do not call tools.")
    assert not calls
    answer = next(r for r in rows if r["type"] == "assistant/message" and marker in json.dumps(r["data"]["message"]["content"]))
    archived = emulator.rpc("workspace/archiveSession", {"request": {"sessionId": history_sid}})
    assert history_sid in archived["archivedSessionIds"]
    evidence["sourceSessionId"] = history_sid; evidence["sourceEventSeq"] = answer["seq"]
    sid = None
    try:
        emulator.stop(); emulator.start(); evidence["restartReadyMs"] = emulator.ready("normal")
        sid = support["session"](emulator, True); evidence["querySessionId"] = sid
        result, _ = agent["tool"](emulator, sid, "session_search", {"query": marker, "session_ids": [history_sid], "availability": ["persisted"]})
        text = toolkit["texts"]([result])
        assert "Session search results (1)" in text and history_sid in text and marker in text, text
        evidence["persistedArchivedSessionFoundAfterRestart"] = True
        result, _ = agent["tool"](emulator, sid, "session_event_search", {"session_id": history_sid, "query": marker, "event_types": ["assistant/message"]})
        assert marker in toolkit["texts"]([result]) and str(answer["seq"]) in toolkit["texts"]([result])
        result, _ = agent["tool"](emulator, sid, "session_event_read", {"session_id": history_sid, "seq": answer["seq"]})
        event_json = re.search(r"```json\n(.*?)\n```", toolkit["texts"]([result]), re.S)
        assert event_json
        event = json.loads(event_json[1]); assert event["seq"] == answer["seq"]
        assert marker in json.dumps(event), event
        evidence["exactEventRead"] = True
        for name, args in [("session_event_trace", {"session_id": history_sid, "seq": answer["seq"]}), ("session_trace", {"session_id": history_sid})]:
            result, _ = agent["tool"](emulator, sid, name, args)
            assert history_sid in toolkit["texts"]([result]), result
        evidence["eventAndSessionTrace"] = True
    finally:
        if sid: emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
        emulator.rpc("workspace/unarchiveSession", {"request": {"sessionId": history_sid}})
        evidence["sourceArchiveStateRestored"] = True


def run(emulator, output, case):
    name = "mh-optional-" + uuid.uuid4().hex[:10]
    backup = PROFILE + "/" + name + ".package.bak"
    lock_backup = PROFILE + "/" + name + ".lock.bak"
    boot_backup = "mobile-harness-boot.json." + name
    remote = "/data/local/tmp/" + name + ".json"
    saved = False
    had_lock = False
    evidence = {"fixture": name, "enabledBundles": BUNDLES}
    try:
        emulator.ready("normal")
        assert emulator.app("test ! -e alpine/native-benchmark-home/cordis.patch.yml && printf EMPTY") == "EMPTY"
        assert emulator.app(f"cp {PROFILE}/package.json {backup} && cp mobile-harness-boot.json {boot_backup} && printf SAVED") == "SAVED"
        saved = True
        evidence["manifestBeforeSha256"] = hashlib.sha256(agent["read_bytes"](emulator, PROFILE + "/package.json")).hexdigest()
        had_lock = emulator.app(f"test -e {PROFILE}/pnpm-lock.yaml && printf PRESENT || printf ABSENT") == "PRESENT"
        if had_lock: emulator.app(f"cp {PROFILE}/pnpm-lock.yaml {lock_backup}")
        evidence["lockBeforeSha256"] = hashlib.sha256(agent["read_bytes"](emulator, PROFILE + "/pnpm-lock.yaml")).hexdigest() if had_lock else None
        manifest = json.loads(emulator.app(f"cat {PROFILE}/package.json"))
        original_bundles = manifest["dsh"]["profile"]["bundles"]
        assert not any(bundle in original_bundles for bundle in BUNDLES), "Optional bundle already user-enabled; do not alter it"
        manifest["dsh"]["profile"]["bundles"] = original_bundles + BUNDLES
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary) / "package.json"; local.write_text(json.dumps(manifest) + "\n")
            assert "FileTransfer finish" in emulator.hdc("file", "send", str(local), remote)
        emulator.stop(); emulator.app(f"cp {remote} {PROFILE}/package.json"); emulator.start()
        evidence["optionalProfileReadyMs"] = emulator.ready("normal")
        emulator.app(f"mkdir -p alpine/workspace-native/{name}")
        with support["model_key"](emulator):
            if case in {"all", "ralph"}:
                evidence["ralph"] = {}; ralph(emulator, evidence["ralph"], name)
            if case in {"all", "search"}:
                evidence["search"] = {}; search(emulator, evidence["search"])
            if case in {"all", "cancel"}:
                evidence["cancel"] = {}; cancel_ralph(emulator, evidence["cancel"])
            if case in {"all", "scope"}:
                evidence["scope"] = {}; search_scope(emulator, evidence["scope"], name)
        evidence["temporaryModelCredentialRemoved"] = True
    finally:
        try:
            if saved:
                emulator.stop()
                assert emulator.app(f"cp {backup} {PROFILE}/package.json && cmp -s {backup} {PROFILE}/package.json && cp {boot_backup} mobile-harness-boot.json && printf RESTORED") == "RESTORED"
                if had_lock:
                    assert emulator.app(f"cp {lock_backup} {PROFILE}/pnpm-lock.yaml && cmp -s {lock_backup} {PROFILE}/pnpm-lock.yaml && printf RESTORED") == "RESTORED"
                else: emulator.app(f"rm -f {PROFILE}/pnpm-lock.yaml")
                emulator.app(f"rm -f {backup} {lock_backup} {boot_backup}; rm -rf alpine/workspace-native/{name}")
                emulator.start(); emulator.ready("normal"); evidence["exactOriginalManifestRestored"] = True
                evidence["exactOriginalLockRestored"] = True
                evidence["manifestAfterSha256"] = hashlib.sha256(agent["read_bytes"](emulator, PROFILE + "/package.json")).hexdigest()
                assert evidence["manifestAfterSha256"] == evidence["manifestBeforeSha256"]
                lock_exists = emulator.app(f"test -e {PROFILE}/pnpm-lock.yaml && printf PRESENT || printf ABSENT") == "PRESENT"
                evidence["lockAfterSha256"] = hashlib.sha256(agent["read_bytes"](emulator, PROFILE + "/pnpm-lock.yaml")).hexdigest() if lock_exists else None
                assert evidence["lockAfterSha256"] == evidence["lockBeforeSha256"]
            emulator.hdc("shell", "rm", "-f", remote)
        finally: output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target"); parser.add_argument("output", type=Path)
    parser.add_argument("--case", choices=["all", "ralph", "search", "cancel", "scope"], default="all")
    options = parser.parse_args()
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"): parser.error("MH_TEST_DEEPSEEK_API_KEY is required")
    emulator = support["Emulator"](options.target, 19643)
    forward = ("tcp:19643", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    try: run(emulator, options.output, options.case)
    finally: emulator.hdc("fport", "rm", *forward)
