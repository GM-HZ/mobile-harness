"""Verify production HarmonyOS download, local DSH replies and tool feedback."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import posixpath
import re
import runpy
import socket
import subprocess
import sys
import time
import uuid


UI = runpy.run_path(str(Path(__file__).with_name("emulator-chat-import-ui.py")))
SUPPORT = UI["support"]
PROVIDER = "mobile-harness-local"
KEY_REF = "MOBILE_HARNESS_LOCAL_INFERENCE_KEY"
BASE_URL = "http://127.0.0.1:39765/v1"
DONE = "MH_EMULATOR_LOCAL_INFERENCE_E2E_DONE"
MODELS = {
    "lfm3-1.7b-q4": ("LFM3-1.7B Q4", 1099627808,
                     "3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4"),
    "qwen3.5-2b-q4": ("Qwen3.5-2B Q4", 1280835840,
                      "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223"),
}
BASENAME = "answer.txt"


class CheckFailed(RuntimeError):
    """An assertion with a message safe to include in evidence."""


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


def elapsed(start):
    return round((time.monotonic() - start) * 1000)


def progress(stage, **values):
    print(json.dumps({"stage": stage, **values}, ensure_ascii=False), file=sys.stderr, flush=True)


def write_evidence(output, evidence):
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output)


def midpoint(row):
    dimensions = [int(value) for value in re.findall(r"-?\d+", row["bounds"])]
    if len(dimensions) != 4:
        return None
    left, top, right, bottom = dimensions
    if left < right and top < bottom:
        return (left + right) // 2, (top + bottom) // 2
    return None


def find(rows, labels, kinds=()):
    return next((row for row in rows if midpoint(row)
                 and (row["text"] in labels or row["description"] in labels)
                 and (not kinds or row["type"].casefold() in kinds)), None)


def tap(device, row):
    x, y = midpoint(row)
    device.hdc("shell", "uitest", "uiInput", "click", str(x), str(y))


def wait_until(predicate, timeout, message, interval=.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    raise CheckFailed(message)


def foreground(device):
    try:
        device.start()
    except RuntimeError:
        device.hdc("shell", "power-shell", "wakeup")
        device.hdc("shell", "uinput", "-T", "-m", "660", "2100", "660", "650", "500")
        device.start()


def open_settings(device):
    back = find(UI["controls"](device), {"返回会话"}, ("button",))
    if back:
        tap(device, back)

    def settings_button():
        rows = UI["controls"](device)
        if find(rows, {"预览版说明", "Preview Notice"}, ("dialog",)):
            next_button = find(rows, {"继续", "Continue"}, ("button",))
        elif find(rows, {"开始使用", "Get started"}, ("dialog",)):
            next_button = find(rows, {"关闭", "Close"}, ("button",))
        else:
            button = find(rows, {"设置", "Settings"})
            if button:
                return button
            next_button = find(rows, {"账号菜单", "Account menu", "打开侧边栏", "Open sidebar"})
        if next_button:
            tap(device, next_button)
        return None

    tap(device, wait_until(settings_button, 25, "Could not open the shipped DSH settings"))
    general = find(UI["controls"](device), {"通用设置", "General settings", "General"})
    if general:
        tap(device, general)

    def manage_button():
        rows = UI["controls"](device)
        button = find(rows, {"管理模型", "Manage models"}, ("button",))
        if not button:
            device.hdc("shell", "uitest", "uiInput", "swipe", "1080", "1790", "1080", "670")
        return button

    tap(device, wait_until(manage_button, 20, "Local model action is absent from general settings"))
    wait_until(lambda: find(UI["controls"](device), {"本地推理"}), 20, "Native Local Inference page did not open")


def model_action(rows, label, action):
    anchor = find(rows, {label})
    if not anchor:
        return None
    anchors = [row for other, *_ in MODELS.values() if other != label and (row := find(rows, {other}))]
    x, y = midpoint(anchor)
    matching = []
    for row in rows:
        if row["type"].casefold() != "button" or (row["text"] != action and row["description"] != action):
            continue
        point = midpoint(row)
        if point and point[0] > x and all(abs(point[1] - y) < abs(point[1] - midpoint(other)[1])
                                         for other in anchors):
            matching.append(row)
    return min(matching, key=lambda row: abs(midpoint(row)[1] - y), default=None)


def preference_toggle(rows):
    kinds = ("toggle", "switch")
    if match := find(rows, {"优先使用本地推理"}, kinds):
        return match
    toggles = [row for row in rows if row["type"].casefold() in kinds and midpoint(row)]
    return toggles[0] if len(toggles) == 1 else None


def published_weight(device, path):
    return device.app(f"if test -e {path} || test -L {path}; then printf PRESENT; else printf ABSENT; fi")


def partial_files_present(device, model):
    return device.app(f"if test -d local-models; then find local-models -maxdepth 1 -name '{model}-*.download'; fi") != ""


def download(device, model, label, path, size, digest, timeout, result, checkpoint):
    started = time.monotonic()
    observed = 0
    rate_limit = 0
    try:
        tap(device, wait_until(lambda: model_action(UI["controls"](device), label, "下载"),
                               20, "Selected model has no download button"))
        result["clickedAppDownload"] = True

        def finished():
            nonlocal observed, rate_limit
            rows = UI["controls"](device)
            percentages = [int(row["text"][:-1]) for row in rows if re.fullmatch(r"\d{1,3}%", row["text"])]
            observed = max([observed, *percentages])
            if find(rows, {"正在校验模型…"}):
                result["uiVerificationObserved"] = True
            duration = elapsed(started)
            if duration >= rate_limit:
                files = device.app(f"for file in local-models/{model}-*.download; "
                                   'do if test -f "$file"; then stat -c %s "$file"; fi; done')
                written = max((int(line) for line in files.splitlines() if line.isdecimal()), default=0)
                rate_limit = duration + 15000
                result.update(elapsedMs=duration, maxObservedProgressPercent=observed,
                              maxObservedPartialBytes=max(written, result.get("maxObservedPartialBytes", 0)))
                progress("download", elapsedMs=duration, partialBytes=written, totalBytes=size,
                         maxObservedProgressPercent=observed)
                checkpoint()
            for row in rows:
                value = row["text"]
                if matched := re.fullmatch(r"系统下载失败（类别 (\d+)），可再次尝试", value):
                    result["systemFaultCategory"] = int(matched[1])
                    raise CheckFailed("The selected production download reported a system failure")
                if value in {"系统下载失败，可再次尝试", "下载已暂停，可再次尝试", "可用存储空间不足",
                             "文件大小与模型目录不符", "模型文件 SHA-256 校验失败"}:
                    raise CheckFailed(value)
            return model_action(rows, label, "使用此模型")

        wait_until(finished, timeout, "App download and verification exceeded the deadline", interval=1)
        file_size = device.app(f"stat -c %s {path}")
        checksum = device.app(f"sha256sum {path}").split()
        require(file_size == str(size), "Published model byte size differs from the pin")
        require(checksum and checksum[0] == digest, "Published model SHA-256 differs from the pin")
        result.update(verified=True, bytes=size, sha256=digest)
        progress("download", elapsedMs=elapsed(started), verifiedBytes=size)
    finally:
        result.update(elapsedMs=elapsed(started), maxObservedProgressPercent=observed)


def route_settings(device):
    rows = device.rpc("settings/describe", {})["namespaces"]
    by_name = {row["ns"]: row["value"] for row in rows}
    return by_name["agent-default-model"], by_name["llm-pi-ai"].get("providers", {})


def credentials_present(device):
    return device.rpc("credentials/describe", {"refs": [KEY_REF]})[KEY_REF]["configured"]


def turn_data(rows, model, marker, workspace, tool_required, result, prior_header=None):
    replies = [row["data"]["message"] for row in rows if row["type"] == "assistant/message"]
    headers = [row["data"]["header"]["config"] for row in rows if row["type"] == "request/header"]
    calls = [row["data"] for row in rows if row["type"] == "tool/call"]
    results = [row["data"]["message"] for row in rows if row["type"] == "tool/result"]
    last = "".join(part.get("text", "") for part in replies[-1]["content"]
                   if part["type"] == "text").strip() if replies else ""

    def expected_route(config):
        return (config.get("provider"), config.get("model")) == (PROVIDER, model)

    effective_headers = headers or ([prior_header] if prior_header is not None else [])
    result.update(
        requestRoutedLocally=bool(effective_headers) and all(expected_route(header) for header in effective_headers),
        requestHeaderContinued=not headers and prior_header is not None,
        allAssistantMessagesLocal=bool(replies) and all(expected_route(row.get("source", {})) for row in replies),
        assistantReplyCount=len(replies),
        toolCallCount=len(calls),
        toolCalls=[call["name"] if call["name"] == "read" else "<unexpected>" for call in calls],
        finalContainsExpectedText=marker in last,
        finalExactlyExpectedText=marker == last,
    )
    if not tool_required:
        return not calls and not results and marker == last
    if len(calls) != 1 or calls[0]["name"] != "read":
        return False
    try:
        arguments = json.loads(calls[0]["arguments"])
        path = arguments.get("file_path")
    except (ValueError, TypeError, AttributeError):
        path = None
    result["readOwnedFixture"] = isinstance(path, str) and posixpath.normpath(
        posixpath.join(workspace, path)) == f"{workspace}/{BASENAME}"
    result["matchingToolResult"] = len(results) == 1 and results[0].get("toolCallId") == calls[0]["callId"]
    result["toolReturnedMarker"] = result["matchingToolResult"] and not results[0].get("isError") and any(
        marker in part.get("text", "") for part in results[0]["content"] if part["type"] == "text")
    return result["readOwnedFixture"] and result["toolReturnedMarker"] and result["finalContainsExpectedText"]


def run_session(device, model, timeout, evidence, cleanup, stage):
    nonce = uuid.uuid4().hex[:12]
    folder = f"alpine/workspace-native/mh-local-inference-{nonce}"
    workspace = SUPPORT["WORKSPACE"] + f"/mh-local-inference-{nonce}"
    marker = uuid.uuid4().hex[:12]
    with ExitStack() as owned:
        require(device.app(f"mkdir {folder} && printf CREATED") == "CREATED", "Could not create isolated fixture")
        owned.callback(cleanup, "removeWorkspaceDirectory", lambda: require(
            device.app(f"rm -f {folder}/{BASENAME} && rmdir {folder} && printf REMOVED") == "REMOVED",
            "Could not remove the owned fixture directory"))
        require(device.app(f"printf %s {marker} > {folder}/{BASENAME} && printf WRITTEN") == "WRITTEN",
                "Could not write synthetic fixture")
        registered = device.rpc("workspace/create", {"request": {"path": workspace}})
        require(registered["created"], "Workspace registration is not owned by the fixture")
        workspace_id = registered["workspace"]["workspaceId"]
        owned.callback(cleanup, "removeWorkspaceRegistration", lambda: require(
            device.rpc("workspace/delete", {"request": {"workspaceId": workspace_id}})["deleted"],
            "Could not delete the owned workspace registration"))
        session = device.rpc("session/create", {"request": {"workspaceId": workspace_id,
                                                            "agentPreset": "standard"}})["sessionId"]
        session_request = {"request": {"sessionId": session}}
        owned.callback(cleanup, "archiveSession", lambda: require(
            session in device.rpc("workspace/archiveSession", session_request)["archivedSessionIds"],
            "Could not archive the owned session"))
        owned.callback(cleanup, "cancelSession", device.rpc, "session/cancel", session_request)
        permission = device.rpc("commands/execute", {"agentId": session, "line": "/permission read-only",
                                                     "submittedAttachments": []})["result"]
        require(permission["kind"] == "success" and "read-only" in permission["text"],
                "Could not establish read-only fixture permission")
        evidence.update(sharedDshSession=True, agentPreset="standard")
        turns = (
            ("plainTurn", "请只回复 LOCAL_READY。", "LOCAL_READY"),
            ("readToolTurn", f"请只用 read 工具读取此工作区的 {BASENAME} 一次。"
             "然后在最终回复中给出文件中的十六进制标记。", marker),
        )
        for name, prompt, expected in turns:
            result = evidence[name] = {}
            stage(name)
            run_turn(device, session, model, workspace, name, prompt, expected, timeout, result,
                     lambda: stage(name, announce=False))


def run_turn(device, session, model, workspace, name, prompt, expected, timeout, result, checkpoint):
    previous = SUPPORT["events"](device, session)
    baseline = max((row["seq"] for row in previous), default=-1)
    prior_header = next((row["data"]["header"]["config"] for row in reversed(previous)
                         if row["type"] == "request/header"), None)
    result.update(baselineSeq=baseline, deadlineSeconds=timeout)
    device.rpc("session/prompt", {"request": {
        "sessionId": session, "requestId": str(uuid.uuid4()), "mode": "queue",
        "content": [{"type": "text", "text": prompt}],
    }})
    started = time.monotonic()
    next_log = 0
    rows = []
    last_end = None
    while elapsed(started) < timeout * 1000:
        rows = [row for row in SUPPORT["events"](device, session) if row["seq"] > baseline]
        last_end = next((row["data"]["reason"] for row in reversed(rows) if row["type"] == "turn/end"), None)
        duration = elapsed(started)
        if duration >= next_log:
            next_log = duration + 15000
            result.update(elapsedMs=duration, newEventCount=len(rows))
            progress(name, elapsedMs=duration, newEventCount=len(rows))
            checkpoint()
        if last_end:
            break
        time.sleep(1)
    result.update(elapsedMs=elapsed(started), newEventCount=len(rows),
                  completionReason=last_end["kind"] if last_end else "timeout")
    if last_end and isinstance(error := last_end.get("error"), dict):
        code = error.get("code")
        if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z_]{0,40}", code):
            result["failureCode"] = code
        if isinstance(error.get("status"), int):
            result["httpStatus"] = error["status"]
    matches = turn_data(rows, model, expected, workspace, name == "readToolTurn", result, prior_header)
    progress(name, elapsedMs=result["elapsedMs"], completionReason=result["completionReason"],
             assistantReplyCount=result["assistantReplyCount"], toolCallCount=result["toolCallCount"])
    require(result["completionReason"] == "completed", "DSH did not complete the requested turn")
    require(result["requestRoutedLocally"] and result["allAssistantMessagesLocal"],
            "DSH turn route or reply provider did not match the selected local model")
    require(matches, "DSH did not produce the expected text or owned tool result")
    result["passed"] = True
    checkpoint()


def release_model(device, label, model, path, baseline, providers, cleanup):
    def release():
        rows = UI["controls"](device)
        if button := model_action(rows, label, "取消"):
            tap(device, button)
        wait_until(lambda: not (find(rows := UI["controls"](device), {"正在更新本地推理…"})
                                or model_action(rows, label, "取消")),
                   60, "App still reports an in-progress test operation")
        if button := find(UI["controls"](device), {"停止本地推理"}, ("button",)):
            tap(device, button)
        wait_until(lambda: route_settings(device) == (baseline, providers) and not credentials_present(device),
                   40, "App did not clear the owned route and credential")
        require(device.app(f"rm -f {path} && printf REMOVED") == "REMOVED",
                "Could not remove the downloaded fixture weight")
        require(published_weight(device, path) == "ABSENT" and not partial_files_present(device, model),
                "App weight or partial remained after cleanup")

    cleanup("stopAppAndRemoveOwnedWeight", release)


def execute(args, evidence):
    label, size, digest = MODELS[args.model]
    path = f"local-models/{args.model}-{digest}.gguf"
    cleanup_errors = evidence["cleanupErrors"]

    def stage(name, announce=True):
        evidence["stage"] = name
        if announce:
            progress(name)
        write_evidence(args.output, evidence)

    def cleanup(name, action, *params):
        try:
            action(*params)
            evidence["cleanup"].append(name)
            return True
        except Exception as error:
            cleanup_errors.append({"step": name, "type": type(error).__name__})
            return False

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        host_port = reservation.getsockname()[1]
    device = SUPPORT["Emulator"](args.target, host_port)
    with ExitStack() as owned:
        stage("install")
        with args.hap.open("rb") as file:
            evidence["hapSha256"] = hashlib.file_digest(file, "sha256").hexdigest()
        require("install bundle successfully" in device.hdc("install", str(args.hap)), "Could not install the tested HAP")
        forward = (f"tcp:{host_port}", "tcp:19592")
        require("Forwardport result:OK" in device.hdc("fport", *forward), "Could not open the DSH HDC forward")

        def remove_forward():
            device.hdc("fport", "rm", *forward)
            require(" ".join(forward) not in device.hdc("fport", "ls"), "DSH forward remained")

        owned.callback(cleanup, "removeDshForward", remove_forward)
        stage("boot")
        foreground(device)
        evidence["readyMs"] = device.ready("normal")
        baseline, providers = route_settings(device)
        require(PROVIDER not in providers and baseline.get("provider") != PROVIDER and not credentials_present(device),
                "Acceptance requires a clean local provider, default and credential")
        require(published_weight(device, path) == "ABSENT" and not partial_files_present(device, args.model),
                "Acceptance requires the selected model and its partial downloads to be absent")
        stage("open-settings")
        open_settings(device)
        evidence["openedActualSettings"] = True
        owned.callback(release_model, device, label, args.model, path, baseline, providers, cleanup)
        stage("download")
        download(device, args.model, label, path, size, digest, args.download_timeout, evidence["download"],
                 lambda: stage("download", announce=False))

        stage("start-local-model")
        start = time.monotonic()
        tap(device, wait_until(lambda: model_action(UI["controls"](device), label, "使用此模型"),
                               20, "Verified downloaded model has no start button"))
        wait_until(lambda: model_action(UI["controls"](device), label, "运行中"), 90, "Selected model failed to start")
        recorded = route_settings(device)[1].get(PROVIDER, {})
        require(recorded.get("api") == "openai-completions" and recorded.get("baseURL") == BASE_URL
                and recorded.get("apiKeyEnv") == KEY_REF and credentials_present(device)
                and [model.get("id") for model in recorded.get("models", [])] == [args.model],
                "Native model was not registered with the authenticated loopback provider")
        evidence["activationMs"] = elapsed(start)

        stage("prefer-local")
        tap(device, wait_until(lambda: preference_toggle(UI["controls"](device)),
                               15, "Prefer-local toggle was not visible"))

        def local_default():
            default = device.rpc("session/modelCatalog", {}).get("default") or {}
            return (default.get("provider"), default.get("model")) == (PROVIDER, args.model)

        wait_until(local_default, 30, "DSH did not use the selected local default")
        evidence["preferredLocalModel"] = args.model

        stage("create-session")
        run_session(device, args.model, args.turn_timeout, evidence, cleanup, stage)

        stage("restore-prior-route")
        tap(device, wait_until(lambda: preference_toggle(UI["controls"](device)),
                               15, "Prefer-local toggle was unavailable for restoring the default"))
        wait_until(lambda: route_settings(device)[0] == baseline, 30, "Turning off preference did not restore the default")
        evidence["priorDefaultRestored"] = True
        tap(device, wait_until(lambda: find(UI["controls"](device), {"停止本地推理"}, ("button",)),
                               15, "Native Stop control was unavailable"))
        wait_until(lambda: route_settings(device) == (baseline, providers) and not credentials_present(device),
                   35, "Stop did not restore providers and remove the temporary loopback credential")
        evidence["routeAndCredentialRemoved"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="owned dedicated loopback HarmonyOS Phone emulator")
    parser.add_argument("output", type=Path)
    parser.add_argument("--hap", required=True, type=Path, help="exact unsigned self/local-inference HAP to install")
    parser.add_argument("--model", choices=MODELS, default="lfm3-1.7b-q4")
    parser.add_argument("--download-timeout", type=int, default=900)
    parser.add_argument("--turn-timeout", type=int, default=540,
                        help="per-turn diagnostic deadline in seconds (default: 540)")
    args = parser.parse_args()
    if not re.fullmatch(r"127\.0\.0\.1:\d{1,5}", args.target) or not 0 < int(args.target.split(":")[1]) < 65536:
        parser.error("target must be a dedicated 127.0.0.1 emulator port")
    if args.download_timeout <= 0 or args.turn_timeout <= 0:
        parser.error("timeouts must be positive")
    if not args.hap.is_file():
        parser.error("--hap must refer to an existing HAP")
    start = time.monotonic()
    root = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    evidence = {"schema": 1, "probe": "harmonyos-emulator-local-inference-e2e", "commit": commit,
                "target": args.target, "model": args.model, "stage": "connect", "ok": False,
                "download": {}, "cleanup": [], "cleanupErrors": []}
    try:
        execute(args, evidence)
        if not evidence["cleanupErrors"]:
            evidence.update(ok=True, stage="complete", done=DONE)
    except CheckFailed as error:
        evidence["failure"] = {"type": type(error).__name__, "message": str(error)}
    except (Exception, SystemExit) as error:
        evidence["failure"] = {"type": type(error).__name__}
    finally:
        evidence["elapsedMs"] = elapsed(start)
        write_evidence(args.output, evidence)
        print(json.dumps(evidence, ensure_ascii=False), flush=True)
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
