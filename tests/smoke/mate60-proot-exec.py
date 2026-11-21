"""Probe PRoot exec semantics on a HDC-attached HarmonyOS phone.

The script creates a throwaway workspace and session, asks the model to invoke
the `bash` tool exactly once with a fixed probe command, and records the raw
tool output. It answers whether arbitrary `exec` of guest binaries/scripts
works in the packaged PRoot rootfs, and how unsigned copies behave.

    python3 tests/smoke/mate60-proot-exec.py --target <usb-serial> --output out.json
"""
import argparse
import json
import re
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

RUNTIME_PROBE = """set +e
echo "PWD=$PWD"
echo "--- pip install a pure-python tool at runtime ---"
python3 -m pip install --no-cache-dir --user pyfiglet > ./pip-install.log 2>&1; echo "PIP_INSTALL_EXIT=$?"
tail -4 ./pip-install.log
python3 -m pyfiglet -f small MH 2>&1 | head -6; echo "PYFIGLET_EXIT=$?"
echo "--- node js runtime ---"
node -e "console.log('NODE_JS_RUNTIME_OK')" 2>&1; echo "NODE_JS_EXIT=$?"
echo RUNTIME_PROBE_DONE
"""

RUNTIME_TARGET_PROBE = """set +e
echo "PWD=$PWD"
echo "--- pip install into a project directory ---"
python3 -m pip install --no-cache-dir --target ./pylibs pyfiglet > ./pip-target.log 2>&1; echo "PIP_TARGET_EXIT=$?"
tail -3 ./pip-target.log
PYTHONPATH=./pylibs python3 -m pyfiglet -f small MH 2>&1 | head -6; echo "PYFIGLET_TARGET_EXIT=$?"
echo "--- direct network check ---"
python3 -c "import urllib.request; print(urllib.request.urlopen('https://pypi.org/simple/pyfiglet/', timeout=15).status)" 2>&1; echo "PYPI_HTTP_EXIT=$?"
echo RUNTIME_TARGET_PROBE_DONE
"""

PIP_NATIVE_PROBE = """set +e
echo "PWD=$PWD"
echo "--- pure python package + console script ---"
python3 -m pip install --no-cache-dir --target ./pylibs pyfiglet > ./pip-pure.log 2>&1; echo "PIP_PURE_EXIT=$?"
ls ./pylibs/bin 2>/dev/null
if [ -f ./pylibs/bin/pyfiglet ]; then
  chmod +x ./pylibs/bin/pyfiglet
  head -1 ./pylibs/bin/pyfiglet
  ( exec ./pylibs/bin/pyfiglet -f small MH ) > ./console.log 2>&1; echo "CONSOLE_EXEC_EXIT=$?"
  head -4 ./console.log
fi
echo "--- native python wheel (ujson) ---"
python3 -m pip install --no-cache-dir --target ./pylibs ujson > ./pip-native.log 2>&1; echo "PIP_NATIVE_EXIT=$?"
tail -2 ./pip-native.log
PYTHONPATH=./pylibs python3 -c "import ujson; print('UJSON_IMPORT_OK', ujson.__version__)" 2>&1; echo "UJSON_IMPORT_EXIT=$?"
echo PIP_NATIVE_PROBE_DONE
"""

MMAP_PROBE = """set +e
echo "PWD=$PWD"
cp /bin/busybox ./copied-bx 2>/dev/null
python3 - <<'PY' 2>&1
import ctypes, os
libc = ctypes.CDLL(None, use_errno=True)
libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
libc.mprotect.restype = ctypes.c_int
libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
PROT_READ, PROT_WRITE, PROT_EXEC = 1, 2, 4
MAP_PRIVATE, MAP_SHARED, MAP_ANON = 2, 1, 0x20
def show(label, value, err):
    print(label, 'OK' if err == 0 else 'ERR', value, 'errno', err, os.strerror(err) if err else '')
show('anon_rwx', None, 0) if False else None
ctypes.set_errno(0)
r = libc.mmap(None, 4096, PROT_READ|PROT_WRITE|PROT_EXEC, MAP_PRIVATE|MAP_ANON, -1, 0)
show('anon_rwx', r, ctypes.get_errno())
ctypes.set_errno(0)
r2 = libc.mmap(None, 4096, PROT_READ|PROT_EXEC, MAP_PRIVATE|MAP_ANON, -1, 0)
show('anon_rx', r2, ctypes.get_errno())
ctypes.set_errno(0)
r3 = libc.mmap(None, 4096, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANON, -1, 0)
m = libc.mprotect(r3, 4096, PROT_READ|PROT_EXEC)
show('mprotect_rw_to_rx', m, ctypes.get_errno())
ctypes.set_errno(0)
fd = os.open('/bin/busybox', os.O_RDONLY)
r4 = libc.mmap(None, 4096, PROT_READ|PROT_EXEC, MAP_PRIVATE, fd, 0)
show('bound_file_rx', r4, ctypes.get_errno())
ctypes.set_errno(0)
fd2 = os.open('./copied-bx', os.O_RDONLY)
r5 = libc.mmap(None, 4096, PROT_READ|PROT_EXEC, MAP_PRIVATE, fd2, 0)
show('copied_file_rx', r5, ctypes.get_errno())
ctypes.set_errno(0)
mfd = os.memfd_create('execprobe')
os.write(mfd, b'\\x7fELF' + b'\\x00'*256)
r6 = libc.mmap(None, 4096, PROT_READ|PROT_EXEC, MAP_SHARED, mfd, 0)
show('memfd_rx', r6, ctypes.get_errno())
code = bytes.fromhex('400580d2c0035fd6')
buf = ctypes.create_string_buffer(code, len(code))
ctypes.set_errno(0)
r7 = libc.mmap(None, 4096, PROT_READ|PROT_WRITE|PROT_EXEC, MAP_PRIVATE|MAP_ANON, -1, 0)
if r7 is not None:
    ctypes.memmove(r7, code, len(code))
prot = libc.mprotect(r7, 4096, PROT_READ|PROT_EXEC)
show('code_page_rx', prot, ctypes.get_errno())
if prot == 0:
    fn = ctypes.CFUNCTYPE(ctypes.c_int)(r7)
    try:
        print('EXECUTE_CODE_RESULT', fn())
    except Exception as error:
        print('EXECUTE_CODE_ERROR', repr(error))
else:
    print('EXECUTE_CODE_SKIPPED')
PY
echo MMAP_PROBE_DONE
"""

MH_EXEC_PROBE = """set +e
echo "--- mh-exec availability ---"
ls -l /usr/bin/mh-exec 2>&1
echo "--- download and run a static tool through mh-exec ---"
curl -sSLo ./bb.apk https://dl-cdn.alpinelinux.org/alpine/v3.20/main/aarch64/busybox-static-1.36.1-r31.apk && echo CURL_OK
gzip -dc ./bb.apk > ./bb.tar && echo GZIP_OK
mkdir -p ./bbx && tar -xf ./bb.tar -C ./bbx && echo TAR_OK
ls -l ./bbx/bin/busybox.static
MH_ELF_ARGV0=busybox mh-exec ./bbx/bin/busybox.static echo MH_EXEC_SWITCH_OK
echo MH_EXEC_PROBE_DONE
"""

TRANSPARENT_PROBE = """set +e
echo "--- prepare a downloaded static tool ---"
curl -sSLo ./bb.apk https://dl-cdn.alpinelinux.org/alpine/v3.20/main/aarch64/busybox-static-1.36.1-r31.apk && echo CURL_OK
gzip -dc ./bb.apk > ./bb.tar && echo GZIP_OK
mkdir -p ./tr && tar -xf ./bb.tar -C ./tr && echo TAR_OK
ls -l ./tr/bin/busybox.static
echo "--- transparent direct execution (no mh-exec) ---"
cp ./tr/bin/busybox.static ./tr/bin/busybox
./tr/bin/busybox echo TRANSPARENT_EXEC_OK; echo "TRANSPARENT_EXIT=$?"
./tr/bin/busybox uname -m; echo "UNAME_EXIT=$?"
echo "--- transparent dynamic ELF ---"
curl -sSLo ./dyn.apk https://dl-cdn.alpinelinux.org/alpine/v3.20/main/aarch64/busybox-1.36.1-r31.apk && echo DYN_CURL_OK
gzip -dc ./dyn.apk > ./dyn.tar && mkdir -p ./dynx && tar -xf ./dyn.tar -C ./dynx && echo DYN_TAR_OK
./dynx/bin/busybox echo DYN_TRANSPARENT_OK; echo "DYN_TRANSPARENT_EXIT=$?"
echo "--- signed tool health under the preload ---"
git --version; echo "GIT_EXIT=$?"
node -e "console.log('NODE_OK')"; echo "NODE_EXIT=$?"
curl --version 2>&1 | head -1; echo "CURL_EXIT=$?"
echo TRANSPARENT_PROBE_DONE
"""

INSTALL_PROBE = """set +e
echo "--- install a static tool by name ---"
mh-install busybox https://dl-cdn.alpinelinux.org/alpine/v3.20/main/aarch64/busybox-static-1.36.1-r31.apk bin/busybox.static busybox
echo "MH_INSTALL_EXIT=$?"
ls -l /usr/bin/busybox /usr/lib/mh-tools/busybox/tool 2>&1
echo "--- run by name ---"
busybox echo MH_INSTALL_RUN_OK; echo "RUN_EXIT=$?"
busybox uname -m; echo "UNAME_EXIT=$?"
echo MH_INSTALL_PROBE_DONE
"""

RUNTIME_EVAL_PROBE = """set +e
echo "--- node jitless options ---"
node --v8-options 2>&1 | grep -i -m3 jitless
echo "--- node without NODE_OPTIONS ---"
env -u NODE_OPTIONS node -e "console.log('NODE_NO_JITLESS_OK')" 2>&1; echo "NODE_EXIT=$?"
echo "--- pty support ---"
python3 -c "import pty,os; m,s=pty.openpty(); print('PTY_OK',m,s); os.close(m); os.close(s)" 2>&1; echo "PTY_EXIT=$?"
ls -l /dev/ptmx 2>&1; ls -d /dev/pts 2>&1
echo RUNTIME_EVAL_DONE
"""

DEBUG_EXIT_PROBE = """set +e
export MH_ELF_ARGV0=busybox
TOOL=/usr/lib/mh-tools/busybox/tool
python3 /usr/bin/mh-exec $TOOL echo DIRECT_PY_OK; echo "DIRECT_PY_EXIT=$?"
mh-exec $TOOL echo SCRIPT_OK; echo "SCRIPT_EXIT=$?"
busybox echo SHIM_OK; echo "SHIM_EXIT=$?"
echo ELF_DEBUG_DONE
"""

DYNAMIC_PROBE = """set +e
echo "--- install a dynamically linked static-package tool ---"
mh-install busybox-dyn https://dl-cdn.alpinelinux.org/alpine/v3.20/main/aarch64/busybox-1.36.1-r31.apk bin/busybox busybox
echo "MH_INSTALL_DYN_EXIT=$?"
ls -l /usr/lib/mh-tools/busybox-dyn/tool 2>&1
echo "--- run the dynamic tool ---"
busybox-dyn echo DYN_EXEC_OK; echo "DYN_EXIT=$?"
busybox-dyn uname -m; echo "DYN_UNAME_EXIT=$?"
busybox-dyn --help >/dev/null 2>&1; echo "DYN_HELP_EXIT=$?"
echo DYNAMIC_PROBE_DONE
"""

SHIM_ENV_PROBE = """set +e
echo "LD_PRELOAD=[$LD_PRELOAD]"
ls -l /usr/lib/libmh-exec-shim.so 2>&1
ls -l /usr/bin/mh-exec /usr/bin/python3 2>&1
echo "MH_EXEC_REDIRECT=[$MH_EXEC_REDIRECT]"
echo SHIM_ENV_DONE
"""

SHIM_DEBUG_PROBE = """set +e
echo "LD_PRELOAD=[$LD_PRELOAD]"
echo "--- musl LD_DEBUG=libs on /bin/true ---"
LD_DEBUG=libs /bin/true 2>&1 | head -30
echo "--- musl LD_DEBUG=libs on python3 ---"
LD_DEBUG=libs python3 -c "print('PY_OK')" 2>&1 | head -30
echo SHIM_DEBUG_DONE
"""

TRANSPARENT_MINI = """set +e
curl -fsSLo ./bb.apk https://dl-cdn.alpinelinux.org/alpine/v3.20/main/aarch64/busybox-static-1.36.1-r31.apk && echo MINI_CURL_OK
gzip -dc ./bb.apk > ./bb.tar; mkdir -p ./tr; tar -xf ./bb.tar -C ./tr && cp ./tr/bin/busybox.static ./tr/bin/busybox && echo MINI_TAR_OK
./tr/bin/busybox echo MINI_TRANSPARENT_OK; echo "MINI_EXIT=$?"
echo MINI_PROBE_DONE
"""

NATIVE_OVERLAY_PROBE = """set +e
echo "--- signed libraries present ---"
ls -l /usr/lib/libonig.so.5 /usr/lib/libjq.so.1 /usr/lib/libarchive.so.13 /usr/lib/libpng16.so.16 2>&1
echo "--- dlopen a signed library from python ctypes ---"
python3 -c "import ctypes; ctypes.CDLL('/usr/lib/libarchive.so.13'); print('CTYPES_LIBARCHIVE_OK')" 2>&1; echo "CTYPES_EXIT=$?"
echo "--- load a signed native extension through node dlopen ---"
node -e "console.log('EXTENSION_ANSWER', require('/usr/lib/mh-demo.node').answer())" 2>&1; echo "EXT_EXIT=$?"
echo "--- run a downloaded dynamic tool that needs the new libs (jq) ---"
mh-install jq https://dl-cdn.alpinelinux.org/alpine/v3.22/main/aarch64/jq-1.8.2-r0.apk usr/bin/jq jq
echo "JQ_INSTALL_EXIT=$?"
jq --version 2>&1; echo "JQ_VERSION_EXIT=$?"
echo '{"a":1}' | jq .a 2>&1; echo "JQ_RUN_EXIT=$?"
echo NATIVE_OVERLAY_PROBE_DONE
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


def upload_file(device, relative, payload):
    """Publish a host file through the HDC file channel and copy it into app storage."""
    import tempfile
    from pathlib import Path as _Path
    with tempfile.TemporaryDirectory() as folder:
        local = _Path(folder) / "payload"
        local.write_bytes(payload)
        remote = "/data/local/tmp/mh-elf-loader-" + uuid.uuid4().hex[:8]
        assert "FileTransfer finish" in device.hdc("file", "send", str(local), remote)
        try:
            device.app("cp " + remote + " " + relative)
            size = device.app("wc -c < " + relative).strip()
            if int(size or 0) != len(payload):
                raise AssertionError("uploaded size mismatch: " + size + " vs " + str(len(payload)))
        finally:
            device.hdc("shell", "rm", "-f", remote)


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


def run(device, port, output, probe=None, loader_file=None, payload_file=None, elf_args="", elf_argv0=None):
    name = "proot-exec-" + uuid.uuid4().hex[:8]
    native = FILES + "/alpine/workspace-native/" + name
    probe = probe or PROBE
    kinds = {id(PROBE): "real-device PRoot exec semantics probe",
             id(NATIVE_PROBE): "real-device native execution bypass probe",
             id(BYPASS_PROBE): "real-device runtime native-code bypass probe",
             id(RUNTIME_PROBE): "real-device runtime package acquisition probe",
             id(RUNTIME_TARGET_PROBE): "real-device runtime pure-python install probe",
             id(PIP_NATIVE_PROBE): "real-device python dependency executability probe",
             id(MMAP_PROBE): "real-device executable memory policy probe",
             "elf-loader": "real-device in-memory ELF loader prototype",
             "elf-run": "real-device in-memory static ELF execution",
             "elf-download": "real-device download-and-run static tool",
             "elf-mhexec": "real-device /usr/bin/mh-exec download-and-run",
             "elf-transparent": "real-device transparent downloaded tool execution",
             "elf-install": "real-device install and run a downloaded static tool by name",
             "runtime-eval": "real-device JIT and PTY capability evaluation",
             "elf-debug": "real-device loader exit-status comparison",
             "elf-dynamic": "real-device dynamically linked ELF execution",
             "shim-env": "real-device exec shim environment check",
             "shim-debug": "real-device exec shim loader debug",
             "elf-transparent-mini": "real-device minimal transparent exec",
             "native-overlay": "signed native library and extension overlay"}
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
        if probe == "python3 ./inmemory-elf-runner.py":
            from pathlib import Path as _Path
            runner = _Path("tests/smoke/fixtures/inmemory-elf-runner.py").read_bytes()
            upload_file(device, "alpine/workspace-native/" + name + "/inmemory-elf-runner.py", runner)
            evidence["uploadedLoaderBytes"] = len(runner)
            command = ("set +e; "
                       "curl -sSLo ./bb.apk https://dl-cdn.alpinelinux.org/alpine/v3.20/main/aarch64/busybox-static-1.36.1-r31.apk && echo CURL_OK; "
                       "gzip -dc ./bb.apk > ./bb.tar && echo GZIP_OK; "
                       "mkdir -p ./bbx && tar -xf ./bb.tar -C ./bbx && echo TAR_OK; "
                       "ls -l ./bbx/bin/busybox.static; "
                       "MH_ELF_ARGV0=busybox python3 ./inmemory-elf-runner.py ./bbx/bin/busybox.static echo DOWNLOADED_INMEM_OK; "
                       "echo ELF_DOWNLOAD_PROBE_DONE")
        elif loader_file and not payload_file:
            from pathlib import Path as _Path
            loader = _Path(loader_file).read_bytes()
            upload_file(device, "alpine/workspace-native/" + name + "/elf-loader.py", loader)
            evidence["uploadedLoaderBytes"] = len(loader)
            command = "python3 ./elf-loader.py && echo INMEM_ELF_PROBE_DONE"
        elif payload_file:
            from pathlib import Path as _Path
            runner = _Path("tests/smoke/fixtures/inmemory-elf-runner.py").read_bytes()
            upload_file(device, "alpine/workspace-native/" + name + "/inmemory-elf-runner.py", runner)
            payload = _Path(payload_file).read_bytes()
            upload_file(device, "alpine/workspace-native/" + name + "/guest-tool", payload)
            evidence["uploadedPayloadBytes"] = len(payload)
            prefix = ("MH_ELF_ARGV0=" + elf_argv0 + " ") if elf_argv0 else ""
            command = prefix + "python3 ./inmemory-elf-runner.py ./guest-tool " + elf_args
        else:
            command = probe
        instruction = ("Actually call bash exactly once now with precisely "
                       + json.dumps({"command": command, "description": "Probe PRoot exec semantics"})
                       + ". Use no other tools. Report the result and stop.")
        calls, results, _ = prompt(device, session, instruction)
        evidence["toolCalls"] = calls
        bash_calls = [call for call in calls if call["name"] == "bash"]
        evidence["bashCallCount"] = len(bash_calls)
        if not bash_calls:
            raise AssertionError("The model did not call bash")
        arguments = json.loads(bash_calls[0]["arguments"])
        evidence["commandMatched"] = arguments.get("command") == command
        evidence["command"] = arguments.get("command")
        text = texts(results)
        evidence["resultText"] = text
        markers = {}
        for marker in ("EXEC_SH_OK", "EXEC_BASH_OK", "EXEC_NODE_OK", "EXEC_PY_OK", "EXEC_SCRIPT_OK",
                       "COPY_NODE_OK", "PROOT_EXEC_PROBE_DONE"):
            markers[marker] = marker in text
        # Each probe ends with its own DONE marker (e.g. NATIVE_OVERLAY_PROBE_DONE,
        # SHIM_ENV_DONE); the shared EXEC_* markers only belong to the exec probe.
        done = re.search(r"\b([A-Z][A-Z0-9_]*_DONE)\b", probe)
        expected_done = done.group(1) if done else None
        exits = {}
        for line in text.splitlines():
            if "=" in line and line.split("=", 1)[0].endswith("_EXIT"):
                key, value = line.split("=", 1)
                exits[key] = value.strip()
        evidence["markers"] = markers
        evidence["exits"] = exits
        evidence["ok"] = bool(expected_done) and expected_done in text
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
    parser.add_argument("--probe", choices=["exec", "native", "bypass", "runtime", "runtime-target", "pip-native", "mmap", "elf-loader", "elf-run", "elf-download", "elf-mhexec", "elf-transparent", "elf-install", "runtime-eval", "elf-debug", "elf-dynamic", "shim-env", "shim-debug", "elf-transparent-mini", "native-overlay"], default="exec")
    parser.add_argument("--loader-file", default=str(Path(__file__).with_name("fixtures") / "inmemory-elf-loader.py"))
    parser.add_argument("--payload-file")
    parser.add_argument("--elf-args", default="")
    parser.add_argument("--elf-argv0")
    args = parser.parse_args()
    probe = {"native": NATIVE_PROBE, "bypass": BYPASS_PROBE, "runtime": RUNTIME_PROBE,
             "runtime-target": RUNTIME_TARGET_PROBE, "pip-native": PIP_NATIVE_PROBE,
             "mmap": MMAP_PROBE, "elf-loader": "python3 ./elf-loader.py",
             "elf-download": "python3 ./inmemory-elf-runner.py",
             "elf-mhexec": MH_EXEC_PROBE, "elf-transparent": TRANSPARENT_PROBE,
             "elf-install": INSTALL_PROBE, "runtime-eval": RUNTIME_EVAL_PROBE,
             "elf-debug": DEBUG_EXIT_PROBE, "dynamic": DYNAMIC_PROBE,
             "elf-dynamic": DYNAMIC_PROBE, "shim-env": SHIM_ENV_PROBE,
             "shim-debug": SHIM_DEBUG_PROBE, "elf-transparent-mini": TRANSPARENT_MINI,
             "native-overlay": NATIVE_OVERLAY_PROBE}.get(args.probe, PROBE)
    run(Device(args.target, args.port), args.port, args.output, probe,
        loader_file=(args.loader_file if args.probe == "elf-loader" else None),
        payload_file=(args.payload_file if args.probe == "elf-run" else None),
        elf_args=args.elf_args, elf_argv0=args.elf_argv0)
    print(args.output)


if __name__ == "__main__":
    main()
