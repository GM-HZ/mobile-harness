import filecmp
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from html.parser import HTMLParser
from urllib.parse import urlsplit
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/harmonyos"
RUNTIME = ROOT / "runtime/harmonyos"
EXPERIMENTAL = os.environ.get("HARMONY_EXPERIMENTAL_HOST_PROCESS") == "1"
APPGALLERY = os.environ.get("HARMONY_APPGALLERY_BUILD") == "1"
STAGE = ROOT / ".build/stage" / (
    "harmonyos-appgallery" if APPGALLERY else "harmonyos-process-probe" if EXPERIMENTAL else "harmonyos"
)
RAW = STAGE / "entry/src/main/resources/rawfile"
CPP = STAGE / "entry/src/main/cpp"
SETTINGS_CLIENT = "dsh/node_modules/@deepseek-ai/dsh-client-ui-settings-general/lib/client.js"
CHAT_CLIENT = "dsh/node_modules/@deepseek-ai/dsh-client-ui-chat/lib/client.js"
MODELS_CLIENT = "dsh/node_modules/@deepseek-ai/dsh-client-ui-settings-models/lib/client.js"


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
    entry = "\n\t\tfunction apply(ctx) {"
    if source.count(entry) != 1:
        raise SystemExit("The pinned DSH General Settings entry point changed")
    row = (RUNTIME / "web/settings-recovery.js").read_text().rstrip()
    appgallery = "true" if APPGALLERY else "false"
    injection = f"\n{row}\n{entry}\n\t\t\tregisterMobileHarnessSettings(ctx, {appgallery});"
    (RAW / "dsh-settings-client.js").write_text(source.replace(entry, injection, 1), encoding="utf-8")


def stage_appgallery_chat():
    with ZipFile(RAW / "dsh-layer.zip") as layer:
        source = layer.read(CHAT_CLIENT).decode("utf-8")
    position = source.index('function AssistantMarkdown(')
    entry = "\t\t\tconst rendered = [];"
    index = source.index(entry, position)
    label = (
        '\n\t\t\tif (groupPart !== "reasoning" && blocks.some((block) => block.kind === "text" && block.text.trim())) {'
        '\n\t\t\t\trendered.push((0, react_jsx_runtime.jsx)("div", {'
        ' style: { fontSize: "0.75rem", opacity: 0.75, marginBottom: "4px" },'
        ' children: mobileHarnessAiLabel() }, "mobile-harness-ai-label"));'
        '\n\t\t\t}'
    )
    end = index + len(entry)
    source = source[:end] + label + source[end:]
    copy_point = "text: assistantText(closing.blocks),"
    if source.count(copy_point) != 1:
        raise SystemExit("Unexpected pinned DSH assistant copy action")
    source = source.replace(copy_point, "text: mobileHarnessLabelCopy(assistantText(closing.blocks)),")
    helpers = (
        'function mobileHarnessAiLabel() { return document.documentElement.lang.startsWith("zh")'
        ' ? "AI 生成" : "AI-generated"; }\n'
        'function mobileHarnessLabelCopy(text) { return text ? mobileHarnessAiLabel() + "\\n\\n" + text : text; }\n'
    )
    (RAW / "appgallery-chat-client.js").write_text(helpers + source, encoding="utf-8")


def stage_appgallery_models():
    with ZipFile(RAW / "dsh-layer.zip") as layer:
        source = layer.read(MODELS_CLIENT).decode("utf-8")
    # The native first-run page supplies the phone-specific disclosure.
    notice = (
        '\t\t\tif (!("dshDesktop" in globalThis)) ctx.slots.inject("settings.onboarding", () => ctx.slots.register({\n'
        '\t\t\t\tname: "settings.onboarding",\n'
        '\t\t\t\tid: "welcome-notice",\n'
        '\t\t\t\torder: -100,\n'
        '\t\t\t\tinject: welcomeInjected\n'
        '\t\t\t}, WelcomeNotice));\n'
    )
    if source.count(notice) != 1:
        raise SystemExit("Unexpected pinned DSH welcome notice")
    (RAW / "appgallery-models-client.js").write_text(source.replace(notice, ""), encoding="utf-8")


def stage_appgallery_presets():
    blocked = {
        "persistent-shell", "tool-bash", "tool-pwsh", "tool-jobs", "tool-plugin-manager",
        "tool-plugin-market", "tool-executor-ptc", "tool-cordis", "skill-filesystem", "tool-skill",
    }
    row = re.compile(r"^ {10}- id: ([\w-]+)\s*$", re.MULTILINE)
    presets = "dsh/node_modules/@deepseek-ai/dsh-web-app/presets"
    with ZipFile(RAW / "dsh-layer.zip") as layer:
        for name in ("cordis", "minimal", "ptc", "standard"):
            source = layer.read(f"{presets}/{name}.patch.yml").decode("utf-8")
            rows = list(row.finditer(source))
            if not rows or not any(match[1] in blocked for match in rows):
                raise SystemExit(f"Unexpected pinned DSH preset structure: {name}")
            allowed = [source[:rows[0].start()]]
            for index, match in enumerate(rows):
                if match[1] not in blocked:
                    end = rows[index + 1].start() if index + 1 < len(rows) else len(source)
                    allowed.append(source[match.start():end])
            (RAW / f"appgallery-preset-{name}.yml").write_text("".join(allowed), encoding="utf-8")


def stage_runtime_revision():
    digest = hashlib.sha256()
    pinned = (ROOT / "docs/build-inputs.sha256").read_bytes()
    digest.update(pinned)
    pinned_names = {PurePosixPath(line.split(maxsplit=1)[1]).name for line in pinned.decode().splitlines()}
    for asset in sorted(RAW.iterdir()):
        if (asset.is_file() and asset.name not in pinned_names
                and asset.name not in ("runtime-revision", "appgallery-privacy-url", "appgallery-source-url")
                and not asset.name.startswith(("LICENSE.", "NOTICE."))
                and not asset.name.endswith(".zip.sha256")):
            digest.update(f"{asset.name} {sha256(asset)}\n".encode())
    (RAW / "runtime-revision").write_text(digest.hexdigest(), encoding="utf-8")
    for line in pinned.decode().splitlines():
        checksum, filename = line.split(maxsplit=1)
        asset = PurePosixPath(filename)
        if asset.parent.name == "rawfile" and asset.suffix == ".zip":
            (RAW / f"{asset.name}.sha256").write_text(checksum, encoding="utf-8")


def stage_appgallery_notices():
    base = "dsh/node_modules"
    licenses = {
        "sharp": "@img/sharp-linuxmusl-arm64/LICENSE",
        "ripgrep": "@vscode/ripgrep-linux-arm64/LICENSE",
        "koffi": "koffi/LICENSE.txt",
        "dsh-system": "@deepseek-ai/node-addon-system-linux-arm64/LICENSE",
        "require-builtin": "node-addon-require-builtin-linux-arm64-musl/LICENSE",
    }
    with ZipFile(RAW / "dsh-layer.zip") as layer:
        for name, member in licenses.items():
            (RAW / f"LICENSE.{name}.txt").write_bytes(layer.read(f"{base}/{member}"))
    with ZipFile(RAW / "pnpm-layer-v2.zip") as layer:
        (RAW / "LICENSE.pnpm.txt").write_bytes(layer.read("pnpm-harmony-v2/LICENSE"))
    copy(RUNTIME / "notices/sharp-libvips-1.3.4.md", RAW / "NOTICE.libvips.md")
    for notice in sorted((RUNTIME / "notices/alpine-3.22").glob("*.txt")):
        copy(notice, RAW / f"NOTICE.alpine.{notice.name}")


def stage_appgallery_url(variable, filename):
    path = RAW / filename
    url = os.environ.get(variable, "").strip()
    if not url:
        path.unlink(missing_ok=True)
        return
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https" and parsed.hostname
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443)
            and not any(char.isspace() or ord(char) < 32 for char in url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise SystemExit(f"{variable} must be an HTTPS URL without embedded credentials")
    path.write_text(url, encoding="utf-8")


def set_appgallery_version(config):
    name = os.environ.get("HARMONY_APPGALLERY_VERSION_NAME", "")
    code = os.environ.get("HARMONY_APPGALLERY_VERSION_CODE", "")
    if not name and not code:
        return
    if not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,9}){2}", name) or not re.fullmatch(r"[0-9]{1,10}", code):
        raise SystemExit("Set both AppGallery version variables using a three-part version and numeric build number")
    number = int(code)
    if not config["versionCode"] < number <= 2_147_483_647:
        raise SystemExit("AppGallery version code must exceed the repository version code and fit a signed 32-bit integer")
    config["versionName"] = name
    config["versionCode"] = number


def stage_appgallery_image():
    sdk = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents")) / "sdk/default/openharmony/native"
    libraries = STAGE / "entry/libs/arm64-v8a"
    subprocess.run([
        sdk / "llvm/bin/clang", "--target=aarch64-linux-ohos26.0.0", f"--sysroot={sdk / 'sysroot'}",
        "-shared", "-fPIC", "-O2", "-DNAPI_VERSION=8", "-I", ROOT / "vendor/repos/node/src",
        RUNTIME / "native/dsh-image.c", "-L", libraries, "-lnode", "-limage_source", "-limage_packer",
        "-lpixelmap", "-lm", "-Wl,-z,defs", "-o", libraries / "libdshimage.so",
    ], check=True)


def stage_appgallery_search():
    sdk = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents")) / "sdk/default/openharmony/native"
    libraries = STAGE / "entry/libs/arm64-v8a"
    target = "aarch64-unknown-linux-ohos"
    artifacts = ROOT / ".build/search-cargo"
    cargo = shutil.which("cargo") or Path.home() / ".cargo/bin/cargo"
    subprocess.run([
        cargo, "build", "--locked", "--release", "--target", target, "--target-dir", artifacts,
        "--manifest-path", RUNTIME / "search/Cargo.toml",
    ], check=True)
    metadata = json.loads(subprocess.check_output([
        cargo, "metadata", "--offline", "--locked", "--filter-platform", target,
        "--format-version", "1", "--manifest-path", RUNTIME / "search/Cargo.toml",
    ]))
    notices = ["HarmonyOS workspace search dependencies"]
    for package in sorted(metadata["packages"], key=lambda package: package["name"]):
        if not package["source"]:
            continue
        root = Path(package["manifest_path"]).parent
        license_file = root / "LICENSE-MIT"
        if not license_file.is_file():
            raise SystemExit(f"Missing Rust dependency license: {license_file}")
        notices.append(f"{package['name']} {package['version']} (MIT)\n{license_file.read_text().rstrip()}")
    rustc = os.environ.get("RUSTC") or shutil.which("rustc") or Path(cargo).with_name("rustc")
    sysroot = Path(subprocess.check_output([rustc, "--print", "sysroot"], text=True).strip())
    copyright_doc = sysroot / "share/doc/rust/COPYRIGHT-library.html"

    class CopyrightText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)

    notice = CopyrightText()
    notice.feed(copyright_doc.read_text())
    notices.append("".join(notice.parts).strip())
    (RAW / "NOTICE.workspace-search.txt").write_text("\n\n".join(notices) + "\n", encoding="utf-8")
    subprocess.run([
        sdk / "llvm/bin/clang", "--target=aarch64-linux-ohos26.0.0", f"--sysroot={sdk / 'sysroot'}",
        "-shared", "-fPIC", "-O2", "-DNAPI_VERSION=8", "-I", ROOT / "vendor/repos/node/src",
        RUNTIME / "native/dsh-search.c", artifacts / target / "release/libdsh_search.a",
        "-L", libraries, "-lnode", "-Wl,--exclude-libs,ALL", "-Wl,-z,defs",
        "-o", libraries / "libdshsearch.so",
    ], check=True)


def main():
    bundle = os.environ.get("HARMONY_APPGALLERY_BUNDLE", "")
    if APPGALLERY and not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+", bundle):
        raise SystemExit("Invalid HARMONY_APPGALLERY_BUNDLE")
    inputs = Path(os.environ.get("HARMONY_INPUTS_DIR") or ROOT / ".build/inputs/harmonyos").resolve()
    for source in files_from_index(APP):
        copy(source, STAGE / source.relative_to(APP))
    for directory in (ROOT / "packages/dsh-host", ROOT / "packages/bundles/mobile",
                      RUNTIME / "compat", RUNTIME / "diagnostics"):
        for source in sorted(directory.iterdir()):
            if source.is_file() and source.name != "appgallery.patch.yml":
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
    if APPGALLERY:
        stage_appgallery_url("HARMONY_APPGALLERY_PRIVACY_URL", "appgallery-privacy-url")
        stage_appgallery_url("HARMONY_APPGALLERY_SOURCE_URL", "appgallery-source-url")
        copy(ROOT / "packages/bundles/mobile/appgallery.patch.yml", RAW / "appgallery.patch.yml")
        app_config = STAGE / "AppScope/app.json5"
        config = json.loads(app_config.read_text())
        config["app"]["bundleName"] = bundle
        config["app"]["vendor"] = "Mobile Harness"
        set_appgallery_version(config["app"])
        app_config.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        for directory in (STAGE / "AppScope", STAGE / "entry/src/main"):
            strings = directory / "resources/base/element/string.json"
            config = json.loads(strings.read_text())
            for item in config["string"]:
                if item["name"] == "app_name":
                    item["value"] = "DSH-MH"
            strings.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    stage_assets(inputs)
    if APPGALLERY:
        stage_appgallery_image()
        stage_appgallery_search()
    stage_settings_client()
    if APPGALLERY:
        stage_appgallery_presets()
        stage_appgallery_chat()
        stage_appgallery_models()
        stage_appgallery_notices()
        for project, name in (("dsh", "LICENSE"), ("node", "LICENSE"), ("proot", "COPYING")):
            copy(ROOT / "vendor/repos" / project / name, RAW / f"LICENSE.{project}.txt")
    stage_runtime_revision()
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


if __name__ == "__main__":
    main()
