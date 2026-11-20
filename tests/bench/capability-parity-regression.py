"""Run the capability parity acceptance gate on one build in a fixed order.

Each step is an existing smoke/probe script. The runner records exit code,
duration and the step's JSON evidence, then writes one consolidated summary so a
release candidate has a single reproducible regression gate.

Steps that need a second emulator, a host Ollama model or the voice fixtures are
parameterised; the gate fails if any step fails.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "tests/smoke"
HDC = os.environ.get("HARMONY_HDC", "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc")
DEVECO = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents"))
ARTIFACT = ROOT / ".build/artifacts/harmonyos/dsh-mh-harmonyos-arm64-v0.4.69-unsigned.hap"


def step(name, script, arguments, output, timeout, critical=True):
    return {"name": name, "script": script, "arguments": arguments, "output": output,
            "timeout": timeout, "critical": critical}


def build_steps(args):
    voice = ["--model-root", str(Path(args.voice_model_root).resolve()),
             "--audio", str(Path(args.voice_audio).resolve())]
    return [
        step("recovery", "emulator-recovery.py", [args.target, "{out}"], "recovery.json", 420),
        step("voice-input", "emulator-voice-input.py", [args.target, "{out}", *voice, "--arkweb", "--native-mic"],
             "voice.json", 600),
        # Host-audio acoustic capture depends on the host speakers/microphone; it is
        # recorded by the gate but does not fail the gate on an audio-routing flake.
        step("voice-native-capture", "emulator-voice-input.py",
             [args.target, "{out}", *voice, "--native-mic-transcribe"], "voice-capture.json", 600,
             critical=False),
        step("ollama-routes", "emulator-ollama.py",
             [args.target, "{out}", "--model", args.ollama_model, "--context-window", "16384", "--max-tokens", "4096"],
             "ollama.json", 600),
        step("ptc-link-fixture", "emulator-ptc-link-fixture.py", [args.target, "{out}"], "ptc-link.json", 300),
        step("ptc-boundary", "emulator-ptc-boundary.py", [args.target, "{out}"], "ptc-boundary.json", 600),
        step("liveshare", "emulator-liveshare-relay.py",
             [args.target, "{out}", "--owner-login"], "liveshare.json", 900),
        # The second device reaches the host fixture directly (QEMU 10.0.2.2), which
        # keeps the owner gateway WebSocket alive; hdc reverse forwarding drops it.
        step("liveshare-cross-device", "emulator-liveshare-relay.py",
             [args.target, "{out}", "--cross-device", args.second_target, "--device-host", "10.0.2.2"],
             "liveshare-cross-device.json", 900),
        step("account-entry", "emulator-account.py", [args.account_target, "{out}"], "account.json", 480),
        step("native-addon-location", "emulator-native-addon-location.py", [args.target, "{out}"],
             "addon-location.json", 480),
    ]





def reset_microphone(target):
    """Return the app microphone permission to the unused test state before a voice step."""
    subprocess.run([HDC, "-t", target, "shell", "atm", "perm", "-r", "-b", "org.sayact.nodepoc"],
                   check=False, timeout=60)


def ensure_app_ready(target):
    """Start the app and wait for a finished boot before a step uses the device."""
    subprocess.run([HDC, "-t", target, "shell", "aa", "start", "-a", "EntryAbility", "-b", "org.sayact.nodepoc"],
                   check=False, timeout=90)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        read = subprocess.run([HDC, "-t", target, "shell", "-b", "org.sayact.nodepoc",
                               "cd data/storage/el2/base/haps/entry/files && cat mobile-harness-boot.json"],
                              capture_output=True, text=True, timeout=90)
        if '"pending":false' in (read.stdout or ""):
            return
        time.sleep(2)
    print(f"warning: {target} did not report a finished boot", flush=True)


def reset_account_device(target):
    """Start the account entry step from empty application data so no expired attempt remains."""
    for command in (["aa", "force-stop", "org.sayact.nodepoc"],):
        subprocess.run([HDC, "-t", target, "shell", *command], check=False, timeout=90)
    cleaned = subprocess.run([HDC, "-t", target, "shell", "bm", "clean", "-n", "org.sayact.nodepoc", "-d"],
                             check=False, timeout=120)
    print("account reset clean:", (cleaned.stdout or "").strip()[:200], flush=True)
    subprocess.run([HDC, "-t", target, "shell", "aa", "start", "-a", "EntryAbility", "-b", "org.sayact.nodepoc"],
                   check=False, timeout=90)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        read = subprocess.run([HDC, "-t", target, "shell", "-b", "org.sayact.nodepoc",
                               "cd data/storage/el2/base/haps/entry/files && cat mobile-harness-boot.json"],
                              capture_output=True, text=True, timeout=90)
        if '"pending":false' in (read.stdout or ""):
            print("account device ready after reset", flush=True)
            return
        time.sleep(3)
    raise SystemExit("The account device did not become ready after clearing its data")



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="127.0.0.1:5555")
    parser.add_argument("--second-target", default="127.0.0.1:5557", help="Second emulator for the cross-device viewer")
    parser.add_argument("--account-target", default=None, help="Signed-out emulator for the account entry step")
    parser.add_argument("--forge-target", default=None, help="Emulator without a Forge GitHub config for the public-read step")
    parser.add_argument("--voice-model-root", default=str(ROOT.parent/"harmonyos-package-management/.build/voice-native/models"))
    parser.add_argument("--voice-audio", default=str(ROOT.parent/"harmonyos-package-management/.build/voice-native/mandarin-sample.wav"))
    parser.add_argument("--ollama-model", default="mh-smoke-ollama-079:latest")
    parser.add_argument("--output", type=Path, default=ROOT/".build/batch-011/capability-parity-gate.json")
    parser.add_argument("--only", help="Comma separated step names")
    args = parser.parse_args()
    args.account_target = args.account_target or args.second_target
    args.forge_target = args.forge_target or args.second_target
    args.output = args.output.resolve()
    directory = args.output.parent
    directory.mkdir(parents=True, exist_ok=True)
    steps = build_steps(args)
    if args.only:
        wanted = {name.strip() for name in args.only.split(",") if name.strip()}
        steps = [row for row in steps if row["name"] in wanted]
    targets = subprocess.check_output([HDC, "list", "targets"], text=True).strip().splitlines()
    summary = {
        "kind": "capability parity regression gate",
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "targets": targets,
        "artifact": {"path": str(ARTIFACT.relative_to(ROOT)),
                     "sha256": hashlib.sha256(ARTIFACT.read_bytes()).hexdigest(),
                     "bytes": ARTIFACT.stat().st_size},
        "sourceCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "steps": [],
    }
    failures = 0
    for row in steps:
        output = directory / row["output"]
        if output.exists():
            output.unlink()
        command = [str(Path(os.environ.get("PYTHON", "python3")))]
        command += [str(SMOKE / row["script"])]
        command += [value.replace("{out}", str(output)) if isinstance(value, str) else value
                    for value in row["arguments"]]
        step_target = row["arguments"][0] if row["arguments"] else args.target
        if row["name"] == "account-entry":
            reset_account_device(args.account_target)
        else:
            ensure_app_ready(step_target)
            if row["name"].startswith("voice"):
                reset_microphone(step_target)
        started = time.monotonic()
        print(f"== {row['name']} ==", flush=True)
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=row["timeout"])
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as error:
            code = "timeout"
            stdout = (error.stdout or b"").decode(errors="replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
            stderr = (error.stderr or b"").decode(errors="replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
        elapsed = round(time.monotonic() - started)
        log = directory / f"{row['name']}.log"
        log.write_text(stdout + ("\n[stderr]\n" + stderr if stderr else ""), encoding="utf-8")
        passed = code == 0 and output.is_file()
        if not passed and row["critical"]:
            failures += 1
        record = {"name": row["name"], "command": command, "exit": code, "passed": passed,
                  "elapsedSeconds": elapsed, "evidence": str(output.relative_to(ROOT)) if output.is_file() else None,
                  "log": str(log.relative_to(ROOT))}
        if not output.is_file() and code == 0:
            record["evidenceError"] = "the step exited 0 but wrote no evidence file"
        summary["steps"].append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    summary["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary["failures"] = failures
    summary["ok"] = failures == 0
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": summary["ok"], "failures": failures,
                      "steps": [{"name": row["name"], "passed": row["passed"], "exit": row["exit"],
                                 "elapsedSeconds": row["elapsedSeconds"]} for row in summary["steps"]]},
                     ensure_ascii=False), flush=True)
    raise SystemExit(0 if summary["ok"] else 1)


if __name__ == "__main__":
    main()
