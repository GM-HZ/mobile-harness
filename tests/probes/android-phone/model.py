"""Loopback-only Messages model for the Android Phone Use fixture."""

import argparse
import base64
import binascii
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import re
from time import sleep


FIXTURE = "org.mobileharness.phonefixture"
PREFIX = "mcp__phone__"
PROMPT_MARKER = "MH_PHONE_FIXTURE"
FORM_MARKER = "MH_PHONE_FORM_FIXTURE"
COORD_MARKER = "MH_PHONE_COORD_FIXTURE"
SWIPE_MARKER = "MH_PHONE_SWIPE_FIXTURE"
SECURE_MARKER = "MH_PHONE_SECURE_FIXTURE"
COLD_READ_MARKER = "MH_PHONE_COLD_READ_FIXTURE"
BACKGROUND_MARKER = "MH_PHONE_BACKGROUND_FIXTURE"
HANDOFF_MARKER = "MH_PHONE_HANDOFF_FIXTURE"
SHELL_MARKER = "MH_SHELL_FIXTURE"
SSH_MARKER = re.compile(r"MH_SSH_(RESUME|APPROVAL|REPORT)_FIXTURE ([0-9a-f]{12})")
REPORT_MARKER = re.compile(r"MH_PHONE_REPORT_FIXTURE ([0-9a-f]{12})")
MARKERS = {
    PROMPT_MARKER, FORM_MARKER, COORD_MARKER, SWIPE_MARKER,
    SECURE_MARKER, COLD_READ_MARKER, BACKGROUND_MARKER, HANDOFF_MARKER, SHELL_MARKER,
}
FORM_TEXT = "Mobile Harness 测试"
UPLOADED_IMAGES = {}


def decide(request):
    available = {tool["name"] for tool in request.get("tools", [])}
    mode = None
    ssh_fixture = None
    report_run = None
    calls = {}
    results = {}
    latest = None
    for message in request.get("messages", []):
        content = message["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for block in content:
            prompt = block["text"].strip() if message["role"] == "user" and block["type"] == "text" else ""
            ssh_match = SSH_MARKER.fullmatch(prompt)
            report_match = REPORT_MARKER.fullmatch(prompt)
            if prompt in MARKERS or ssh_match or report_match:
                mode = prompt
                ssh_fixture = ssh_match.groups() if ssh_match else None
                report_run = report_match[1] if report_match else None
                calls.clear()
                results.clear()
                latest = None
            elif block["type"] == "tool_use":
                calls[block["id"]] = block["name"]
            elif block["type"] == "tool_result" and block["tool_use_id"] in calls:
                latest = block
                results[block["tool_use_id"]] = block
    if mode is None:
        return "text", "Mobile Harness fixture session"
    if ssh_fixture:
        kind, run = ssh_fixture
        if kind == "REPORT":
            if not {"write", "read"} <= available:
                return "text", "MH_SSH_REPORT_TOOLS_MISSING"
            return ssh_report_step(run, latest, calls)
        if "bash" not in available:
            return "text", "MH_SSH_TOOL_MISSING"
        if kind == "APPROVAL":
            return ssh_approval_step(run, latest)
        return ssh_resume_step(run, latest, len(calls))
    if mode == SHELL_MARKER:
        if "bash" not in available:
            return "text", "MH_SHELL_TOOL_MISSING"
        command = {
            "command": "printf 'MH_HARNESS_SHELL\\n'; uname -s",
            "description": "Check which host runs the test command",
        }
        if latest is None:
            return "bash", command
        output = tool_text(latest)
        if latest.get("is_error") and "no sandbox backend is usable" in output and len(calls) == 1:
            return "bash", {
                **command,
                "sandbox_permissions": "danger-full-access",
                "justification": "Run only the fixture command after the sandbox backend was unavailable.",
            }
        if not latest.get("is_error") and re.search(r"MH_HARNESS_SHELL\s+(Linux|Darwin)", output):
            print("Confirmed shell command from the DSH tool result", flush=True)
            return "text", "MH_SHELL_VERIFIED"
        return "text", "MH_SHELL_FAILED"
    required = {PREFIX + name for name in ("open", "screen", "tap")}
    if mode == FORM_MARKER:
        required |= {PREFIX + name for name in ("type", "scroll")}
    if mode == COORD_MARKER:
        required.add(PREFIX + "tap_xy")
    if mode == SWIPE_MARKER:
        required.add(PREFIX + "swipe_xy")
    if mode == HANDOFF_MARKER:
        required.add(PREFIX + "handoff")
    if report_run:
        required.update(("write", "read"))
    if not required <= available:
        return "text", "MH_PHONE_TOOLS_MISSING"
    background = {"background": True} if mode == BACKGROUND_MARKER else {}
    if latest is None:
        return PREFIX + "open", {"app": FIXTURE, **background}
    name = calls.get(latest["tool_use_id"])
    screen = tool_text(latest)
    report_taps = [result for call_id, result in results.items() if calls[call_id] == PREFIX + "tap"] if report_run else []
    retry_report_tap = (
        len(report_taps) == 1 and report_taps[0].get("is_error")
        and "已经过期" in tool_text(report_taps[0]) and "没有执行" in tool_text(report_taps[0])
    )
    retry_sample_read = (
        (mode in (PROMPT_MARKER, BACKGROUND_MARKER, HANDOFF_MARKER) or report_run) and name == PREFIX + "screen"
        and PREFIX + "tap" not in calls.values()
        and list(calls.values()).count(PREFIX + "screen") < 5
    )
    if mode == COORD_MARKER:
        return coordinate_step(name, latest, screen, calls, results)
    if mode == SWIPE_MARKER:
        return swipe_step(name, latest, screen, calls, results)
    if mode == SECURE_MARKER:
        return secure_step(name, latest, screen, calls)
    if mode == COLD_READ_MARKER:
        if name == PREFIX + "open" and not latest.get("is_error"):
            return PREFIX + "screen", {"image": True}
        if name == PREFIX + "screen" and not latest.get("is_error"):
            opened = next(result for call_id, result in results.items() if calls[call_id] == PREFIX + "open")
            if "Toggle sample" in tool_text(opened) and "Toggle sample" in screen and screenshot(latest):
                print("DSH returned the fixture tree on open and the first screenshot", flush=True)
                return "text", "MH_PHONE_COLD_READ_VERIFIED"
        print("DSH did not return both the fixture tree and the first screenshot", flush=True)
        return "text", "MH_PHONE_COLD_READ_FAILED"
    if latest.get("is_error"):
        if name == PREFIX + "tap" and retry_report_tap:
            return PREFIX + "screen", {}
        if background and retry_sample_read and "未能读取后台屏控件树" in screen:
            sleep(1)
            return PREFIX + "screen", background
        if background and name == PREFIX + "open":
            probe = re.search(r"probe-v1;stage=\w+;type=\w+;elapsedMs=\d+", screen)
            if probe:
                print(f"DSH refused the background launch: {probe[0]}", flush=True)
                return "text", "MH_PHONE_BACKGROUND_UNAVAILABLE"
        return "text", "MH_PHONE_FAILED_TOOL"
    if mode == FORM_MARKER:
        return form_step(name, latest, screen, calls)
    if report_run:
        report_path = f"mh-phone-report-{report_run}.txt"
        report_lines = ("Mobile Harness 验证", f"report_id={report_run}", "fixture_state=SAMPLE_ON")
        if name == "write":
            return "read", {"file_path": report_path}
        if name == "read":
            if all(line in screen for line in report_lines):
                print(f"DSH read back the workspace report {report_path}", flush=True)
                return "text", f"MH_PHONE_REPORT_VERIFIED {report_run}"
            return "text", "MH_PHONE_REPORT_READ_FAILED"
    if name == PREFIX + "handoff":
        if "用户点了「继续」" not in screen:
            return "text", "MH_PHONE_HANDOFF_FAILED"
        print("DSH confirmed the user continued after handoff", flush=True)
        return PREFIX + "screen", {}
    if name in (PREFIX + "open", PREFIX + "tap"):
        return PREFIX + "screen", background
    if name == PREFIX + "screen":
        pattern = r"屏幕 (b\d+) · 后台屏 · Mobile Harness Phone Fixture" if background else r"屏幕 (s\d+)"
        frame = re.search(pattern, screen)
        if frame and "SAMPLE_ON" in screen and PREFIX + "tap" in calls.values():
            if background:
                print("Confirmed SAMPLE_ON from the DSH background display", flush=True)
                return "text", "MH_PHONE_BACKGROUND_VERIFIED"
            if mode == HANDOFF_MARKER:
                return "text", "MH_PHONE_HANDOFF_VERIFIED"
            if report_run:
                if not report_taps or report_taps[-1].get("is_error"):
                    return "text", "MH_PHONE_REPORT_TAP_NOT_VERIFIED"
                return "write", {"file_path": report_path, "content": "\n".join(report_lines) + "\n"}
            print("Confirmed SAMPLE_ON from the DSH tool result", flush=True)
            return "text", "MH_PHONE_VERIFIED_SAMPLE_ON"
        button = re.search(r"\[(\d+)\][^\n]*Toggle sample", screen, re.IGNORECASE)
        if frame and button and "SAMPLE_OFF" in screen and (PREFIX + "tap" not in calls.values() or retry_report_tap):
            if mode == HANDOFF_MARKER and PREFIX + "handoff" not in calls.values():
                return PREFIX + "handoff", {"reason": "Verify the Mobile Harness test handoff, then choose Continue."}
            return PREFIX + "tap", {"screen": frame[1], "id": int(button[1])}
        if retry_sample_read:
            sleep(1)
            return PREFIX + "screen", background
    return "text", "MH_PHONE_FAILED_READBACK"


def ssh_approval_step(run, latest):
    result = f"MH_SSH_APPROVAL_VERIFIED {run}"
    if latest is None:
        return "bash", {
            "command": rf"printf 'APPROVED\n' >> ./mh-ssh-approved-{run} && printf '{result}\n'",
            "description": "Write one test marker after approval from the Android client",
            "sandbox_permissions": "danger-full-access",
            "justification": "Allow this isolated SSH fixture to write its single approval marker.",
        }
    if not latest.get("is_error") and result in tool_text(latest):
        return "text", result
    return "text", f"MH_SSH_APPROVAL_FAILED {run}"


def ssh_report_step(run, latest, calls):
    report_path = f"mh-ssh-report-{run}.txt"
    lines = ("Mobile Harness 远端报告", f"report_id={run}", "workspace=ssh-fixture")
    if latest is None:
        return "write", {"file_path": report_path, "content": "\n".join(lines) + "\n"}
    if latest.get("is_error"):
        return "text", "MH_SSH_REPORT_TOOL_FAILED"
    if calls[latest["tool_use_id"]] == "write":
        return "read", {"file_path": report_path}
    if all(line in tool_text(latest) for line in lines):
        print(f"DSH read back the SSH workspace report {report_path}", flush=True)
        return "text", f"MH_SSH_REPORT_VERIFIED {run}"
    return "text", "MH_SSH_REPORT_READ_FAILED"


def ssh_resume_step(run, latest, call_count):
    # This refusal happens before the command starts, so the retry cannot duplicate START.
    retry = (
        latest is not None and call_count == 1 and latest.get("is_error")
        and "no sandbox backend is usable" in tool_text(latest)
    )
    if latest is None or retry:
        command = rf"""set -eu
run=./mh-ssh-resume-{run}
mkdir -p "$run"
printf 'START\n' >> "$run/events"
attempts=0
while [ ! -f "$run/release" ]; do
  [ "$attempts" -lt 90 ] || exit 1
  attempts=$((attempts + 1))
  sleep 1
done
printf 'FINISH\n' >> "$run/events"
printf 'MH_SSH_RESUME_RESULT {run}\n'
"""
        arguments = {
            "command": command,
            "description": "Hold a test command while the Android SSH tunnel reconnects",
            "timeoutMs": 100_000,
        }
        if retry:
            arguments.update(
                sandbox_permissions="danger-full-access",
                justification="Allow only this isolated SSH fixture command after its sandbox was unavailable.",
            )
        return "bash", arguments
    if not latest.get("is_error") and f"MH_SSH_RESUME_RESULT {run}" in tool_text(latest):
        print(f"Confirmed the remote command result for {run}", flush=True)
        return "text", f"MH_SSH_RESUME_VERIFIED {run}"
    return "text", "MH_SSH_RESUME_FAILED"


def form_step(name, latest, screen, calls):
    if name == PREFIX + "open":
        return PREFIX + "screen", {}
    tools = list(calls.values())
    frame = re.search(r"屏幕 (s\d+) · Mobile Harness Phone Fixture", screen)
    if not frame:
        if name == PREFIX + "screen" and PREFIX + "type" not in tools and tools.count(name) < 4:
            sleep(0.6)
            return PREFIX + "screen", {}
        return "text", "MH_FORM_WRONG_SCREEN"

    if name == PREFIX + "screen" and PREFIX + "type" not in tools:
        if "截图上的数字" not in screen and tools.count(name) < 5:
            return PREFIX + "screen", {"image": True}
        if not screenshot(latest):
            return "text", "MH_FORM_IMAGE_MISSING"
        note = re.search(r"\[(\d+)\][^\n]*Fixture note", screen)
        if note and "Save fixture note" not in screen:
            return PREFIX + "type", {"screen": frame[1], "id": int(note[1]), "text": FORM_TEXT}
    elif name == PREFIX + "type":
        if "回读一致" in screen and FORM_TEXT in screen:
            return PREFIX + "scroll", {"screen": frame[1], "direction": "down"}
    elif name == PREFIX + "scroll":
        save = re.search(r"\[(\d+)\][^\n]*Save fixture note", screen)
        if save and "FORM_NOT_SAVED" in screen:
            return PREFIX + "tap", {"screen": frame[1], "id": int(save[1])}
        if tools.count(PREFIX + "scroll") < 3:
            return PREFIX + "scroll", {"screen": frame[1], "direction": "down"}
    elif name == PREFIX + "tap":
        return PREFIX + "screen", {}
    elif name == PREFIX + "screen" and PREFIX + "tap" in tools:
        if f"FORM_SAVED {FORM_TEXT}" in screen:
            print("Confirmed typed note, scroll and saved state from DSH results", flush=True)
            return "text", "MH_PHONE_FORM_VERIFIED"
    return "text", "MH_FORM_FAILED_READBACK"


def coordinate_step(name, latest, screen, calls, results):
    tap = PREFIX + "tap_xy"
    read = PREFIX + "screen"
    attempts = list(calls.values()).count(tap)
    if name == PREFIX + "open" and not latest.get("is_error"):
        return read, {}
    if name == tap:
        if (attempts == 1 and latest.get("is_error") and "已过期" in screen
                and "COORD_HITS_0" in screen):
            print("DSH refused stale screenshot coordinates with zero fixture hits", flush=True)
            return read, {"image": True}
        if attempts == 2 and not latest.get("is_error"):
            return read, {}
        return "text", "MH_COORD_TAP_FAILED"

    if name != read or latest.get("is_error"):
        return "text", "MH_COORD_READ_FAILED"
    frame = re.search(r"屏幕 (s\d+) · Mobile Harness Phone Fixture", screen)
    if not frame:
        if attempts == 0 and list(calls.values()).count(read) < 5:
            sleep(0.6)
            return read, {}
        return "text", "MH_COORD_WRONG_SCREEN"
    if attempts == 2:
        if "COORD_HITS_1" in screen:
            print("DSH verified exactly one coordinate gesture reached the fixture", flush=True)
            return "text", "MH_PHONE_COORD_VERIFIED"
        return "text", "MH_COORD_UNEXPECTED_HIT_COUNT"
    if "COORD_HITS_0" not in screen:
        return "text", "MH_COORD_UNEXPECTED_HIT_COUNT"
    shots = [
        result for call_id, result in results.items()
        if calls[call_id] == read and "截图上的数字" in tool_text(result)
    ]
    if not shots:
        if list(calls.values()).count(read) < 6:
            return read, {"image": True}
        return "text", "MH_COORD_IMAGE_MISSING"
    if attempts == 0 and shots[0] is latest:
        # Invalidate this screenshot ID by publishing another observation first.
        return read, {}
    if attempts == 1 and (len(shots) < 2 or shots[-1] is not latest):
        return "text", "MH_COORD_IMAGE_MISSING"
    shot = shots[-1]
    observation = re.search(r"屏幕 (s\d+)", tool_text(shot))[1]
    data = screenshot(shot)
    if not data:
        return "text", "MH_COORD_IMAGE_MISSING"
    try:
        point = magenta_center(data)
    except ImportError:
        return "text", "MH_COORD_PILLOW_REQUIRED"
    if point is None:
        return "text", "MH_COORD_TARGET_MISSING"
    print(f"Detected the visual target in {observation} at {point}", flush=True)
    return tap, {"observation": observation, "x": point[0], "y": point[1]}


def magenta_center(data):
    from PIL import Image, ImageChops

    with Image.open(BytesIO(data)) as image:
        red, green, blue = image.convert("RGB").split()
        mask = ImageChops.multiply(red.point(lambda x: 255 if x > 180 else 0),
                                   green.point(lambda x: 255 if x < 95 else 0))
        mask = ImageChops.multiply(mask, blue.point(lambda x: 255 if x > 180 else 0))
        bounds = mask.getbbox()
        if not bounds:
            return None
        x1, y1, x2, y2 = bounds
        x, y = (x1 + x2) // 2, (y1 + y2) // 2
        if x2 - x1 >= 12 and y2 - y1 >= 12 and mask.getpixel((x, y)):
            return x, y
    return None


def swipe_step(name, latest, screen, calls, results):
    swipe = PREFIX + "swipe_xy"
    read = PREFIX + "screen"
    attempts = list(calls.values()).count(swipe)
    if name == PREFIX + "open" and not latest.get("is_error"):
        return read, {"image": True}
    if name == swipe:
        if attempts == 1 and latest.get("is_error") and "已过期" in screen and "SWIPE_HITS_0" in screen:
            print("DSH refused an expired swipe observation with zero fixture hits", flush=True)
            return read, {"image": True}
        if attempts == 2 and not latest.get("is_error"):
            return read, {}
        return "text", "MH_SWIPE_ACTION_FAILED"

    if name != read or latest.get("is_error"):
        return "text", "MH_SWIPE_READ_FAILED"
    if attempts == 2:
        if "SWIPE_HITS_1" in screen:
            print("DSH read back exactly one swipe from the fixture", flush=True)
            return "text", "MH_PHONE_SWIPE_VERIFIED"
        return "text", "MH_SWIPE_UNEXPECTED_HITS"

    shots = [
        result for call_id, result in results.items()
        if calls[call_id] == read and "截图上的数字" in tool_text(result)
        and "Mobile Harness Phone Fixture" in tool_text(result) and "SWIPE_HITS_0" in tool_text(result)
    ]
    if not shots:
        if list(calls.values()).count(read) < 5:
            sleep(0.6)
            return read, {"image": True}
        return "text", "MH_SWIPE_IMAGE_MISSING"
    if attempts == 0 and shots[-1] is latest:
        return read, {}  # Publish a newer observation before trying the original coordinates.
    if attempts == 1 and (len(shots) < 2 or shots[-1] is not latest):
        if list(calls.values()).count(read) < 7:
            sleep(0.8)
            return read, {"image": True}
        return "text", "MH_SWIPE_IMAGE_MISSING"
    if "SWIPE_HITS_0" not in screen:
        return "text", "MH_SWIPE_UNEXPECTED_HITS"
    shot = shots[-1]
    observation = re.search(r"屏幕 (s\d+) · Mobile Harness Phone Fixture", tool_text(shot))
    data = screenshot(shot)
    if not observation or not data:
        return "text", "MH_SWIPE_IMAGE_MISSING"
    path = cyan_path(data)
    if path is None:
        return "text", "MH_SWIPE_TARGET_MISSING"
    x, y, end_x = path
    print(f"Detected swipe path in {observation[1]} from ({x}, {y}) to ({end_x}, {y})", flush=True)
    return swipe, {"observation": observation[1], "x": x, "y": y, "end_x": end_x, "end_y": y}


def cyan_path(data):
    from PIL import Image, ImageChops

    with Image.open(BytesIO(data)) as image:
        red, green, blue = image.convert("RGB").split()
        mask = ImageChops.multiply(red.point(lambda x: 255 if x < 85 else 0),
                                   green.point(lambda x: 255 if x > 170 else 0))
        mask = ImageChops.multiply(mask, blue.point(lambda x: 255 if x > 215 else 0))
        bounds = mask.getbbox()
        if bounds is None:
            return None
        left, top, right, bottom = bounds
        width = right - left
        if width < 50 or bottom - top < 12:
            return None
        start_x, end_x = left + width // 5, right - width // 5
        y = (top + bottom) // 2
        if mask.getpixel((start_x, y)) and mask.getpixel((end_x, y)):
            return start_x, y, end_x
    return None


def secure_step(name, latest, screen, calls):
    read = PREFIX + "screen"
    tap = PREFIX + "tap"
    tools = list(calls.values())
    if name == PREFIX + "open" and not latest.get("is_error"):
        return read, {}
    if name == tap and not latest.get("is_error"):
        return read, {"image": True}
    if name == read and tap in tools:
        content = latest.get("content")
        has_image = isinstance(content, list) and any(part["type"] == "image" for part in content)
        if latest.get("is_error") and "安全窗口" in screen and not has_image:
            print("DSH refused the secure window and supplied no screenshot to the model", flush=True)
            return "text", "MH_PHONE_SECURE_VERIFIED"
        return "text", "MH_SECURE_SCREEN_NOT_REFUSED"
    if name == read and not latest.get("is_error"):
        frame = re.search(r"屏幕 (s\d+) · Mobile Harness Phone Fixture", screen)
        button = re.search(r"\[(\d+)\][^\n]*Protect fixture window", screen)
        if frame and button:
            return tap, {"screen": frame[1], "id": int(button[1])}
        if not frame and tools.count(read) < 5:
            sleep(0.6)
            return read, {}
    return "text", "MH_SECURE_SETUP_FAILED"


def is_jpeg(data):
    return data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")


def screenshot(result):
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for part in content:
        if part["type"] != "image":
            continue
        source = part["source"]
        if source["type"] == "file" and (image := UPLOADED_IMAGES.get(source["file_id"])):
            print(f"DSH tool JPEG referenced by model request: {len(image)} bytes, {source['file_id']}", flush=True)
            return image
        if source["type"] != "base64" or source["media_type"] != "image/jpeg":
            continue
        try:
            data = base64.b64decode(source["data"], validate=True)
        except binascii.Error:
            continue
        if is_jpeg(data):
            print(f"DSH tool JPEG received by model: {len(data)} bytes, SHA-256 {hashlib.sha256(data).hexdigest()}",
                  flush=True)
            return data
    return None


def tool_text(result):
    content = result.get("content", [])
    return content if isinstance(content, str) else "\n".join(
        block["text"] for block in content if block["type"] == "text"
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] not in ("/models", "/v1/models"):
            self.send_error(404)
            return
        catalog = {"object": "list", "data": [{
            "id": "deepseek-flash",
            "object": "model",
            "input_modalities": ["text", "image"],
            "api_capabilities": {"anthropic_messages": {"tool_update": "addition-only"}},
        }]}
        self.send_json(catalog)

    def send_json(self, value):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())

    def upload_image(self):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 4 * 1024 * 1024 or self.headers.get_content_type() != "multipart/form-data":
            self.send_error(400)
            return
        header = f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode()
        form = BytesParser(policy=policy.default).parsebytes(header + self.rfile.read(size))
        for field in form.iter_parts():
            if field.get_param("name", header="content-disposition") != "file":
                continue
            data = field.get_payload(decode=True)
            if field.get_content_type() == "image/jpeg" and is_jpeg(data):
                file_id = "file_" + hashlib.sha256(data).hexdigest()
                image = {
                    "id": file_id, "type": "file", "mime_type": "image/jpeg",
                    "filename": "fixture.jpg", "size_bytes": len(data),
                    "created_at": datetime.now(UTC).isoformat(),
                }
                UPLOADED_IMAGES[file_id] = data
                self.send_json(image)
                return
        self.send_error(400)

    def do_POST(self):
        path = self.path.partition("?")[0]
        if path == "/v1/files":
            self.upload_image()
            return
        if path != "/v1/messages":
            self.send_error(404)
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        kind, value = decide(request)
        usage = {"input_tokens": 5, "output_tokens": 1}
        message = {
            "type": "message", "id": "msg_phone_fixture", "role": "assistant",
            "model": request["model"], "content": [], "stop_reason": None, "usage": usage,
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.event("message_start", message=message)
        if kind == "text":
            self.event("content_block_start", index=0, content_block={"type": "text", "text": ""})
            delta = {"type": "text_delta", "text": value}
            reason = "end_turn"
        else:
            print(f"Model requested {kind}", flush=True)
            block = {"type": "tool_use", "id": f"fixture_{kind}_{len(request['messages'])}",
                     "name": kind, "input": {}}
            self.event("content_block_start", index=0, content_block=block)
            delta = {"type": "input_json_delta", "partial_json": json.dumps(value)}
            reason = "tool_use"
        self.event("content_block_delta", index=0, delta=delta)
        self.event("content_block_stop", index=0)
        self.event("message_delta", delta={"stop_reason": reason, "stop_sequence": None}, usage=usage)
        self.event("message_stop")

    def event(self, kind, **fields):
        payload = json.dumps({"type": kind, **fields})
        self.wfile.write(f"event: {kind}\ndata: {payload}\n\n".encode())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18774)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.serve_forever()
