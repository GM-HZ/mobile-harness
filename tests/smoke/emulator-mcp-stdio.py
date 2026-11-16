"""Probe real Node and Python MCP stdio servers on the HarmonyOS Phone emulator."""
import argparse
import json
from pathlib import Path
import runpy
import time
import uuid

tests = runpy.run_path(str(Path(__file__).with_name("emulator-dsh-capabilities.py")))


def verify(emulator, has_model, interpreter, filename, output):
    name = "mh-stdio-" + uuid.uuid4().hex[:10]
    source = Path(__file__).with_name("fixtures") / filename
    guest = name + source.suffix
    remote = f"/data/local/tmp/{guest}"
    active = f"alpine/workspace-native/{guest}"
    settings = tests["mcp_settings"]
    set_settings = tests["set_mcp_settings"]
    before = settings(emulator)
    original = before["user"]
    servers = dict(original.get("servers", {}))
    servers[name] = {
        "transport": "stdio", "command": interpreter, "args": [guest, "literal '$(); \" argument"],
        "cwd": "/workspace-native", "env": {"MH_FIXTURE": "space 'quote'\nnext"},
        "enabled": False, "startupTimeoutMs": 10_000,
    }
    try:
        assert "FileTransfer finish" in emulator.hdc("file", "send", str(source), remote)
        assert emulator.app(f"cp {remote} {active} && echo READY") == "READY"
        updated = set_settings(emulator, {**original, "servers": servers}, before["revision"])
        probe = emulator.rpc("mcpManager/probe", {"name": name})
        output["probe"] = probe
        assert probe["ok"] and probe["closeConfirmed"] and probe["toolNames"] == ["stdio_fixture_echo"], probe
        if not has_model:
            return

        servers[name]["enabled"] = True
        servers[name]["env"]["MH_LIVE"] = "1"
        set_settings(emulator, {**original, "servers": servers}, updated["revision"])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if emulator.app(f"test ! -f {active}.ready || cat {active}.ready") == "ok":
                break
            time.sleep(0.3)
        else:
            raise RuntimeError(f"Live MCP server for {interpreter} did not list tools")

        session_id = tests["session"](emulator, has_model)
        emulator.rpc("session/prompt", {"request": {
            "sessionId": session_id, "requestId": str(uuid.uuid4()), "mode": "queue",
            "content": [{"type": "text", "text": "Call the MCP tool whose name ends in stdio_fixture_echo, with no arguments. Report its exact result. Do not use other tools."}],
        }})
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            if any(event["type"] == "tool/result" and "MH_MCP_STDIO_OK" in json.dumps(event)
                   for event in tests["events"](emulator, session_id)):
                output["toolResultReturnedToSession"] = True
                return
            time.sleep(0.6)
        raise RuntimeError(f"No tool result returned from {interpreter}")
    finally:
        current = settings(emulator)
        latest = current["user"]
        if name in latest.get("servers", {}):
            remaining = dict(latest["servers"])
            remaining.pop(name)
            restored = {**latest, "servers": remaining}
            if "servers" not in original and not remaining:
                restored.pop("servers")
            set_settings(emulator, restored, current["revision"])
        output["fixtureRemoved"] = name not in settings(emulator)["user"].get("servers", {})
        emulator.app(f"rm -f {active} {active}.ready")
        emulator.hdc("shell", "rm", "-f", remote)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--port", type=int, default=19638)
    options = parser.parse_args()
    emulator = tests["Emulator"](options.target, options.port)
    forward = (f"tcp:{options.port}", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    outcome = {}
    try:
        emulator.ready("normal")
        with tests["model_key"](emulator) as has_model:
            for command, filename in (("node", "mcp-stdio.cjs"), ("python3", "mcp-stdio.py")):
                outcome[command] = {}
                verify(emulator, has_model, command, filename, outcome[command])
                print(command, outcome[command], flush=True)
    finally:
        emulator.hdc("fport", "rm", *forward)
        options.output.write_text(json.dumps(outcome, indent=2) + "\n")


if __name__ == "__main__":
    main()
