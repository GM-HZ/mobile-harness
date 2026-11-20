"""Read-only real-device verification for a HDC-attached HarmonyOS phone.

Unlike the destructive emulator fixtures this script accepts a USB target. It
never changes the profile: it starts the app if needed, then records the device
parameters, installed build, boot state, account state, bundle availability and
the runtime feature probes that do not need a model turn.

    python3 tests/smoke/mate60-verify.py --target <usb-serial> --output out.json
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid

HDC = "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc"
BUNDLE = "org.sayact.nodepoc"
FILES = "data/storage/el2/base/haps/entry/files"
HOST_HEADER = "127.0.0.1:19592"


class Device:
    def __init__(self, target, port):
        self.target = target
        self.url = f"http://127.0.0.1:{port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.device = [HDC, "-t", target]

    def hdc(self, *args):
        return subprocess.check_output(self.device + list(args), text=True, timeout=180).strip()

    def app(self, command):
        return self.hdc("shell", "-b", BUNDLE, "cd " + FILES + " && " + command)

    def start(self):
        return self.hdc("shell", "aa", "start", "-a", "EntryAbility", "-b", BUNDLE)

    def state(self):
        return json.loads(self.app("cat mobile-harness-boot.json"))

    def cookie(self):
        return json.loads(self.app("cat alpine/tmp/dsh-client-native-launch"))["cookie"].split(";", 1)[0]

    def rpc(self, method, args, timeout=30):
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
                    return round((timeout - (deadline - time.monotonic())) * 1000)
            except Exception:
                pass
            time.sleep(1)
        return None


def parameters(device):
    names = ["const.product.model", "const.product.brand", "const.product.name",
             "const.ohos.apiversion", "const.product.software.version", "const.product.devicetype"]
    return {name.split(".")[-1]: device.hdc("shell", "param", "get", name) for name in names}


def installed_build(device):
    raw = device.hdc("shell", "bm dump -n " + BUNDLE)
    start = raw.find("{")
    data = json.loads(raw[start:])
    return {"versionCode": data.get("versionCode"), "versionName": data.get("versionName"),
            "appId": str(data.get("appId", ""))[:40], "installTime": data.get("installTime")}


def battery(device):
    try:
        raw = device.hdc("shell", "hidumper -s 3302 -a -i")
        capacity = re.search(r"capacity: (\d+)", raw)
        return {"capacity": int(capacity.group(1)) if capacity else None}
    except Exception as error:
        return {"error": str(error)[:120]}


def microphone_state(device):
    try:
        raw = device.hdc("shell", "atm dump -t -b " + BUNDLE)
        match = re.search(r"ohos\.permission\.MICROPHONE\s+status:\s*(-?\d+)\s+flag:\s*(-?\d+)", raw)
        return {"status": int(match.group(1)), "flag": int(match.group(2))} if match else {"raw": raw[:200]}
    except Exception as error:
        return {"error": str(error)[:120]}


def run(device, output):
    evidence = {"kind": "real-device read-only verification", "target": device.target,
                "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    device.hdc("fport", "tcp:" + str(device.port), "tcp:19592")
    try:
        evidence["started"] = device.start()
        evidence["readyMs"] = device.ready()
        if evidence["readyMs"] is None:
            raise SystemExit("The app did not become ready")
        evidence["parameters"] = parameters(device)
        evidence["build"] = installed_build(device)
        evidence["state"] = device.state()
        evidence["web"] = device.web_status()
        evidence["storage"] = device.hdc("shell", "df -h /data | tail -1")
        evidence["battery"] = battery(device)
        evidence["microphone"] = microphone_state(device)
        evidence["account"] = device.rpc("account/getState", {})
        bundles = device.rpc("pluginManager/listBundles", {})
        evidence["bundles"] = [{key: row.get(key) for key in ("name", "enabled", "availability", "optional")}
                               for row in bundles]
        evidence["dshVersions"] = sorted({str(row.get("dshVersion")) for row in bundles if row.get("dshVersion")})
        for method, args in [("liveshareShares/list", {}), ("credentials/describe", {})]:
            try:
                evidence[method] = device.rpc(method, args)
            except Exception as error:
                evidence[method] = {"error": str(error)[:160]}
        evidence["ok"] = True
    finally:
        device.hdc("fport", "rm", "tcp:" + str(device.port), "tcp:19592")
        Path(output).write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: evidence[key] for key in ("ok", "readyMs", "web", "account", "build")},
                     ensure_ascii=False, indent=1))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="37R0224115035605")
    parser.add_argument("--port", type=int, default=19670)
    parser.add_argument("--output", type=Path, default=Path(".build/mate60-verify.json"))
    args = parser.parse_args()
    device = Device(args.target, args.port)
    device.port = args.port
    run(device, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
