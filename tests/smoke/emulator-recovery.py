"""Inject a crash-only DSH bundle on an isolated loopback Phone emulator."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import uuid

HDC = os.environ.get("HARMONY_HDC", "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc")
BUNDLE = "org.sayact.nodepoc"
FILES = "/data/storage/el2/base/haps/entry/files"
WORKSPACE = FILES + "/alpine/workspace-native"
PROFILE = "alpine/native-benchmark-home/profiles/web"
HOST_HEADER = "127.0.0.1:19592"


class Emulator:
    def __init__(self, target, port):
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]+", target):
            raise SystemExit("The destructive crash fixture only accepts a loopback emulator target")
        self.device = [HDC, "-t", target]
        self.url = f"http://127.0.0.1:{port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if self.hdc("shell", "param get const.product.devicetype") != "phone":
            raise SystemExit("Expected a Phone emulator")

    def hdc(self, *args):
        return subprocess.check_output(self.device + list(args), text=True, timeout=90).strip()

    def app(self, command):
        return self.hdc("shell", "-b", BUNDLE, "cd data/storage/el2/base/haps/entry/files && " + command)

    def start(self):
        result = self.hdc("shell", "aa", "start", "-a", "EntryAbility", "-b", BUNDLE)
        if "start ability successfully" not in result:
            raise RuntimeError(result)

    def stop(self):
        result = self.hdc("shell", "aa", "force-stop", BUNDLE)
        if "force stop process successfully" not in result:
            raise RuntimeError(result)

    def state(self):
        return json.loads(self.app("cat mobile-harness-boot.json"))

    def cookie(self):
        return json.loads(self.app("cat alpine/tmp/dsh-client-native-launch"))["cookie"].split(";", 1)[0]

    def rpc(self, method, args, timeout=30):
        body = json.dumps({
            "type": "client-request", "rpcId": str(uuid.uuid4()), "method": method,
            "payload": {"args": args},
        }).encode()
        request = urllib.request.Request(self.url + "/api/" + method, body, headers={
            "Content-Type": "application/json", "Host": HOST_HEADER, "Cookie": self.cookie(),
        })
        with self.opener.open(request, timeout=timeout) as response:
            result = json.load(response)["result"]
        if not result["ok"]:
            raise RuntimeError(f"{method}: {result['error']['code']}")
        return result.get("value")

    def web_status(self, authenticated):
        headers = {"Host": HOST_HEADER}
        if authenticated:
            headers["Cookie"] = self.cookie()
        request = urllib.request.Request(self.url + "/", headers=headers)
        try:
            with self.opener.open(request, timeout=2) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def ready(self, mode):
        start = time.monotonic()
        while time.monotonic() - start < 120:
            try:
                if self.state() == {"mode": mode, "pending": False} and self.web_status(True) == 200:
                    return round((time.monotonic() - start) * 1000)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            time.sleep(.25)
        raise RuntimeError(f"{mode} Host did not become ready")


def bundle_archive(archive, name, marker):
    files = {
        "package.json": json.dumps({
            "name": name, "version": "1.0.0", "type": "module", "main": "index.js",
            "files": ["index.js", "cordis.patch.yml"], "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
        }),
        "cordis.patch.yml": f"- insert:\n    - id: {name}\n      name: {name}\n",
        "index.js": (
            "import { appendFileSync } from 'node:fs';\n"
            f"export const name = '{name}';\n"
            f"export function apply() {{ appendFileSync('{marker}', 'loaded\\n'); process.abort(); }}\n"
        ),
    }
    with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as target:
        for filename, contents in files.items():
            payload = contents.encode()
            info = tarfile.TarInfo(filename)
            info.size = len(payload)
            target.addfile(info, io.BytesIO(payload))


def test(emulator, output):
    name = "mobile-harness-crash-" + uuid.uuid4().hex[:10]
    marker = name + ".log"
    remote = f"/data/local/tmp/{name}"
    backup = f"{PROFILE}/{name}.bak"
    lock_backup = backup + '.lock'
    boot_backup = 'mobile-harness-boot.json.' + name
    result = {"fixture": name}
    modified = False
    forwarded = False
    had_lock = False
    def digest(file):
        return hashlib.sha256(base64.b64decode(emulator.app('base64 ' + file))).hexdigest()
    try:
        forward = emulator.hdc("fport", f"tcp:{emulator.url.rsplit(':', 1)[1]}", "tcp:19592")
        assert "Forwardport result:OK" in forward, forward
        forwarded = True
        result["normalReadyMs"] = emulator.ready("normal")
        result["anonymousHttp"] = emulator.web_status(False)
        assert result["anonymousHttp"] == 401
        assert emulator.app(f'cp {PROFILE}/package.json {backup} && cp mobile-harness-boot.json {boot_backup} && printf SAVED') == 'SAVED'
        modified = True
        result['manifestBeforeSha256'] = digest(PROFILE + '/package.json')
        had_lock = emulator.app(f'test -e {PROFILE}/pnpm-lock.yaml && printf PRESENT') == 'PRESENT'
        if had_lock: emulator.app(f'cp {PROFILE}/pnpm-lock.yaml {lock_backup}')
        result['lockBeforeSha256'] = digest(PROFILE + '/pnpm-lock.yaml') if had_lock else None
        workspace = emulator.rpc("workspace/create", {"request": {"path": WORKSPACE}})["workspace"]
        session = emulator.rpc("session/create", {"request": {"workspaceId": workspace["workspaceId"]}})["sessionId"]
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "bundle.tgz"
            bundle_archive(archive, name, marker)
            assert "FileTransfer finish" in emulator.hdc("file", "send", str(archive), remote + ".tgz")
            assert emulator.app(f"mkdir -p alpine/workspace-native/{name} && tar -xzf {remote}.tgz -C alpine/workspace-native/{name} && echo READY") == "READY"
            installed = emulator.rpc("pluginManager/installBundle", {
                "spec": f"file:{WORKSPACE}/{name}", "options": {"enabled": False},
            }, timeout=90)
            result["pluginInstalledDisabled"] = installed.get("enabled") is False
            assert result["pluginInstalledDisabled"]
            emulator.stop()
            profile = json.loads(emulator.app(f"cat {PROFILE}/package.json"))
            bundles = profile["dsh"]["profile"]["bundles"]
            assert name not in bundles
            bundles.append(name)
            modified_profile = Path(temporary) / "package.json"
            modified_profile.write_text(json.dumps(profile) + "\n")
            assert "FileTransfer finish" in emulator.hdc("file", "send", str(modified_profile), remote + ".json")
            assert emulator.app(f"cp {remote}.json {PROFILE}/package.json && echo ACTIVATED") == "ACTIVATED"
        emulator.start()
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            loaded = emulator.app(f"if test -f alpine/workspace-native/{marker}; then cat alpine/workspace-native/{marker}; fi")
            if loaded == "loaded" and not emulator.hdc("shell", "pidof", BUNDLE):
                break
            time.sleep(.25)
        else:
            raise RuntimeError("The installed plugin did not abort the Host")
        result["actualPluginCrash"] = True
        result["interruptedNormalBoot"] = emulator.state()
        assert result["interruptedNormalBoot"] == {"mode": "normal", "pending": True}
        emulator.start()
        result["safeReadyMs"] = emulator.ready("safe")
        result["safeAuthenticatedHttp"] = emulator.web_status(True)
        result["pluginNotLoadedAgain"] = emulator.app(f"cat alpine/workspace-native/{marker}") == "loaded"
        state = emulator.rpc("session/state", {"request": {"sessionId": session}})
        result["sameSessionInSafeMode"] = isinstance(state.get("cursor"), int)
        assert result["pluginNotLoadedAgain"] and result["sameSessionInSafeMode"]
    finally:
        try:
            if modified:
                emulator.stop()
                result["normalProfileRestored"] = emulator.app(
                    f"cp {backup} {PROFILE}/package.json && cmp -s {backup} {PROFILE}/package.json && cp {boot_backup} mobile-harness-boot.json && echo RESTORED"
                ) == "RESTORED"
                assert result["normalProfileRestored"]
                if had_lock: emulator.app(f'cp {lock_backup} {PROFILE}/pnpm-lock.yaml')
                else: emulator.app(f'rm -f {PROFILE}/pnpm-lock.yaml')
                emulator.app(f'rm -rf alpine/workspace-native/{name} {PROFILE}/node_modules/{name}; rm -f alpine/workspace-native/{marker} {backup} {lock_backup} {boot_backup}')
                emulator.start(); result['returnNormalReadyMs'] = emulator.ready('normal')
                result['manifestAfterSha256'] = digest(PROFILE + '/package.json')
                result['lockAfterSha256'] = digest(PROFILE + '/pnpm-lock.yaml') if had_lock else None
                assert result['manifestBeforeSha256'] == result['manifestAfterSha256']
                assert result['lockBeforeSha256'] == result['lockAfterSha256']
        finally:
            emulator.hdc('shell', 'rm', '-f', remote + '.tgz', remote + '.json')
            if forwarded:
                emulator.hdc("fport", "rm", f"tcp:{emulator.url.rsplit(':', 1)[1]}", "tcp:19592")
            output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="loopback Phone emulator HDC target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--port", type=int, default=19633)
    options = parser.parse_args()
    test(Emulator(options.target, options.port), options.output)
