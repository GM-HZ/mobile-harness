"""Stage the pinned Android application and verified ARM64 runtime."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "vendor/repos/dsh-go"
STAGE = ROOT / ".build/stage/android"
LOCK = json.loads((ROOT / "runtime/android/release-lock.json").read_text())
APP_ID = "org.mobileharness.android"
UPSTREAM_ID = "io.github.ccch1mneyyy.dsh_app"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def replace(path, old, new, count=1):
    source = path.read_text()
    if source.count(old) != count:
        raise SystemExit(f"Android overlay no longer matches upstream: {path.name}")
    path.write_text(source.replace(old, new))


def apply_product_identity(destination):
    app = destination / "app"
    module = app / "android/app"
    replace(module / "build.gradle.kts",
            f'applicationId = "{UPSTREAM_ID}"', f'applicationId = "{APP_ID}"')
    main = module / "src/main"
    replace(main / "AndroidManifest.xml", 'android:label="DSH Go"', 'android:label="Mobile Harness"')
    replace(app / "lib/state/app_info.dart", "static const name = 'DSH Go';",
            "static const name = 'Mobile Harness';")
    replace(main / "res/xml/shortcuts.xml",
            f'android:targetPackage="{UPSTREAM_ID}"', f'android:targetPackage="{APP_ID}"', count=2)

    # These constants represent the installed package. The Kotlin class namespace stays upstream.
    phone = main / "kotlin" / UPSTREAM_ID.replace(".", "/") / "phone"
    replace(phone / "SafetyGate.kt", f'OWN_PACKAGE = "{UPSTREAM_ID}"', f'OWN_PACKAGE = "{APP_ID}"')
    replace(phone / "background/PrivilegedProtocol.kt",
            f'APP_PACKAGE = "{UPSTREAM_ID}"', f'APP_PACKAGE = "{APP_ID}"')
    for locale, label in (("values", "DSH Phone Control"), ("values-zh", "DSH 手机操控")):
        replace(main / f"res/{locale}/phone_a11y_strings.xml", f">{label}<", ">Mobile Harness Phone Use<")

    # This build has its own package and signing key. Upstream update offers are inapplicable.
    replace(app / "lib/state/update_state.dart", "(ref) => defaultUpdateSources()",
            "(ref) => const UpdateSources(useGithubApi: false, mirrors: [])")
    stats = app / "lib/usage/usage_stats.dart"
    replace(stats, "this.enabled = true, this.noticed", "this.enabled = false, this.noticed")
    replace(stats, "prefs.getBool(enabledKey) ?? true", "prefs.getBool(enabledKey) ?? false")

    wrapper = app / "android/gradle/wrapper/gradle-wrapper.properties"
    replace(wrapper, "mirrors.cloud.tencent.com/gradle/", "services.gradle.org/distributions/")


def stage_source(destination):
    with subprocess.Popen(
        ["git", "-C", str(UPSTREAM), "archive", LOCK["commit"]], stdout=subprocess.PIPE
    ) as archive:
        with archive.stdout:
            subprocess.run(["tar", "-xf", "-", "-C", str(destination)], stdin=archive.stdout, check=True)
        if archive.wait():
            raise SystemExit("Could not archive the pinned dsh-Go source")
    patch_dir = ROOT / "runtime/android/patches"
    # The archive has no .git. Stop discovery at its parent so git apply treats paths
    # as relative to the staged archive instead of skipping them under the main checkout.
    patch_env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(destination.parent)}
    for name in (
        "background-input-probe.patch",
        "foreground-swipe.patch",
        "ssh-first-trust.patch",
        "background-android-version.patch",
        "foreground-root-retry.patch",
        "onboarding-default-model.patch",
    ):
        subprocess.run(["git", "apply", str(patch_dir / name)], cwd=destination, env=patch_env, check=True)
    apply_product_identity(destination)


def stage_runtime(apk, destination):
    abi = LOCK["abi"]
    manifest_path = "assets/runtime/manifest.json"
    out = destination / "runtime/out" / abi
    with ZipFile(apk) as source:
        manifest = json.loads(source.read(manifest_path))
        rootfs = f"rootfs-{abi}.tar.xz"
        if manifest["abi"] != abi or manifest["rootfs"] != rootfs:
            raise SystemExit("Android runtime manifest does not match the locked ABI")

        def extract(member, relative, expected=None):
            path = out / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open(member) as data, path.open("wb") as target:
                shutil.copyfileobj(data, target)
            if expected is not None and digest(path) != expected:
                raise SystemExit(f"Android runtime hash mismatch: {member}")

        extract(manifest_path, manifest_path)
        extract(f"assets/runtime/{rootfs}", f"assets/runtime/{rootfs}", manifest["rootfsSha256"])
        for name in ("proot-COPYING.txt", "libtalloc-notice.txt", "libandroid-shmem-copyright.txt"):
            member = f"assets/runtime/licenses/{name}"
            extract(member, member)
        for name in ("libproot.so", "libproot-loader.so", "libtalloc.so", "libandroid-shmem.so"):
            extract(f"lib/{abi}/{name}", f"jniLibs/{abi}/{name}", manifest["jniLibs"][name]["sha256"])
    print(f"Verified Android runtime {manifest['runtimeVersion']}")


def main():
    source_pin = subprocess.check_output(["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True).strip()
    if not (UPSTREAM / ".git").is_file() or source_pin != LOCK["commit"]:
        raise SystemExit("Run git submodule update --init vendor/repos/dsh-go to restore the Android source pin")
    default_apk = ROOT / ".build/inputs/android" / LOCK["apk"]
    apk = Path(os.environ.get("ANDROID_RUNTIME_APK", default_apk)).resolve()
    if not apk.is_file():
        raise SystemExit(f"Download the locked {LOCK['tag']} ARM64 APK to {apk}. See docs/android.md.")
    if digest(apk) != LOCK["sha256"]:
        raise SystemExit(f"Android runtime source APK hash mismatch: {apk}")

    STAGE.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="android-", dir=STAGE.parent) as temporary:
        destination = Path(temporary) / "project"
        destination.mkdir()
        stage_source(destination)
        stage_runtime(apk, destination)
        if STAGE.exists():
            shutil.rmtree(STAGE)
        destination.rename(STAGE)
    print(f"Prepared Android project: {STAGE}")


if __name__ == "__main__":
    main()
