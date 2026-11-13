"""Exercise the AppGallery glob and grep tools through a real session and a local model fixture."""
import argparse
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import re
import threading
import uuid

recovery = importlib.import_module("emulator-recovery")
MODEL = "appgallery-search-fixture"
CREDENTIAL = "MOBILE_HARNESS_SEARCH_FIXTURE"
CALLS = (
    ("glob", {"pattern": "**/*.txt"}),
    ("grep", {"pattern": "needle-[0-9]+", "include": "*.txt"}),
    ("grep", {"pattern": "[", "include": "*.txt"}),
    ("glob", {"pattern": "**/*.txt", "path": "../.."}),
)


def void_rpc(emulator, method, args):
    try:
        emulator.rpc(method, args)
    except KeyError as error:
        if error.args != ("value",):
            raise


def model_handler(outcomes, done):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            tool_messages = [message["content"] for message in request["messages"] if message.get("role") == "tool"]
            if request.get("tools") and len(tool_messages) < len(CALLS):
                index = len(tool_messages)
                name, arguments = CALLS[index]
                if name not in {tool["function"]["name"] for tool in request["tools"]}:
                    self.send_error(400, "Search tool was not registered")
                    return
                delta = {"role": "assistant", "tool_calls": [{
                    "index": 0, "id": f"call_{index}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }]}
                finish = "tool_calls"
            else:
                delta = {"role": "assistant", "content": "Search fixture finished."}
                finish = "stop"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for part, reason in ((delta, None), ({}, finish)):
                chunk = {"id": "search-fixture", "object": "chat.completion.chunk", "created": 1,
                         "model": MODEL, "choices": [{"index": 0, "delta": part, "finish_reason": reason}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            if len(tool_messages) == len(CALLS):
                outcomes[:] = tool_messages
                done.set()
    return Handler


def test(emulator, port, model_port):
    if emulator.hdc("shell", "param get const.product.model") != "emulator":
        raise SystemExit("Expected a Phone emulator")
    outcomes = []
    done = threading.Event()
    forward = (f"tcp:{port}", "tcp:19592")
    reverse = (f"tcp:{model_port}", f"tcp:{model_port}")
    namespace = "llm-pi-ai"
    folder = "search-fixture-" + uuid.uuid4().hex[:10]
    relative = f"alpine/workspace-native/{folder}"
    with ExitStack() as cleanup:
        server = cleanup.enter_context(ThreadingHTTPServer(("127.0.0.1", model_port), model_handler(outcomes, done)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cleanup.callback(server.shutdown)
        for operation, ports in (("fport", forward), ("rport", reverse)):
            if "Forwardport result:OK" not in emulator.hdc(operation, *ports):
                raise RuntimeError(f"Could not establish the {operation} fixture")
            cleanup.callback(emulator.hdc, "fport", "rm", *ports)
        emulator.ready("normal")

        saved = next(row for row in emulator.rpc("settings/describe", {})["namespaces"]
                     if row["ns"] == namespace).get("user", {})
        provider = {
            "displayName": "Local Search Fixture", "apiKeyEnv": CREDENTIAL, "api": "openai-completions",
            "baseURL": f"http://127.0.0.1:{model_port}/v1",
            "models": [{"id": MODEL, "name": MODEL, "contextWindow": 65536, "maxTokens": 2048}],
        }
        emulator.rpc("settings/update", {
            "ns": namespace, "patch": {"providers": {**saved.get("providers", {}), MODEL: provider}},
        })
        cleanup.callback(emulator.rpc, "settings/replace", {"ns": namespace, "section": saved})
        void_rpc(emulator, "credentials/set", {"ref": CREDENTIAL, "value": "fixture-only"})
        cleanup.callback(void_rpc, emulator, "credentials/unset", {"ref": CREDENTIAL})
        emulator.app(
            f"mkdir -p {relative}/docs {relative}/.git && "
            f"printf 'needle-42\\n' > {relative}/docs/match.txt && "
            f"printf 'needle-666\\n' > {relative}/.git/hidden.txt"
        )
        cleanup.callback(emulator.app, f"rm -r {relative}")
        workspace = emulator.rpc("workspace/create", {
            "request": {"path": f"{recovery.WORKSPACE}/{folder}"},
        })["workspace"]
        workspace_id = workspace["workspaceId"]
        cleanup.callback(emulator.rpc, "workspace/delete", {"request": {"workspaceId": workspace_id}})
        session_id = emulator.rpc("session/create", {
            "request": {"workspaceId": workspace_id},
        })["sessionId"]
        emulator.rpc("session/selectModel", {
            "request": {"sessionId": session_id, "provider": MODEL, "model": MODEL},
        })
        emulator.rpc("session/prompt", {"request": {
            "sessionId": session_id, "requestId": str(uuid.uuid4()), "mode": "queue",
            "content": [{"type": "text", "text": "Run the workspace search fixture."}],
        }})
        if not done.wait(40):
            raise RuntimeError("Expected search calls did not complete")
        glob, grep, bad_pattern, outside = outcomes
        assert "docs/match.txt" in glob and "hidden.txt" not in glob, glob
        assert "Line 1: needle-42" in grep and "needle-666" not in grep, grep
        assert "unclosed character class" in bad_pattern, bad_pattern
        assert "Search path must be within the local workspace" in outside, outside
        print("AppGallery glob and grep passed, including invalid regex and workspace boundary.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="loopback Phone emulator HDC target")
    parser.add_argument("--bundle", default="org.mobileharness.dshmh")
    parser.add_argument("--port", type=int, default=19633)
    parser.add_argument("--model-port", type=int, default=19634)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", args.bundle):
        parser.error("invalid application bundle name")
    recovery.BUNDLE = args.bundle
    test(recovery.Emulator(args.target, args.port), args.port, args.model_port)
