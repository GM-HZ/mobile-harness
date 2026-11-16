"""Exercise one durable schedule and a controlled Streamable HTTP MCP server."""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import threading
import time
import uuid

Emulator = runpy.run_path(str(Path(__file__).with_name("emulator-recovery.py")))["Emulator"]
WORKSPACE = "/data/storage/el2/base/haps/entry/files/alpine/workspace-native"


class McpFixture(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, payload=b""):
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        if payload:
            self.send_header("Content-Type", "application/json")
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def do_GET(self):
        self.respond(405)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = request["method"]
        self.server.methods.append(method)
        if "id" not in request:
            self.respond(202)
            return
        if method == "initialize":
            result = {
                "protocolVersion": request["params"]["protocolVersion"],
                "serverInfo": {"name": "mh-probe", "version": "1.0"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": [{
                "name": "fixture_echo", "description": "Returns a fixed fixture token",
                "inputSchema": {"type": "object", "properties": {}},
            }]}
        elif method == "tools/call" and request["params"]["name"] == "fixture_echo":
            result = {"content": [{"type": "text", "text": "MH_MCP_HTTP_OK"}]}
        else:
            self.respond(400)
            return
        self.respond(200, json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode())


@contextmanager
def model_key(emulator):
    key = os.environ.get("MH_TEST_DEEPSEEK_API_KEY")
    if key is None:
        yield False
        return
    refs = {"refs": ["DEEPSEEK_API_KEY"]}
    credentials = emulator.rpc("credentials/describe", refs)
    if credentials["DEEPSEEK_API_KEY"]["configured"]:
        raise RuntimeError("The fixture requires the emulator's test key slot to be empty")
    emulator.rpc("credentials/set", {"ref": "DEEPSEEK_API_KEY", "value": key})
    try:
        yield True
    finally:
        emulator.rpc("credentials/unset", {"ref": "DEEPSEEK_API_KEY"})
        assert not emulator.rpc("credentials/describe", refs)["DEEPSEEK_API_KEY"]["configured"]


def session(emulator, has_model):
    workspace = emulator.rpc("workspace/create", {"request": {"path": WORKSPACE}})["workspace"]
    session_id = emulator.rpc("session/create", {"request": {"workspaceId": workspace["workspaceId"]}})["sessionId"]
    if has_model:
        emulator.rpc("session/selectModel", {"request": {
            "sessionId": session_id, "provider": "deepseek-official", "model": "deepseek-flash", "reasoningEffort": "off",
        }})
    return session_id


def events(emulator, session_id):
    response = emulator.rpc("session/events", {"request": {"address": {"kind": "session", "sessionId": session_id}}})
    return [row["event"] for row in response["records"] if row.get("event")]


def verify_schedule(emulator, has_model, evidence):
    session_id = session(emulator, has_model)
    marker = "MH_SCHEDULE_" + uuid.uuid4().hex[:12].upper()
    schedule = emulator.rpc("schedule/create", {"request": {
        "title": "Mobile Harness scheduler acceptance",
        "prompt": f"Reply with the exact text {marker} and take no other action.",
        "timing": {"kind": "after", "after_seconds": 24},
        "target": {"kind": "session", "sessionId": session_id},
    }})
    schedule_id = schedule["id"]
    try:
        emulator.stop()
        emulator.start()
        evidence["restartReadyMs"] = emulator.ready("normal")
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline:
            task = emulator.rpc("schedule/view", {"request": {"id": schedule_id}})
            assert task["id"] == schedule_id
            matching = [event["type"] for event in events(emulator, session_id) if marker in json.dumps(event)]
            evidence.update(persistedAcrossHostRestart=True, receiptPresent=bool(task.get("lastDelivery")),
                            eventsWithMarker=matching, modelReply="assistant/message" in matching)
            if evidence["receiptPresent"] and "user/message" in matching and (not has_model or evidence["modelReply"]):
                return
            time.sleep(0.8)
        raise RuntimeError(f"Schedule delivery did not complete: {evidence}")
    finally:
        result = emulator.rpc("schedule/edit", {"request": {"id": schedule_id, "action": "delete"}})
        evidence["fixtureRemoved"] = result.get("deleted") is True


def mcp_settings(emulator):
    return next(row for row in emulator.rpc("settings/describe", {})["namespaces"] if row["ns"] == "mcp-manager")


def set_mcp_settings(emulator, section, revision):
    return emulator.rpc("settings/replace", {"ns": "mcp-manager", "section": section, "expectedRevision": revision})


def verify_mcp(emulator, has_model, device_port, evidence):
    with ThreadingHTTPServer(("127.0.0.1", 0), McpFixture) as server:
        server.methods = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        reverse = (f"tcp:{device_port}", f"tcp:{server.server_port}")
        try:
            assert "Forwardport result:OK" in emulator.hdc("rport", *reverse)
            settings = mcp_settings(emulator)
            original = settings["user"]
            configured = dict(original.get("servers", {}))
            name = "mh-regression-http-" + uuid.uuid4().hex[:6]
            configured[name] = {
                "transport": "streamable-http", "enabled": False,
                "url": f"http://127.0.0.1:{device_port}/mcp", "startupTimeoutMs": 7000,
            }
            try:
                updated = set_mcp_settings(emulator, {**original, "servers": configured}, settings["revision"])
                probe = emulator.rpc("mcpManager/probe", {"name": name})
                evidence["probe"] = probe
                assert probe["ok"] and probe["closeConfirmed"] and probe["toolNames"] == ["fixture_echo"]
                if has_model:
                    configured[name]["enabled"] = True
                    set_mcp_settings(emulator, {**original, "servers": configured}, updated["revision"])
                    session_id = session(emulator, has_model)
                    request = {
                        "sessionId": session_id, "requestId": str(uuid.uuid4()), "mode": "queue",
                        "content": [{"type": "text", "text": "Call the MCP tool whose name ends in fixture_echo, with no arguments. Report its result. Do not use other tools."}],
                    }
                    emulator.rpc("session/prompt", {"request": request})
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline:
                        if any(event["type"] == "tool/result" and "MH_MCP_HTTP_OK" in json.dumps(event)
                               for event in events(emulator, session_id)):
                            evidence["toolResultReturnedToSession"] = True
                            break
                        time.sleep(0.6)
                    assert evidence.get("toolResultReturnedToSession"), evidence
            finally:
                current = mcp_settings(emulator)
                latest = current["user"]
                restored = {**latest, "servers": {key: value for key, value in latest.get("servers", {}).items() if key != name}}
                if "servers" not in original and not restored["servers"]:
                    restored.pop("servers")
                set_mcp_settings(emulator, restored, current["revision"])
                evidence["fixtureRemoved"] = name not in mcp_settings(emulator)["user"].get("servers", {})
        finally:
            emulator.hdc("fport", "rm", *reverse)
            server.shutdown()
            evidence["observedMethods"] = server.methods


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="loopback Phone emulator HDC target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--host-port", type=int, default=19638)
    parser.add_argument("--guest-mcp-port", type=int, default=19737)
    options = parser.parse_args()
    emulator = Emulator(options.target, options.host_port)
    forward = (f"tcp:{options.host_port}", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    outcome = {"schedule": {}, "mcpHttp": {}}
    try:
        emulator.ready("normal")
        with model_key(emulator) as has_model:
            verify_schedule(emulator, has_model, outcome["schedule"])
            verify_mcp(emulator, has_model, options.guest_mcp_port, outcome["mcpHttp"])
    finally:
        emulator.hdc("fport", "rm", *forward)
        options.output.write_text(json.dumps(outcome, indent=2) + "\n")
    print(json.dumps(outcome))


if __name__ == "__main__":
    main()
