"""Exercise the production DSH Workflow tool on an isolated HarmonyOS Phone emulator."""
import argparse
from concurrent.futures import ThreadPoolExecutor
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
STARTED = {}


def start_workflow(emulator, script, name, background=False):
    session_id = session(emulator, True)
    arguments = json.dumps({
        "meta": {"name": name, "description": "HarmonyOS Workflow acceptance"},
        "script": script, "run_in_background": background,
    })
    purpose = ("This tests the managed worker's synchronous timeout, so the deliberate infinite loop must be terminated by its enforced budget. "
               if name == "mh-workflow-timeout" else
               "This tests in-flight cancellation; the external acceptance harness will cancel the run as soon as its start is observed. "
               if "cancel" in name else "")
    prompt = ("This is an explicitly authorized, isolated local acceptance fixture in a supervised worker. " + purpose
              + f"Actually call workflow once now with exactly these arguments: {arguments}. "
              "Do not rewrite the fixture, retry, or call another tool.")
    STARTED[name] = session_id
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


def worker_trace(emulator):
    return [json.loads(row) for row in emulator.app("grep workflow-worker- alpine/tmp/dsh-native-timeline.log || true").splitlines()]


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

    previous_workers = {row["id"] for row in worker_trace(emulator)}
    sid = start_workflow(emulator, "const until = Date.now() + 60000; while (Date.now() < until) {} return 'natural-end';", "mh-workflow-cancel")
    wait_for(emulator, sid, lambda rows: bool(of_type(rows, "tool-workflow/run-start")))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        trace = worker_trace(emulator)
        running = [row["id"] for row in trace if row["event"] == "workflow-worker-running" and row["id"] not in previous_workers]
        if running:
            assert not any(row["event"] == "workflow-worker-reaped" and row["id"] in running for row in trace)
            break
        time.sleep(.02)
    else: raise AssertionError("The cancellation fixture did not enter an actual synchronous worker slice")
    assert emulator.rpc("session/cancel", {"request": {"sessionId": sid}})["accepted"]
    records = wait_for(emulator, sid, lambda rows: bool(of_type(rows, "tool-workflow/run-end")))
    assert run_result(records, "cancelled"), of_type(records, "tool-workflow/run-end")
    assert all(any(row["event"] == "workflow-worker-reaped" and row["id"] == worker for row in worker_trace(emulator)) for worker in running)
    evidence["cancelledDuringSyncSlice"] = True
    evidence["cancelledSyncWorkersReaped"] = running

    sid = start_workflow(emulator, "await agent('Write a long essay, with 600 words, about the history of paper.');", "mh-workflow-cancel-child")
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


def verify_concurrent_fanout(emulator, evidence):
    previous_workers = {row["id"] for row in worker_trace(emulator)}
    nonce = uuid.uuid4().hex[:12].upper()
    case_names = ["alpha", "beta"]
    markers = {case: [f"MH_FANOUT_{nonce}_{case.upper()}_{index}" for index in range(4)]
               for case in case_names}

    def launch(case):
        prompts = ["Reply only with the exact marker " + marker + ". Do not call tools."
                   for marker in markers[case]]
        script = "return await parallel([" + ",".join(
            "() => agent(" + json.dumps(prompt) + ")" for prompt in prompts) + "]);"
        return start_workflow(emulator, script, "mh-fanout-" + case)

    with ThreadPoolExecutor(max_workers=2) as threads:
        sessions = dict(zip(case_names, threads.map(launch, case_names), strict=True))
    spans = []
    evidence["fanout"] = {}
    for case, sid in sessions.items():
        records = wait_for(emulator, sid, lambda rows: bool(of_type(rows, "tool-workflow/run-end")
                                                           and of_type(rows, "tool/result")), timeout=90)
        run_start, = of_type(records, "tool-workflow/run-start")
        run_end, = of_type(records, "tool-workflow/run-end")
        starts = of_type(records, "tool-workflow/agent-start")
        ends = of_type(records, "tool-workflow/agent-end")
        assert run_result(records, "completed"), run_end["data"]
        assert len(starts) == len(ends) == 4 and all(row["data"]["outcome"] == "completed" for row in ends)
        assert len({row["data"]["childId"] for row in starts}) == 4
        active = set()
        peak = 0
        for row in records:
            if row["type"] == "tool-workflow/agent-start":
                active.add(row["data"]["seq"])
                peak = max(peak, len(active))
            if row["type"] == "tool-workflow/agent-end":
                active.remove(row["data"]["seq"])
        assert peak >= 2 and not active
        text = json.dumps(of_type(records, "tool/result"))
        assert all(marker in text for marker in markers[case])
        assert all(marker not in text for other in case_names if other != case for marker in markers[other])
        spans.append((run_start["time"], run_end["time"]))
        evidence["fanout"][case] = {"children": 4, "peakConcurrentChildren": peak, "allMarkersReturned": True,
                                     "isolatedResults": True, "runMs": run_end["time"] - run_start["time"]}
    overlap = min(end for _, end in spans) - max(start for start, _ in spans)
    assert overlap > 0, spans
    evidence["overlappingParentRunsMs"] = overlap
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        trace = worker_trace(emulator)
        running = {row["id"] for row in trace if row["event"] == "workflow-worker-running"} - previous_workers
        reaped = {row["id"] for row in trace if row["event"] == "workflow-worker-reaped"} - previous_workers
        if len(running) >= 2 and running <= reaped:
            evidence["workersReaped"] = len(running)
            return
        time.sleep(.1)
    raise AssertionError("Concurrent Workflow helpers did not all exit")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--host-port", type=int, default=19641)
    parser.add_argument("--fanout-only", action="store_true", help="Exercise two parent Workflows with four concurrent children each")
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
            try:
                if options.fanout_only:
                    verify_concurrent_fanout(emulator, evidence)
                else:
                    verify_workflow(emulator, evidence)
            finally:
                # Cancel only this fixture's root Sessions before removing their temporary key.
                for sid in STARTED.values():
                    emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
                    if options.fanout_only:
                        emulator.rpc("workspace/archiveSession", {"request": {"sessionId": sid}})
                evidence["sessions"] = dict(STARTED)
        evidence["temporaryModelCredentialRemoved"] = True
    finally:
        options.output.write_text(json.dumps(evidence, indent=2) + "\n")
        emulator.hdc("fport", "rm", *forward)


if __name__ == "__main__":
    main()
