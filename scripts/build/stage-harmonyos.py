import filecmp
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from urllib.parse import quote

import harmonyos_appgallery as appgallery
from harmonyos_dsh import stage_dsh
from harmonyos_guest_extras import stage_guest_extras
from harmonyos_ptc import PORTABLE_ASSETS, portable_assets
from harmonyos_http import stage_http
from harmonyos_speech import stage_speech
from harmonyos_workspace_deps import stage_workspace_dependencies

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/harmonyos"
RUNTIME = ROOT / "runtime/harmonyos"
EXPERIMENTAL = os.environ.get("HARMONY_EXPERIMENTAL_HOST_PROCESS") == "1"
SELF_BUILD = os.environ.get("HARMONY_SELF_BUILD") == "1"
APPGALLERY = os.environ.get("HARMONY_APPGALLERY_BUILD") == "1"
STAGE = ROOT / ".build/stage" / (
    "harmonyos-appgallery" if APPGALLERY else "harmonyos-process-probe" if EXPERIMENTAL else "harmonyos"
)
RAW = STAGE / "entry/src/main/resources/rawfile"
CPP = STAGE / "entry/src/main/cpp"


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


def layer_member(name):
    for path in sorted(RAW.glob("dsh-layer-[0-9]*.zip")):
        with ZipFile(path) as layer:
            if name in layer.namelist():
                return layer.read(name)
    raise SystemExit(f"Missing dsh layer member: {name}")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_assets(inputs, allowed=None):
    for row in (ROOT / "docs/build-inputs.sha256").read_text().splitlines():
        checksum, filename = row.split(maxsplit=1)
        relative = PurePosixPath(filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit(f"Invalid input path: {filename}")
        if allowed is not None and relative.name not in allowed:
            continue
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
    path = "dsh/node_modules/@deepseek-ai/dsh-ptc-runtime-node/lib/process.js"
    bundled = layer_member(path)
    if hashlib.sha256(bundled).hexdigest() != "c01308c52fc52d5f13edd2b65008f3bbcf67bd753eb17af5e4bc023216eca6b4":
        raise SystemExit("Expected the locked DSH PTC bootstrap")
    entry = "runNodeMain(openInheritedControlChannel(), Number(process.argv[2]), process);"
    if bundled.decode("utf8").count(entry) != 1:
        raise SystemExit("Unexpected pinned PTC bootstrap entry")
    overlay = (RUNTIME / "templates/ptc-worker.mjs").read_text()
    worker.write_text(bundled.decode("utf8").replace(entry, overlay, 1))
    node = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents")) / "tools/node/bin/node"
    subprocess.run([str(node), "--check", str(worker)], check=True)


def stage_signing_profile():
    signing_profile = os.environ.get("HARMONY_SIGNING_PROFILE")
    profile = Path(signing_profile or ROOT / "build-profile.json5")
    unsigned = APPGALLERY or os.environ.get("HARMONY_UNSIGNED") == "1"
    if signing_profile and not unsigned and not EXPERIMENTAL and not profile.is_file():
        raise SystemExit(f"HarmonyOS signing profile not found: {profile}")
    if EXPERIMENTAL or unsigned or not profile.is_file():
        profile = APP / "build-profile.example.json5"
    signing = STAGE / "build-profile.json5"
    signing.unlink(missing_ok=True)
    copy(profile, signing)
    signing.chmod(0o600)
    print(f"Prepared HarmonyOS project: {STAGE}")


def stage_appgallery(inputs):
    stage_assets(inputs, appgallery.PINNED_INPUTS)
    bundle = os.environ.get("HARMONY_APPGALLERY_BUNDLE", "")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+", bundle):
        raise ValueError("Invalid HARMONY_APPGALLERY_BUNDLE")
    app_config = STAGE / "AppScope/app.json5"
    config = json.loads(app_config.read_text())
    config["app"]["bundleName"] = bundle
    config["app"]["vendor"] = "Mobile Harness"
    appgallery.set_appgallery_version(config["app"])
    app_config.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    for directory in (STAGE / "AppScope", STAGE / "entry/src/main"):
        strings = directory / "resources/base/element/string.json"
        config = json.loads(strings.read_text())
        for item in config["string"]:
            if item["name"] == "app_name":
                item["value"] = "DSH-MH"
        strings.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    module_config = STAGE / "entry/src/main/module.json5"
    config = json.loads(module_config.read_text())
    for ability in config["module"]["abilities"]:
        ability.pop("backgroundModes", None)
    disabled_permissions = {"ohos.permission.KEEP_BACKGROUND_RUNNING", "ohos.permission.RUNNING_LOCK"}
    config["module"]["requestPermissions"] = [
        permission for permission in config["module"]["requestPermissions"]
        if permission["name"] not in disabled_permissions
    ]
    module_config.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    cmake = CPP / "CMakeLists.txt"
    cmake.write_text("set(MOBILE_HARNESS_APPGALLERY ON)\n" + cmake.read_text())
    appgallery.stage_appgallery_url(RAW, "HARMONY_APPGALLERY_PRIVACY_URL", "appgallery-privacy-url")
    appgallery.stage_appgallery_url(RAW, "HARMONY_APPGALLERY_SOURCE_URL", "appgallery-source-url")
    for name in ("dsh", "node"):
        copy(ROOT / "vendor/repos" / name / "LICENSE", RAW / f"LICENSE.{name}.txt")
    with TemporaryDirectory(prefix="prepare-appgallery-", dir=STAGE) as directory:
        full_layer = Path(directory)
        stage_dsh(ROOT, full_layer, inputs / "entry/src/main/resources/rawfile/dsh-layer.zip")
        stage_http(ROOT, full_layer)
        for name in ("dsh-harmony-llhttp.cjs", "LICENSE.llhttp.txt", "LICENSE.undici.txt"):
            copy(full_layer / name, RAW / name)
        appgallery.stage_layer(ROOT, full_layer, RAW)
    libraries = STAGE / "entry/libs/arm64-v8a"
    appgallery.stage_appgallery_image(ROOT, libraries)
    appgallery.stage_appgallery_search(ROOT, libraries, RAW)
    stage_signing_profile()


def main():
    if APPGALLERY and (EXPERIMENTAL or SELF_BUILD):
        raise ValueError("AppGallery is a separate build variant")
    if APPGALLERY:
        # The AppGallery stage is isolated and all rawfiles and native libraries
        # are regenerated. Prevent earlier stages from leaking guest assets.
        for directory in (RAW, STAGE / "entry/libs/arm64-v8a"):
            for generated in directory.glob("*"):
                if generated.is_file():
                    generated.unlink()
    inputs = Path(os.environ.get("HARMONY_INPUTS_DIR") or ROOT / ".build/inputs/harmonyos").resolve()
    for source in files_from_index(APP):
        if not APPGALLERY or source.name != "alpine-release":
            copy(source, STAGE / source.relative_to(APP))
    for directory in (ROOT / "packages/dsh-host", ROOT / "packages/bundles/mobile",
                      RUNTIME / "compat", RUNTIME / "diagnostics"):
        for source in sorted(directory.iterdir()):
            if source.is_file() and (
                source.name in appgallery.HOST_FILES if APPGALLERY else source.name not in appgallery.APPGALLERY_ONLY
            ):
                copy(source, RAW / source.name)
    dshm = ROOT / "vendor/repos/dshm"
    copy(dshm / "hostcore/app/fetch-shim.js", RAW / "fetch-shim.cjs")
    copy(dshm / "LICENSE", RAW / "LICENSE.dshm.txt")
    for name in ("poc.c", "nativehost.c", "child-descriptors.h", "guest-tools.inc", "workflow-broker.c", "workflow-broker.h",
                 "ptc-supervisor.c", "ptc-supervisor.h", "ptc-file-filter.c", "ptc-file-filter.h"):
        copy(RUNTIME / "native" / name, CPP / name)
    if APPGALLERY:
        stage_appgallery(inputs)
        return
    stage_workflow_worker()
    if EXPERIMENTAL:
        app_config = STAGE / "AppScope/app.json5"
        source = (APP / "AppScope/app.json5").read_text()
        app_config.write_text(source.replace("org.sayact.nodepoc", "org.mobileharness.processprobe"))
        cmake = CPP / "CMakeLists.txt"
        with cmake.open("a") as stream:
            stream.write("\ntarget_compile_definitions(poc PRIVATE MOBILE_HARNESS_EXPERIMENTAL_FORK=1)\n")
    if SELF_BUILD:
        os.environ.setdefault("HARMONY_GUEST_LIB_GROUPS", "common,media,extensions")
    stage_assets(inputs)

    stage_speech(ROOT, STAGE, RAW)
    subprocess.run(
        ["bash", str(RUNTIME / "packaging/build-native-shell.sh")],
        env={**os.environ, "HARMONY_STAGE": str(STAGE)}, check=True
    )
    stage_guest_extras(ROOT, STAGE, RAW)
    stage_workspace_dependencies(ROOT, RAW)
    # Exact native launcher overlay paths, rather than a second manually kept
    # executable list. Harmony's signed loader can execute these while POSIX
    # X_OK returns false for the app UID on owner-executable package libraries.
    bindings = "\n".join((CPP / name).read_text() for name in ("poc.c", "guest-tools.inc", "guest-libs.inc"))
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
    if SELF_BUILD:
        cmake = CPP / "CMakeLists.txt"
        with cmake.open("a") as stream:
            stream.write("\ntarget_compile_definitions(poc PRIVATE MH_SELF_BUILD=1)\n")
    # The stage is reused across builds and branches. Discard overlays removed
    # from the v1 source tree before packing the HAP.
    for name in appgallery.APPGALLERY_ONLY | {"dsh-layer.zip", "dsh-settings-client.js", "dsh-harmony-remote-ssh.cjs"}:
        (RAW / name).unlink(missing_ok=True)
    (RAW / "dsh-self-build.json").write_text(json.dumps({
        "selfBuild": SELF_BUILD,
        "signedExecBypass": SELF_BUILD,
        "note": "Self-built HAPs include the in-memory ELF runner at /usr/bin/mh-exec; store builds never include it.",
    }) + "\n")
    loader = RAW / "mh-exec.py"
    installer = RAW / "mh-install.py"
    if SELF_BUILD:
        copy(RUNTIME / "tools" / "mh-exec.py", loader)
        copy(RUNTIME / "tools" / "mh-install.py", installer)
    else:
        loader.unlink(missing_ok=True)
        installer.unlink(missing_ok=True)
    print(f"Self-build signed-exec bypass: {'enabled' if SELF_BUILD else 'disabled'}")
    stage_signing_profile()


if __name__ == "__main__":
    main()
