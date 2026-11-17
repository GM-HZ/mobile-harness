"""Mount actual Office providers to verify cancellation, disposal, timeouts, and helper crash recovery."""
import argparse
import io
import json
import os
from pathlib import Path
import runpy
import tarfile
import tempfile
import time
import uuid

office = runpy.run_path(str(Path(__file__).with_name("emulator-office.py")))
toolkit = office["toolkit"]
support = office["support"]
ROOT = Path(__file__).resolve().parents[2]
PROFILE = "alpine/native-benchmark-home/profiles/web"


def archive_fixture(destination, name):
    version = json.loads((ROOT / "runtime/harmonyos/dsh/package.json").read_text())["dependencies"]["@deepseek-ai/dsh"]
    packages = support["WORKSPACE"].rsplit("/", 1)[0] + f"/.dsh-{version}/dsh/node_modules/@deepseek-ai/"
    source = Path(__file__).with_name("fixtures").joinpath("office-provider.mjs").read_text()
    source = source.replace("__MH_DSH_PACKAGES__", json.dumps("file://" + packages))
    source = source.replace("__MH_WORKSPACE__", json.dumps(support["WORKSPACE"] + "/" + name))
    files = {
        "package.json": json.dumps({
            "name": name, "version": "1.0.0", "type": "module", "main": "index.js",
            "files": ["index.js", "input.docx", "cordis.patch.yml"],
            "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
        }).encode(),
        "cordis.patch.yml": f"- insert:\n    - id: {name}\n      name: {name}\n".encode(),
        "index.js": source.encode(),
    }
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        office["fixtures"](folder, "HARMONY_OFFICE_PROVIDER_" + uuid.uuid4().hex.upper())
        files["input.docx"] = (folder / "input.docx").read_bytes()
    with tarfile.open(destination, "w:gz", format=tarfile.USTAR_FORMAT) as archive:
        for filename, data in files.items():
            entry = tarfile.TarInfo(filename); entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))


def command(emulator, sid, action, case):
    args = {"action": action, "case": case}
    calls, results = toolkit["prompt"](emulator, sid,
        "Call mh_office_provider exactly once with precisely " + json.dumps(args)
        + ". Report its JSON result and take no other action.", timeout=225)
    assert len(calls) == len(results) == 1 and calls[0]["name"] == "mh_office_provider", calls
    assert json.loads(calls[0]["arguments"]) == args, calls
    assert not results[0]["isError"], toolkit["texts"](results)
    return json.loads(toolkit["texts"](results))


def wait_trace(emulator, predicate, seconds=12):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        trace = office["trace"](emulator)
        if predicate(trace): return trace
        time.sleep(.1)
    raise AssertionError("Office helper did not reach its expected lifecycle state")


def verify(emulator, cases, evidence):
    sid = support["session"](emulator, True)
    try:
        for case in cases:
            evidence[case] = record = {}
            before_workers = {row["id"] for row in office["trace"](emulator) if row["event"] == "office-worker-started"}
            before = {row["request"] for row in office["trace"](emulator) if row["event"] == "office-operation-running"}
            record["created"] = command(emulator, sid, "create", case)
            if case in {"active", "cancel"}:
                assert record["created"]["actedWhilePending"] and record["created"]["status"] == "error", record
                assert any(row["event"] == "office-operation-running" and row["request"] not in before for row in office["trace"](emulator))
                record["observedActiveOperation"] = True
            if case == "timeout":
                assert record["created"]["status"] == "error" and record["created"]["code"] == "timeout", record
            if case in {"idle", "crash"}:
                assert record["created"]["status"] == "completed" and record["created"]["bytes"] > 100, record
            if case == "cancel":
                record["cancelled"] = record["created"]
                record["retried"] = command(emulator, sid, "retry", case)
                assert record["retried"]["status"] == "completed", record
            if case == "crash":
                record["crashed"] = command(emulator, sid, "crash", case)
                worker = record["crashed"]["workerId"]
                wait_trace(emulator, lambda rows: any(row["event"] == "office-worker-reaped" and row["id"] == worker for row in rows))
                record["retried"] = command(emulator, sid, "retry", case)
                assert record["retried"]["status"] == "completed" and record["retried"]["bytes"] > 0, record
            record["disposed"] = command(emulator, sid, "dispose", case)
            disposed = record["disposed"]
            assert disposed["closed"] and disposed["postDisposeRejected"] and disposed["remainingScratch"] == 0, record
            assert disposed["elapsedMs"] < 12000, record
            if case == "active": assert disposed["status"] == "error", record
            worker = disposed["workerId"]
            assert worker and any(row["event"] == "office-worker-reaped" and row["id"] == worker for row in office["trace"](emulator)), record
            final_trace = office["trace"](emulator)
            owned_workers = {row["id"] for row in final_trace if row["event"] == "office-worker-started"} - before_workers
            reaped_workers = {row["id"] for row in final_trace if row["event"] == "office-worker-reaped"}
            assert owned_workers and owned_workers <= reaped_workers, (owned_workers, reaped_workers)
            record["allOwnedHelpersReaped"] = len(owned_workers)
            print(case, json.dumps(record), flush=True)
    finally:
        emulator.rpc("session/cancel", {"request": {"sessionId": sid}})


def run(emulator, cases, evidence):
    name = "mh-office-provider-" + uuid.uuid4().hex[:10]
    remote = "/data/local/tmp/" + name
    backup = f"{PROFILE}/package.json.{name}"
    lock_backup = f"{PROFILE}/pnpm-lock.yaml.{name}"
    boot_backup = "mobile-harness-boot.json." + name
    saved = False; had_lock = False
    try:
        emulator.ready("normal")
        assert emulator.app(f"cp {PROFILE}/package.json {backup} && cp mobile-harness-boot.json {boot_backup} && printf SAVED") == "SAVED"
        saved = True
        had_lock = emulator.app(f"test -e {PROFILE}/pnpm-lock.yaml && printf PRESENT") == "PRESENT"
        if had_lock: emulator.app(f"cp {PROFILE}/pnpm-lock.yaml {lock_backup}")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); archive = folder / "fixture.tgz"
            archive_fixture(archive, name)
            assert "FileTransfer finish" in emulator.hdc("file", "send", str(archive), remote + ".tgz")
            assert emulator.app(f"mkdir alpine/workspace-native/{name} && tar -xzf {remote}.tgz -C alpine/workspace-native/{name} && printf READY") == "READY"
            installed = emulator.rpc("pluginManager/installBundle", {
                "spec": f"file:{support['WORKSPACE']}/{name}", "options": {"enabled": False},
            }, timeout=90)
            assert installed.get("enabled") is False
            emulator.stop()
            profile = json.loads(emulator.app(f"cat {PROFILE}/package.json"))
            profile["dsh"]["profile"]["bundles"].append(name)
            manifest = folder / "package.json"; manifest.write_text(json.dumps(profile) + "\n")
            assert "FileTransfer finish" in emulator.hdc("file", "send", str(manifest), remote + ".json")
            emulator.app(f"cp {remote}.json {PROFILE}/package.json")
        emulator.start(); evidence["readyMs"] = emulator.ready("normal")
        with support["model_key"](emulator): verify(emulator, cases, evidence)
        evidence["temporaryModelCredentialRemoved"] = True
    finally:
        try:
            if saved:
                emulator.stop()
                assert emulator.app(f"cp {backup} {PROFILE}/package.json && cmp -s {backup} {PROFILE}/package.json && cp {boot_backup} mobile-harness-boot.json && printf RESTORED") == "RESTORED"
                if had_lock:
                    assert emulator.app(f"cp {lock_backup} {PROFILE}/pnpm-lock.yaml && cmp -s {lock_backup} {PROFILE}/pnpm-lock.yaml && printf RESTORED") == "RESTORED"
                else: emulator.app(f"rm -f {PROFILE}/pnpm-lock.yaml")
                emulator.app(f"rm -f {backup} {lock_backup} {boot_backup}; rm -rf alpine/workspace-native/{name} {PROFILE}/node_modules/{name}")
                emulator.start(); emulator.ready("normal"); evidence["originalProfileRestored"] = True
        finally:
            emulator.hdc("shell", "rm", "-f", remote + ".tgz", remote + ".json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target"); parser.add_argument("output", type=Path)
    parser.add_argument("--case", choices=("idle", "active", "cancel", "timeout", "crash"))
    options = parser.parse_args()
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"): parser.error("MH_TEST_DEEPSEEK_API_KEY is required")
    emulator = support["Emulator"](options.target, 19649); forward = ("tcp:19649", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    evidence = {}
    try:
        run(emulator, [options.case] if options.case else ["idle", "active", "cancel", "timeout", "crash"], evidence)
    finally:
        options.output.write_text(json.dumps(evidence, indent=2) + "\n")
        emulator.hdc("fport", "rm", *forward)
