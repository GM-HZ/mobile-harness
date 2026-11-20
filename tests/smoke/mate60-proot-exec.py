"""Probe PRoot exec semantics on a HDC-attached HarmonyOS phone.

The script creates a throwaway workspace and session, asks the model to invoke
the `bash` tool exactly once with a fixed probe command, and records the raw
tool output. It answers whether arbitrary `exec` of guest binaries/scripts
works in the packaged PRoot rootfs, and how unsigned copies behave.

    python3 tests/smoke/mate60-proot-exec.py --target <usb-serial> --output out.json
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

HDC = "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc"
BUNDLE = "org.sayact.nodepoc"
FILES = "/data/storage/el2/base/haps/entry/files"
HOST_HEADER = "127.0.0.1:19592"

PROBE = """set +e
echo "PWD=$PWD"
echo "--- guest executables ---"
ls -l /bin/sh /bin/bash /bin/node /bin/busybox /usr/bin/python3 /usr/bin/git 2>&1 | head -12
echo "--- bound exec ---"
( exec /bin/sh -c 'echo EXEC_SH_OK' ); echo "SH_EXIT=$?"
( exec /bin/bash -c 'echo EXEC_BASH_OK' ); echo "BASH_EXIT=$?"
( exec /bin/node -e 'console.log("EXEC_NODE_OK")' ); echo "NODE_EXIT=$?"
( exec /usr/bin/python3 -c 'print("EXEC_PY_OK")' ); echo "PY_EXIT=$?"
( exec /usr/bin/git --version ); echo "GIT_EXIT=$?"
echo "--- script exec ---"
printf '#!/bin/sh\\necho EXEC_SCRIPT_OK\\n' > ./proot-exec.sh; chmod +x ./proot-exec.sh
( exec ./proot-exec.sh ); echo "SCRIPT_EXIT=$?"
echo "--- unbound applet ---"
( exec /bin/xxd /dev/null ); echo "XXD_EXIT=$?"
echo "--- copied guest ELF ---"
cp /bin/busybox ./proot-bx 2>/dev/null; chmod +x ./proot-bx 2>/dev/null
( exec ./proot-bx true ); echo "COPY_BUSYBOX_EXIT=$?"
cp /bin/node ./proot-node 2>/dev/null; chmod +x ./proot-node 2>/dev/null
( exec ./proot-node -e 'console.log("COPY_NODE_OK")' ); echo "COPY_NODE_EXIT=$?"
echo "--- downloaded style unsigned ELF ---"
printf '\\177ELF' > ./proot-fake; chmod +x ./proot-fake
( exec ./proot-fake ); echo "FAKE_EXIT=$?"
echo PROOT_EXEC_PROBE_DONE
"""

NATIVE_PROBE = """set +e
echo "PWD=$PWD"
echo "--- dlopen a copied guest library ---"
cp /usr/lib/libstdc++.so.6 ./copied-libstdc++.so 2>&1
python3 -c "import ctypes; ctypes.CDLL('./copied-libstdc++.so'); print('DLOPEN_COPY_OK')" 2>&1; echo "DLOPEN_COPY_EXIT=$?"
echo "--- dlopen the bound guest library path ---"
python3 -c "import ctypes; ctypes.CDLL('/usr/lib/libstdc++.so.6'); print('DLOPEN_BOUND_OK')" 2>&1; echo "DLOPEN_BOUND_EXIT=$?"
echo "--- memfd + fexecve of a copied guest binary ---"
python3 -c "import os; data=open('/bin/busybox','rb').read(); fd=os.memfd_create('bx'); os.write(fd,data); os.fexecve(fd,['busybox','echo','MEMFD_EXEC_OK'],os.environ)" 2>&1; echo "MEMFD_EXIT=$?"
echo "--- interpreters and package managers ---"
python3 --version 2>&1
node --version 2>&1
command -v npm pnpm pip pip3 2>&1
python3 -m pip --version 2>&1 | head -1
echo NATIVE_PROBE_DONE
"""

BYPASS_PROBE = """set +e
echo "PWD=$PWD"
echo "--- memfd + libc fexecve ---"
( python3 -c "import ctypes, os; data=open('/bin/busybox','rb').read(); fd=os.memfd_create('bx'); os.write(fd,data); libc=ctypes.CDLL(None, use_errno=True); argv=(ctypes.c_char_p*3)(b'busybox', b'echo', b'MEMFD_FEXECVE_OK'); envp=(ctypes.c_char_p*1)(None); rc=libc.fexecve(fd, argv, envp); errno=ctypes.get_errno(); print('FEXECVE_RC', rc, 'ERRNO', errno, os.strerror(errno))" 2>&1 ); echo "FEXECVE_EXIT=$?"
echo "--- memfd via /proc/self/fd execve ---"
( python3 -c "import os; data=open('/bin/busybox','rb').read(); fd=os.memfd_create('bx'); os.write(fd,data); os.execve('/proc/self/fd/%d' % fd, ['busybox','echo','MEMFD_PROCFD_OK'], os.environ)" 2>&1 ); echo "PROCFD_EXIT=$?"
echo "--- copied binary via /proc fd ---"
( python3 -c "import os; os.execve('/proc/self/fd/%d' % os.open('./proot-bx', os.O_RDONLY), ['bx','echo','COPIED_PROCFD_OK'], os.environ)" 2>&1 ); echo "COPIED_PROCFD_EXIT=$?"
echo "--- pure interpreter paths ---"
python3 -c "print('PY_RUNTIME_OK')" 2>&1; echo "PY_RUNTIME_EXIT=$?"
node -e "console.log('NODE_RUNTIME_OK')" 2>&1; echo "NODE_RUNTIME_EXIT=$?"
python3 -m pip --version 2>&1 | head -1
echo BYPASS_PROBE_DONE
"""


class Device:
    def __init__(self, target, port):
        self.target = target
        self.url = f"http://127.0.0.1:{port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.device = [HDC, "-t", target]

    def hdc(self, *args):
        return subprocess.check_output(self.device + list(args), text=True, timeout=180).strip()

    def app(self, command):
        return self.hdc("shell", "-b", BUNDLE, "cd data/storage/el2/base/haps/entry/files && " + command)

    def state(self):
        return json.loads(self.app("cat mobile-harness-boot.json"))

    def cookie(self):
        return json.loads(self.app("cat alpine/tmp/dsh-client-native-launch"))["cookie"].split(";", 1)[0]

    def rpc(self, method, args, timeout=60):
        body = json.dumps({"type": "client-request", "rpcId": str(uuid.uuid4()), "method": method,
                           "payload": {"args": args}}).encode()
        request = urllib.request.Request(self.url + "/api/" + method, body, headers={
            "Content-Type": "application/json", "Host": HOST_HEADER, "Cookie": self.cookie()})
        with self.opener.open(request, timeout=timeout) as response:
            result = json.load(response)["result"]
        if not result["ok"]:
            raise RuntimeError(f"{method}: {result['error']['code']}")
        return result.get("value")

    def web_status(self):
        request = urllib.request.Request(self.url + "/", headers={"Host": HOST_HEADER, "Cookie": self.cookie()})
        try:
            with self.opener.open(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def ready(self, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.state() == {"mode": "normal", "pending": False} and self.web_status() == 200:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False


def events(device, session_id):
    response = device.rpc("session/events", {"request": {"address": {"kind": "session", "sessionId": session_id}}},
                          timeout=120)
    return [row["event"] for row in response["records"] if row.get("event")]


def prompt(device, session_id, instruction, timeout=240):
    text = "ACCEPTANCE" + uuid.uuid4().hex.upper() + ": " + instruction
    before = max((row["seq"] for row in events(device, session_id)), default=0)
    device.rpc("session/prompt", {"request": {
        "sessionId": session_id, "requestId": str(uuid.uuid4()), "mode": "queue",
        "content": [{"type": "text", "text": text}],
    }})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = [row for row in events(device, session_id) if row["seq"] > before]
        ends = [row for row in rows if row["type"] == "turn/end"]
        if ends and ends[-1]["data"]["reason"]["kind"] == "completed":
            calls = [row["data"] for row in rows
                     if row["type"] == "tool/call" and row["data"]["turn"] == ends[-1]["data"]["turn"]]
            ids = {call["callId"] for call in calls}
            results = [row["data"]["message"] for row in rows
                       if row["type"] == "tool/result" and row["data"]["message"].get("toolCallId") in ids]
            return calls, results, rows
        time.sleep(0.2)
    raise AssertionError("The probe turn did not finish")


def texts(results):
    return "\n".join(item.get("text", "") for result in results for item in result["content"])


def run(device, port, output, probe=None):
    name = "proot-exec-" + uuid.uuid4().hex[:8]
    native = FILES + "/alpine/workspace-native/" + name
    probe = probe or PROBE
    kinds = {id(PROBE): "real-device PRoot exec semantics probe",
             id(NATIVE_PROBE): "real-device native execution bypass probe",
             id(BYPASS_PROBE): "real-device runtime native-code bypass probe"}
    evidence = {"kind": kinds.get(id(probe), "real-device probe"), "target": device.target,
                "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "workspace": native}
    device.hdc("fport", "tcp:" + str(port), "tcp:19592")
    session = None
    try:
        device.hdc("shell", "aa", "start", "-a", "EntryAbility", "-b", BUNDLE)
        if not device.ready():
            raise SystemExit("The app did not become ready")
        device.app("mkdir -p alpine/workspace-native/" + name)
        workspace = device.rpc("workspace/create", {"request": {"path": native}})["workspace"]["workspaceId"]
        session = device.rpc("session/create", {"request": {"workspaceId": workspace}})["sessionId"]
        catalog = device.rpc("session/modelCatalog", {})
        default = catalog.get("default") or {}
        evidence["model"] = {"default": default}
        if default.get("provider") and default.get("model"):
            device.rpc("session/selectModel", {"request": {
                "sessionId": session, "provider": default["provider"], "model": default["model"],
                "reasoningEffort": default.get("reasoningEffort") or "off"}})
        device.rpc("commands/execute", {"agentId": session, "line": "/permission danger-full-access",
                                       "submittedAttachments": []})
        modes = [row["data"]["mode"] for row in events(device, session) if row["type"] == "sandbox/mode"]
        evidence["permissionMode"] = modes[-1] if modes else None
        instruction = ("Actually call bash exactly once now with precisely "
                       + json.dumps({"command": probe, "description": "Probe PRoot exec semantics"})
                       + ". Use no other tools. Report the result and stop.")
        calls, results, _ = prompt(device, session, instruction)
        evidence["toolCalls"] = calls
        bash_calls = [call for call in calls if call["name"] == "bash"]
        evidence["bashCallCount"] = len(bash_calls)
        if not bash_calls:
            raise AssertionError("The model did not call bash")
        arguments = json.loads(bash_calls[0]["arguments"])
        evidence["commandMatched"] = arguments.get("command") == probe
        evidence["command"] = arguments.get("command")
        text = texts(results)
        evidence["resultText"] = text
        markers = {}
        for marker in ("EXEC_SH_OK", "EXEC_BASH_OK", "EXEC_NODE_OK", "EXEC_PY_OK", "EXEC_SCRIPT_OK",
                       "COPY_NODE_OK", "PROOT_EXEC_PROBE_DONE"):
            markers[marker] = marker in text
        exits = {}
        for line in text.splitlines():
            if "=" in line and line.split("=", 1)[0].endswith("_EXIT"):
                key, value = line.split("=", 1)
                exits[key] = value.strip()
        evidence["markers"] = markers
        evidence["exits"] = exits
        evidence["ok"] = markers["PROOT_EXEC_PROBE_DONE"]
    finally:
        try:
            if session:
                device.rpc("session/cancel", {"request": {"sessionId": session}})
        except Exception:
            pass
        device.hdc("fport", "rm", "tcp:" + str(port), "tcp:19592")
        Path(output).write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: evidence.get(key) for key in
                      ("ok", "commandMatched", "markers", "exits")}, ensure_ascii=False, indent=1))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="37R0224115035605")
    parser.add_argument("--port", type=int, default=19671)
    parser.add_argument("--output", type=Path, default=Path(".build/mate60-proot-exec.json"))
    parser.add_argument("--probe", choices=["exec", "native", "bypass"], default="exec")
    args = parser.parse_args()
    probe = {"native": NATIVE_PROBE, "bypass": BYPASS_PROBE}.get(args.probe, PROBE)
    run(Device(args.target, args.port), args.port, args.output, probe)
    print(args.output)


if __name__ == "__main__":
    main()
