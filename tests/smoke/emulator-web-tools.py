"""Actual DSH web tools over controlled HTTP/1, URL policy, cancellation and search."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import threading
import time
import uuid

office = runpy.run_path(str(Path(__file__).with_name("emulator-office.py")))
support = office["support"]
toolkit = office["toolkit"]


class Fixture(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *_): pass
    def do_GET(self):
        self.server.paths.append(self.path)
        if self.path == "/slow":
            self.server.pending.set()
            self.server.release.wait(15)
            self.close_connection = True
            return
        headers = {}
        if self.path == "/redirect":
            status, body = 302, b""; headers["Location"] = "/html"
        elif self.path == "/cross":
            status, body = 302, b""
            headers["Location"] = f"http://localhost:{self.server.device_port}/must-not-be-fetched"
        elif self.path == "/large":
            self.send_response(200); self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "6000000"); self.end_headers()
            self.close_connection = True
            return
        elif self.path == "/error":
            status, body = 418, self.server.marker.encode()
        elif self.path == "/chunked":
            self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
            for chunk in [self.server.marker[:12].encode(), self.server.marker[12:].encode(), "中文".encode()]:
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
            return
        else:
            status = 200
            body = ("<h1>" + self.server.marker + "</h1><script>HIDDEN_SCRIPT_MUST_NOT_LEAK</script>").encode()
            headers["Content-Type"] = "text/html; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        if "Content-Type" not in headers: headers["Content-Type"] = "text/plain"
        for key, val in headers.items(): self.send_header(key, val)
        self.end_headers(); self.wfile.write(body)


def run(emulator, output, search=False, require_messages_search=False):
    evidence = {}
    sid = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    server.daemon_threads = True
    # Keep the token free of Markdown punctuation: HTML headings are escaped by Turndown.
    server.marker = "HARMONYWEB" + uuid.uuid4().hex.upper()
    server.paths = []; server.pending = threading.Event(); server.release = threading.Event()
    server.device_port = 19739
    reverse = (f"tcp:{server.device_port}", f"tcp:{server.server_port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    forwarded = False
    try:
        evidence["readyMs"] = emulator.ready("normal")
        assert "Forwardport result:OK" in emulator.hdc("rport", *reverse)
        forwarded = True
        base = f"http://127.0.0.1:{server.device_port}"
        with support["model_key"](emulator):
            sid = support["session"](emulator, True)
            evidence["sessionId"] = sid
            for route, status in [("/html", 200), ("/chunked", 200), ("/redirect", 200), ("/error", 418)]:
                result, _ = office["invoke"](emulator, sid, "web_fetch", {"url": base + route})
                text = toolkit["texts"]([result])
                assert server.marker in text and f"HTTP {status}" in text, text
                assert "HIDDEN_SCRIPT_MUST_NOT_LEAK" not in text, text
                evidence[route[1:]] = {"status": status, "actualMarker": server.marker}
            for route, fragments in [("/cross", ["cross-origin", "redirect"]), ("/large", ["maximum", "bytes", "large"])]:
                result, _ = office["invoke"](emulator, sid, "web_fetch", {"url": base + route}, expect_error=True)
                assert any(fragment in toolkit["texts"]([result]).lower() for fragment in fragments)
                evidence[route[1:] + "Rejected"] = True
            assert "/must-not-be-fetched" not in server.paths, server.paths
            evidence["crossOriginDestinationNotContacted"] = True
            before = len(server.paths)
            for url, fragment in [("http://user:password@127.0.0.1:" + str(server.device_port) + "/credential", "credentials"), ("file:///mh-nonexistent-fixture.txt", "scheme")]:
                result, _ = office["invoke"](emulator, sid, "web_fetch", {"url": url}, expect_error=True)
                assert fragment in toolkit["texts"]([result]).lower(), result
            assert len(server.paths) == before
            evidence["invalidUrlRefusedBeforeNetwork"] = True

            old_turns = sum(r["type"] == "turn/end" for r in support["events"](emulator, sid))
            emulator.rpc("session/prompt", {"request": {
                "sessionId": sid, "requestId": str(uuid.uuid4()), "mode": "queue",
                "content": [{"type": "text", "text": "Call web_fetch once with exactly " + json.dumps({"url": base + "/slow"})
                             + ". Controlled cancellation fixture: do not retry or call other tools."}],
            }})
            assert server.pending.wait(20), "Actual HTTP request did not arrive before cancellation"
            started = time.monotonic()
            assert emulator.rpc("session/cancel", {"request": {"sessionId": sid}})["accepted"]
            deadline = started + 8
            while time.monotonic() < deadline:
                ends = [r for r in support["events"](emulator, sid) if r["type"] == "turn/end"]
                if len(ends) > old_turns:
                    assert ends[old_turns]["data"]["reason"]["kind"] == "aborted"
                    break
                time.sleep(.05)
            else: raise AssertionError("The real web tool did not abort")
            evidence["actualHttpCancelledMs"] = round((time.monotonic() - started) * 1000)
            server.release.set()
            result, _ = office["invoke"](emulator, sid, "web_fetch", {"url": base + "/html"}, preamble=(
                "The earlier request is cancelled and finished. This is a NEW fetch request. Actually execute it now; do not summarize the old result. "))
            assert server.marker in toolkit["texts"]([result])
            evidence["sameSessionAfterCancellation"] = True

            result, _ = office["invoke"](emulator, sid, "web_fetch", {"url": "https://example.com/"})
            assert "Example Domain" in toolkit["texts"]([result])
            evidence["publicHttpsFetch"] = True
            if search:
                previous_events = len(support["events"](emulator, sid))
                result, _ = office["invoke"](emulator, sid, "web_search", {"queries": ["Alpine Linux official apk package manager documentation"]})
                assert "http" in toolkit["texts"]([result]), result
                evidence["deepseekSearch"] = True
                if require_messages_search:
                    new_events = support["events"](emulator, sid)[previous_events:]
                    requests = [row["data"] for row in new_events if row["type"] == "web/deepseek-search-llm-request"]
                    assert len(requests) == 1, [row["type"] for row in new_events]
                    request = requests[0]
                    assert request["endpoint"] == "https://api.deepseek.com/anthropic/v1/messages", request["endpoint"]
                    assert request["body"]["tools"][0]["type"] == "web_search_20250305"
                    evidence["deepseekMessagesSearch"] = {
                        "endpoint": request["endpoint"],
                        "apiVersion": request["apiVersion"],
                        "model": request["body"]["model"],
                    }
        evidence["temporaryModelCredentialRemoved"] = True
        lines = emulator.app("grep http-parser-portable alpine/tmp/dsh-native-timeline.log || true")
        evidence["parserTrace"] = [json.loads(row) for row in lines.splitlines()]
    except BaseException:
        if sid:
            output.with_suffix(".events.json").write_text(json.dumps(support["events"](emulator, sid), indent=2) + "\n")
        raise
    finally:
        try:
            server.release.set()
            if sid: emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
            if forwarded: emulator.hdc("fport", "rm", *reverse)
            server.shutdown(); server.server_close()
        finally:
            evidence["observedPaths"] = server.paths
            output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target"); parser.add_argument("output", type=Path)
    parser.add_argument("--search", action="store_true", help="Also exercise the selected DeepSeek search provider")
    parser.add_argument("--require-messages-search", action="store_true", help="Require the official RC.5 Messages search event")
    options = parser.parse_args()
    if options.require_messages_search and not options.search:
        parser.error("--require-messages-search requires --search")
    if not os.environ.get("MH_TEST_DEEPSEEK_API_KEY"): parser.error("MH_TEST_DEEPSEEK_API_KEY is required")
    emulator = support["Emulator"](options.target, 19643)
    forward = ("tcp:19643", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    try: run(emulator, options.output, options.search, options.require_messages_search)
    finally: emulator.hdc("fport", "rm", *forward)
