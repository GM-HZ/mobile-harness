#!/usr/bin/env python3
"""Check a local OpenAI Chat Completions tool loop with in-memory fixtures."""

import argparse
import http.client
import ipaddress
import json
import math
import secrets
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


DONE = "LOCAL_LLM_AGENT_DONE"
TITLE = "probe-notebook"
MAX_STREAM_BYTES = 4 * 1024 * 1024
SYSTEM = (
    "You are testing a read-only note assistant. To find a note by title, call search_notes with "
    "the exact title as the query, then call read_note with the note_id returned by search_notes. "
    "After read_note, reply with only the exact value of its marker field. "
    "Follow direct formatting requests without using tools."
)


class ProbeError(Exception):
    pass


def tool_schema(name, description, parameter):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {parameter: {"type": "string"}},
                "required": [parameter],
                "additionalProperties": False,
            },
        },
    }


TOOLS = [
    tool_schema("search_notes", "Find a note by its exact title and return its note_id.", "query"),
    tool_schema("read_note", "Read a note by the note_id returned by search_notes.", "note_id"),
]


def parse_base_url(value):
    try:
        url = urlsplit(value)
        local = ipaddress.ip_address(url.hostname).is_loopback
        port = 80 if url.port is None else url.port
    except ValueError:
        raise argparse.ArgumentTypeError("use a numeric loopback URL such as http://127.0.0.1:8080/v1") from None
    if (url.scheme != "http" or not local or not port or url.username is not None
            or url.password is not None or url.query or url.fragment):
        raise argparse.ArgumentTypeError("use an HTTP loopback URL without credentials, query or fragment")
    return url.hostname, port, url.path.rstrip("/") + "/chat/completions"


def sse_events(response):
    event_lines = []
    bytes_read = 0
    while line := response.readline(MAX_STREAM_BYTES + 1):
        bytes_read += len(line)
        if bytes_read > MAX_STREAM_BYTES:
            raise ProbeError("SSE response exceeded 4 MiB")
        line = line.rstrip(b"\r\n")
        if line.startswith(b"data:"):
            event_lines.append(line[5:].removeprefix(b" "))
        elif not line and event_lines:
            yield b"\n".join(event_lines)
            event_lines.clear()
    if event_lines:
        yield b"\n".join(event_lines)


def append_delta(calls, fragment):
    index = fragment.get("index")
    if type(index) is not int or index != 0:
        raise ProbeError("expected one tool call with index 0")
    if fragment.get("type", "function") != "function":
        raise ProbeError("received a non-function tool call")
    if not calls:
        calls.append({"id": "", "name": "", "arguments": ""})
    current = calls[0]
    current["id"] += fragment.get("id") or ""
    function = fragment.get("function", {})
    current["name"] += function.get("name") or ""
    current["arguments"] += function.get("arguments") or ""


def request_turn(endpoint, model, messages, timeout, report):
    host, port, path = endpoint
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    payload = {"model": model, "messages": messages, "tools": TOOLS, "stream": True, "tool_choice": "auto"}
    started = time.monotonic()
    text_parts = []
    reasoning_parts = []
    calls = []
    try:
        connection.request(
            "POST", path, body=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        with connection.getresponse() as response:
            report["httpStatus"] = response.status
            if response.status != 200:
                raise ProbeError(f"server returned HTTP {response.status}")
            if response.headers.get_content_type() != "text/event-stream":
                raise ProbeError("server did not return text/event-stream")
            for event in sse_events(response):
                if event == b"[DONE]":
                    report["sseDone"] = True
                    break
                chunk = json.loads(event)
                if chunk.get("error"):
                    raise ProbeError("server returned an SSE error event")
                if isinstance(chunk.get("model"), str):
                    report["reportedModel"] = chunk["model"]
                    if chunk["model"] != model:
                        raise ProbeError("server reported a different model ID than requested")
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                if len(choices) != 1 or choices[0].get("index", 0) != 0:
                    raise ProbeError("expected one completion choice with index 0")
                choice = choices[0]
                delta = choice.get("delta") or {}
                if delta.get("content") or delta.get("reasoning_content") or delta.get("tool_calls"):
                    report.setdefault("firstDeltaMs", round((time.monotonic() - started) * 1000))
                if delta.get("content") is not None:
                    text_parts.append(delta["content"])
                if delta.get("reasoning_content") is not None:
                    reasoning_parts.append(delta["reasoning_content"])
                for fragment in delta.get("tool_calls") or []:
                    append_delta(calls, fragment)
                if choice.get("finish_reason") is not None:
                    report["finishReason"] = choice["finish_reason"]
            if not report.get("sseDone"):
                raise ProbeError("stream ended before its [DONE] event")
            if "reportedModel" not in report:
                raise ProbeError("server did not identify the response model")
            return "".join(text_parts), "".join(reasoning_parts), calls
    except (AttributeError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
        raise ProbeError("malformed SSE completion chunk") from None
    finally:
        report["toolCallCount"] = len(calls)
        if calls:
            report["toolNames"] = [call["name"] for call in calls]
        report["durationMs"] = round((time.monotonic() - started) * 1000)
        connection.close()


def verify_call(name, arguments, calls, report):
    if report.get("finishReason") != "tool_calls" or len(calls) != 1:
        raise ProbeError(f"expected one {name} call and tool_calls finish reason")
    call = calls[0]
    if call["name"] != name or not call["id"].strip():
        raise ProbeError(f"expected {name} and a non-empty tool call ID")
    try:
        parsed = json.loads(call["arguments"], object_pairs_hook=list)
    except ValueError:
        raise ProbeError(f"{name} arguments were not valid JSON") from None
    if parsed != list(arguments.items()):
        raise ProbeError(f"{name} arguments did not match the fixture")
    report["toolCalls"] = [{"id": call["id"], "name": name, "arguments": arguments}]
    return {
        "id": call["id"], "type": "function",
        "function": {"name": name, "arguments": call["arguments"]},
    }


def verify_text(expected, content, calls, report):
    report["resultText"] = content[:200]
    report["expectedText"] = expected
    if report.get("finishReason") != "stop" or calls or content != expected:
        raise ProbeError("expected exactly the fixture text, no tool call and a stop finish reason")


def text_turn(options, evidence, stage, messages, expected):
    report = {"stage": stage, "ok": False}
    evidence["turns"].append(report)
    content, _, calls = request_turn(options.base_url, options.model, messages, options.timeout, report)
    verify_text(expected, content, calls, report)
    report["ok"] = True


def run_control(options, evidence):
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "请只回复 CONTROL_OK。这条消息无需调用工具。"},
    ]
    text_turn(options, evidence, "no_tool", messages, "CONTROL_OK")


def run_tool_loop(options, evidence):
    note_id = "note-" + secrets.token_hex(4)
    marker = "MH-" + secrets.token_hex(6)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            f"找到标题为 {TITLE} 的笔记。请只返回笔记中 marker 字段的原始值，不加引号、反引号或其他文字。"
        )},
    ]
    fixtures = [
        ("search_notes", {"query": TITLE}, {"note_id": note_id, "title": TITLE}),
        ("read_note", {"note_id": note_id}, {"marker": marker}),
    ]
    previous_call_id = None
    for name, arguments, result in fixtures:
        report = {"stage": name, "ok": False}
        evidence["turns"].append(report)
        content, reasoning, calls = request_turn(options.base_url, options.model, messages, options.timeout, report)
        call = verify_call(name, arguments, calls, report)
        if call["id"] == previous_call_id:
            raise ProbeError("tool call ID was reused across the two calls")
        previous_call_id = call["id"]
        assistant = {"role": "assistant", "content": content or None, "tool_calls": [call]}
        if reasoning:
            assistant["reasoning_content"] = reasoning
        messages += [
            assistant,
            {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)},
        ]
        report["ok"] = True
    text_turn(options, evidence, "marker", messages, marker)


def expire(_signum, _frame):
    raise TimeoutError("probe deadline expired")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1", type=parse_base_url)
    parser.add_argument("--model", required=True, help="model ID served by the local backend")
    parser.add_argument("--backend", default="llama.cpp", help="backend and optional build identifier for evidence")
    parser.add_argument("--timeout", default=180, type=float, help="total probe timeout in seconds")
    parser.add_argument("--output", type=Path, help="also copy JSON evidence to this file")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a positive finite number")

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    started = time.monotonic()
    evidence = {
        "schema": 1, "ok": False, "status": "fail", "done": None, "commit": commit,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "endpoint": {"host": args.base_url[0], "port": args.base_url[1], "path": args.base_url[2]},
        "backend": args.backend, "model": args.model, "timeoutSeconds": args.timeout, "turns": [],
    }
    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, args.timeout)
    try:
        for scenario in (run_control, run_tool_loop):
            try:
                scenario(args, evidence)
            except (OSError, http.client.HTTPException, ProbeError) as error:
                stage = evidence["turns"][-1]["stage"] if evidence["turns"] else "start"
                evidence.setdefault("failures", []).append({
                    "stage": stage, "type": type(error).__name__, "message": str(error),
                })
                if isinstance(error, OSError):
                    break
        if "failures" not in evidence:
            evidence.update(ok=True, status="pass", done=DONE)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        evidence["durationMs"] = round((time.monotonic() - started) * 1000)
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
