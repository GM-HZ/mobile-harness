import filecmp
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from zipfile import ZipFile

from harmonyos_dsh import stage_dsh
from harmonyos_guest_extras import stage_guest_extras

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
    for name in ("poc.c", "nativehost.c", "guest-tools.inc"):
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
    stage_dsh(ROOT, RAW, inputs / "entry/src/main/resources/rawfile/dsh-layer.zip")
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
