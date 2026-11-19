"""Preflight a public LiveShare Relay before running the device acceptance.

Checks the HTTPS health endpoint, the TLS certificate chain identity and the
WebSocket upgrade path the owner gateway needs. Works against a self-signed
local deployment with ``--insecure`` and against a public CA deployment without
it. Run with ``--self-test`` to validate the checks on a local TLS proxy.
"""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

SMOKE = Path(__file__).resolve().parent
HDC_HINT = os.environ.get("HARMONY_HDC", "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc")
DEVECO = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents"))


def node_binary():
    return DEVECO / "tools/node/bin/node"


def ws_module():
    import runpy
    return runpy.run_path(str(SMOKE / "emulator-ptc-approval.py"))["ws_module"]()


def certificate_text(der):
    pem = ssl.DER_cert_to_PEM_cert(der).encode()
    output = subprocess.run(["openssl", "x509", "-noout", "-subject", "-issuer", "-dates", "-ext", "subjectAltName"],
                            input=pem, capture_output=True)
    return output.stdout.decode(errors="replace")


def parse_certificate(text):
    result = {}
    for key, name in (("subject", "subject"), ("issuer", "issuer"), ("notBefore", "notBefore"),
                      ("notAfter", "notAfter")):
        match = re.search(key + r"=\s*(.+)", text)
        if match:
            result[name] = match.group(1).strip()
    san = re.search(r"X509v3 Subject Alternative Name:\s*\n\s*(.+)", text)
    if san:
        result["subjectAltName"] = san.group(1).strip()
    return result


def tls_probe(host, port, insecure):
    context = ssl.create_default_context()
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    result = {"verified": False, "insecure": insecure}
    try:
        return _tls_probe(host, port, context, result)
    except OSError as error:
        result["error"] = str(error)[:300]
        return result


def _tls_probe(host, port, context, result):
    with socket.create_connection((host, port), timeout=8) as raw:
        try:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
                result.update({"verified": True, "protocol": tls.version(), "cipher": tls.cipher()[0]})
        except ssl.SSLCertVerificationError as error:
            result["verifyError"] = error.verify_message
            # Reconnect without verification only to report the certificate identity.
            fallback = ssl._create_unverified_context()
            with socket.create_connection((host, port), timeout=8) as raw2:
                with fallback.wrap_socket(raw2, server_hostname=host) as tls:
                    der = tls.getpeercert(binary_form=True)
                    result.update({"protocol": tls.version()})
    if der:
        result.update(parse_certificate(certificate_text(der)))
    return result


def http_health(url, insecure):
    path = url.rstrip("/") + "/health"
    if insecure:
        context = ssl._create_unverified_context()
    else:
        context = ssl.create_default_context()
    handler = urllib.request.HTTPSHandler(context=context)
    opener = urllib.request.build_opener(handler, urllib.request.ProxyHandler({}))
    try:
        request = urllib.request.Request(path, headers={"accept": "application/json"})
        with opener.open(request, timeout=10) as response:
            body = response.read(2048).decode(errors="replace")
            return {"status": response.status, "body": body[:400]}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "body": error.read(512).decode(errors="replace")[:400]}
    except Exception as error:
        return {"status": None, "error": str(error)[:300]}


def wss_probe(url, insecure):
    parsed = urlsplit(url)
    target = f"wss://{parsed.netloc}/__tunnel_gateway__?shareId=preflight&sessionMode=view"
    payload = {"url": target, "rejectUnauthorized": not insecure, "timeout": 9000, "headers": {}}
    try:
        output = subprocess.check_output([str(node_binary()), str(SMOKE / "fixtures/wss-probe.cjs"), str(ws_module())],
                                         input=json.dumps(payload), text=True, timeout=20)
        return json.loads(output)
    except subprocess.CalledProcessError as error:
        return {"outcome": "probe-failed", "message": str(error)[:300]}


def preflight(url, insecure=False):
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise SystemExit("A public Relay preflight requires an https URL")
    host = parsed.hostname
    port = parsed.port or 443
    result = {"url": url, "host": host, "port": port, "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    result["tls"] = tls_probe(host, port, insecure)
    result["health"] = http_health(url, insecure)
    result["wss"] = wss_probe(url, insecure)
    failures = []
    if not result["tls"].get("verified") and not insecure:
        failures.append("tls-verification:" + str(result["tls"].get("verifyError")))
    if result["health"].get("status") != 200:
        failures.append("health-status:" + str(result["health"].get("status")))
    wss = result["wss"]
    if wss.get("outcome") != "http" or wss.get("status") not in (401, 403):
        failures.append("wss-anonymous-handling:" + repr({k: wss.get(k) for k in ("outcome", "status")}))
    result["failures"] = failures
    result["ok"] = not failures
    return result


def self_test(output):
    cert = Path(tempfile.mkdtemp(prefix="mh-relay-cert-"))
    key, pem = cert / "relay.key", cert / "relay.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
                    "-keyout", str(key), "-out", str(pem)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    relay = subprocess.Popen([str(node_binary()), str(SMOKE / "fixtures/liveshare-relay.cjs"), str(ws_module())],
                             stdout=subprocess.PIPE, text=True)
    proxy = None
    evidence = {}
    try:
        relay_port = int(relay.stdout.readline())
        proxy = subprocess.Popen([str(node_binary()), str(SMOKE / "fixtures/relay-tls-proxy.cjs"),
                                  str(pem), str(key), str(relay_port)], stdout=subprocess.PIPE, text=True)
        proxy_port = int(proxy.stdout.readline())
        local = f"https://127.0.0.1:{proxy_port}"
        evidence["insecureLocalProxy"] = preflight(local, insecure=True)
        evidence["verifiedSelfSigned"] = preflight(local, insecure=False)
        evidence["refused"] = preflight("https://127.0.0.1:1", insecure=True)
        assert evidence["insecureLocalProxy"]["ok"] is True, evidence["insecureLocalProxy"]
        assert evidence["verifiedSelfSigned"]["ok"] is False, evidence["verifiedSelfSigned"]
        assert evidence["refused"]["ok"] is False, evidence["refused"]
        evidence["relayPort"] = relay_port
        evidence["proxyPort"] = proxy_port
    finally:
        if proxy:
            proxy.terminate()
            proxy.wait(timeout=5)
        relay.terminate()
        relay.wait(timeout=5)
        for path in (key, pem):
            path.unlink(missing_ok=True)
        cert.rmdir()
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"ok": all([evidence["insecureLocalProxy"]["ok"],
                                 not evidence["verifiedSelfSigned"]["ok"],
                                 not evidence["refused"]["ok"]])}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--insecure", action="store_true", help="Accept a self-signed certificate (local validation)")
    parser.add_argument("--self-test", action="store_true", help="Validate the checks against a local TLS proxy")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test(args.output or Path(".build/relay-preflight-self-test.json"))
        sys.exit(0)
    if not args.url:
        parser.error("url is required unless --self-test is used")
    result = preflight(args.url, args.insecure)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(0 if result["ok"] else 1)
