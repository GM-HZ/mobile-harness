import filecmp
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from zipfile import ZipFile
from urllib.parse import quote

from harmonyos_dsh import stage_dsh
from harmonyos_guest_extras import stage_guest_extras
from harmonyos_ptc import PORTABLE_ASSETS, portable_assets
from harmonyos_http import stage_http

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/harmonyos"
RUNTIME = ROOT / "runtime/harmonyos"
EXPERIMENTAL = os.environ.get("HARMONY_EXPERIMENTAL_HOST_PROCESS") == "1"
STAGE = ROOT / ".build/stage" / ("harmonyos-process-probe" if EXPERIMENTAL else "harmonyos")
RAW = STAGE / "entry/src/main/resources/rawfile"
CPP = STAGE / "entry/src/main/cpp"
SETTINGS_CLIENT = "dsh/node_modules/@deepseek-ai/dsh-client-ui-settings-general/lib/client.js"


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file() or not (
        source.stat().st_size == destination.stat().st_size
        and filecmp.cmp(source, destination, shallow=False)
    ):
        shutil.copy2(source, destination)


def files_from_index(directory):
    listed = subprocess.check_output(
        ["git", "ls-files", "-z", "--", str(directory.relative_to(ROOT))], cwd=ROOT
    )
    return [ROOT / os.fsdecode(name) for name in listed.split(b"\0") if name]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_assets(inputs):
    for row in (ROOT / "docs/build-inputs.sha256").read_text().splitlines():
        checksum, filename = row.split(maxsplit=1)
        relative = PurePosixPath(filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit(f"Invalid input path: {filename}")
        source = inputs / relative
        if not source.is_file():
            raise SystemExit(f"Missing pinned HarmonyOS input: {source}")
        if sha256(source) != checksum:
            raise SystemExit(f"HarmonyOS input checksum mismatch: {filename}")
        if relative.name in {"dsh-layer.zip", "dsh-startup-sources.gz"}:
            continue
        destination = STAGE / relative
        # Generated input bytes may change while size and timestamps match.
        if destination.is_file() and sha256(destination) == checksum:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def stage_settings_client():
    # Keep the pinned DSH layer intact. Only overlay its settings client at launch.
    with ZipFile(RAW / "dsh-layer.zip") as layer:
        source = layer.read(SETTINGS_CLIENT).decode("utf-8")
    entry = "function apply(ctx){"
    if source.count(entry) != 1:
        raise SystemExit("The pinned DSH General Settings entry point changed")
    row = (RUNTIME / "web/settings-recovery.js").read_text().rstrip()
    injection = "\n" + row + "\n" + entry + "\n\t\t\tregisterMobileHarnessRecovery(ctx);"
    (RAW / "dsh-settings-client.js").write_text(source.replace(entry, injection, 1), encoding="utf-8")

def stage_workflow_worker():
    source = ROOT / "vendor/repos/dsh/packages/workflow/workflow-ptc/src/guest-source.ts"
    declaration = "export const WORKFLOW_GUEST_SOURCE = "
    _, exported = source.read_text().split(declaration)
    guest_url = "data:text/javascript," + quote(json.loads(exported), safe="")
    worker = RAW / "dsh-harmony-workflow-worker.cjs"
    contents = worker.read_text()
    if contents.count("PACKAGED_WORKFLOW_GUEST_URL") != 1:
        raise SystemExit("Unexpected Workflow worker template")
    worker.write_text(contents.replace("PACKAGED_WORKFLOW_GUEST_URL", json.dumps(guest_url)), encoding="utf-8")


def stage_ptc_worker():
    assets = portable_assets()
    (RAW / "dsh-harmony-ptc-enabled").write_text("1")
    worker = RAW / "dsh-harmony-ptc-worker.mjs"
    for name in PORTABLE_ASSETS:
        copy(assets / name, RAW / name)
    copy(ROOT / "vendor/repos/node/deps/amaro/LICENSE.md", RAW / "LICENSE.amaro.txt")
    with ZipFile(RAW / "dsh-layer.zip") as layer:
        path = "dsh/node_modules/@deepseek-ai/dsh-ptc-runtime-node/lib/process.js"
        bundled = layer.read(path)
    if hashlib.sha256(bundled).hexdigest() != "c01308c52fc52d5f13edd2b65008f3bbcf67bd753eb17af5e4bc023216eca6b4":
        raise SystemExit("Expected the locked DSH PTC bootstrap")
    entry = "runNodeMain(openInheritedControlChannel(), Number(process.argv[2]), process);"
    if bundled.decode("utf8").count(entry) != 1:
        raise SystemExit("Unexpected pinned PTC bootstrap entry")
    overlay = (RUNTIME / "templates/ptc-worker.mjs").read_text()
    worker.write_text(bundled.decode("utf8").replace(entry, overlay, 1))
    node = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents")) / "tools/node/bin/node"
    subprocess.run([str(node), "--check", str(worker)], check=True)


def main():
    inputs = Path(os.environ.get("HARMONY_INPUTS_DIR") or ROOT / ".build/inputs/harmonyos").resolve()
    for source in files_from_index(APP):
        copy(source, STAGE / source.relative_to(APP))
    for directory in (ROOT / "packages/dsh-host", ROOT / "packages/bundles/mobile",
                      RUNTIME / "compat", RUNTIME / "diagnostics"):
        for source in sorted(directory.iterdir()):
            if source.is_file():
                copy(source, RAW / source.name)
    dshm = ROOT / "vendor/repos/dshm"
    copy(dshm / "hostcore/app/fetch-shim.js", RAW / "fetch-shim.cjs")
    copy(dshm / "LICENSE", RAW / "LICENSE.dshm.txt")
    stage_workflow_worker()
    for name in ("poc.c", "nativehost.c", "guest-tools.inc", "workflow-broker.c", "workflow-broker.h",
                 "ptc-supervisor.c", "ptc-supervisor.h", "ptc-file-filter.c", "ptc-file-filter.h"):
        copy(RUNTIME / "native" / name, CPP / name)
    if EXPERIMENTAL:
        app_config = STAGE / "AppScope/app.json5"
        source = (APP / "AppScope/app.json5").read_text()
        app_config.write_text(source.replace("org.sayact.nodepoc", "org.mobileharness.processprobe"))
        cmake = CPP / "CMakeLists.txt"
        with cmake.open("a") as stream:
            stream.write("\ntarget_compile_definitions(poc PRIVATE MOBILE_HARNESS_EXPERIMENTAL_FORK=1)\n")
    stage_assets(inputs)
    subprocess.run(
        ["bash", str(RUNTIME / "packaging/build-native-shell.sh")],
        env={**os.environ, "HARMONY_STAGE": str(STAGE)}, check=True
    )
    stage_guest_extras(ROOT, STAGE, RAW)
    # Exact native launcher overlay paths, rather than a second manually kept
    # executable list. Harmony's signed loader can execute these while POSIX
    # X_OK returns false for the app UID on owner-executable package libraries.
    bindings = (CPP / "poc.c").read_text() + (CPP / "guest-tools.inc").read_text()
    programs = sorted({guest for guest in re.findall(r'\{\s*"libguest_[^"]+",\s*"([^"]+)"\s*\}', bindings)
                       if re.match(r'^/(?:usr/)?s?bin/', guest) and not guest.endswith(('.node', '.so'))})
    if not {'/bin/node', '/bin/bash', '/usr/bin/git'} <= set(programs):
        raise SystemExit("Missing signed subprocess executable overlays")
    (RAW / "dsh-harmony-signed-programs.json").write_text(json.dumps(programs) + "\n")
    stage_dsh(ROOT, RAW, inputs / "entry/src/main/resources/rawfile/dsh-layer.zip")
    stage_ptc_worker()
    stage_http(ROOT, RAW)
    subprocess.run(
        ["python3", str(RUNTIME / "packaging/build-startup-sources.py")],
        env={**os.environ, "HARMONY_STAGE": str(STAGE)}, check=True
    )
    stage_settings_client()
    signing_profile = os.environ.get("HARMONY_SIGNING_PROFILE")
    profile = Path(signing_profile or ROOT / "build-profile.json5")
    unsigned = os.environ.get("HARMONY_UNSIGNED") == "1"
    if signing_profile and not unsigned and not EXPERIMENTAL and not profile.is_file():
        raise SystemExit(f"HarmonyOS signing profile not found: {profile}")
    if EXPERIMENTAL or unsigned or not profile.is_file():
        profile = APP / "build-profile.example.json5"
    signing = STAGE / "build-profile.json5"
    signing.unlink(missing_ok=True)
    copy(profile, signing)
    signing.chmod(0o600)
    print(f"Prepared HarmonyOS project: {STAGE}")


if __name__ == "__main__":
    main()
