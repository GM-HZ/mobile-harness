"""Stage the AppGallery runtime from the patched, locked HarmonyOS DSH layer."""

import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from harmonyos_dsh import MANIFEST, OPTIONAL_ARCHIVE

ARCHIVE = "dsh-appgallery-layer.zip"
PINNED_INPUTS = {"libnode.so", "libdshflock.so", "libdshpublish.so", "dsh-layer.zip"}
HOST_FILES = {
    "appgallery.patch.yml",
    "dsh-client.patch.yml",
    "dsh-harmony-fs.mjs",
    "dsh-harmony-http.cjs",
    "dsh-harmony-llhttp.cjs",
    "dsh-native-image.cjs",
    "dsh-native-search.cjs",
    "dsh-native-web.cjs",
}
APPGALLERY_ONLY = {"appgallery.patch.yml", "dsh-native-image.cjs", "dsh-native-search.cjs"}

NODE_MODULES = "dsh/node_modules/"
DEEPSEEK_PACKAGES = NODE_MODULES + "@deepseek-ai/"
SETTINGS = DEEPSEEK_PACKAGES + "dsh-client-ui-settings-general/lib/client.js"
CHAT = DEEPSEEK_PACKAGES + "dsh-client-ui-chat/lib/client.js"
MODELS = DEEPSEEK_PACKAGES + "dsh-client-ui-settings-models/lib/client.js"
DOCUMENT_PREVIEW = DEEPSEEK_PACKAGES + "dsh-client-ui-sidebar-documentpreview/lib/client.js"
PRESETS = DEEPSEEK_PACKAGES + "dsh-web-app/presets/"
RESTRICTED_TOOLS = {
    "persistent-shell", "tool-bash", "tool-pwsh", "tool-jobs", "tool-plugin-manager",
    "tool-plugin-market", "tool-executor-ptc", "tool-cordis", "skill-filesystem", "tool-skill",
    "workflow-ptc", "tool-workflow",
}
PRESET_ROW = re.compile(r"^( +)- id: ([\w-]+)[ \t]*$", re.MULTILINE)
EXCLUDED_PREFIXES = (
    "toolchains/lsp/",
    NODE_MODULES + "@img/sharp-libvips-linuxmusl-arm64/",
    NODE_MODULES + "@img/sharp-wasm32/",
    NODE_MODULES + "sherpa-onnx-linux-arm64/",
    DEEPSEEK_PACKAGES + "libreoffice-kit/",
    DEEPSEEK_PACKAGES + "libreoffice-kit-wasm/",
)
LICENSES = {
    NODE_MODULES + "@img/sharp-linuxmusl-arm64/LICENSE": "LICENSE.sharp.txt",
    NODE_MODULES + "@vscode/ripgrep-linux-arm64/LICENSE": "LICENSE.ripgrep.txt",
    NODE_MODULES + "koffi/LICENSE.txt": "LICENSE.koffi.txt",
    DEEPSEEK_PACKAGES + "node-addon-system-linux-arm64/LICENSE": "LICENSE.dsh-system.txt",
    NODE_MODULES + "node-addon-require-builtin-linux-arm64-musl/LICENSE": "LICENSE.require-builtin.txt",
}


def replace_one(source, before, after):
    if source.count(before) != 1:
        raise ValueError(f"Unexpected pinned AppGallery client entry: {before}")
    return source.replace(before, after, 1)


def appgallery_settings(source, overlay):
    forge_row = (
        '\tctx.slots.inject("settings.general.item", () => ctx.slots.register({\n'
        '\t\tname: "settings.general.item",\n'
        '\t\tid: "mobile-harness-github",\n'
        '\t\torder: 97,\n'
        '\t\tlocale: NS,\n'
        '\t}, MobileHarnessGitHubRow));\n'
    )
    source = replace_one(source, forge_row, "")
    anchor = "function apply(ctx){"
    return replace_one(source, anchor, overlay.rstrip() + "\n" + anchor + "registerMobileHarnessAppGallery(ctx);")


def appgallery_chat(source):
    helpers = (
        'function mobileHarnessAiLabel(){return document.documentElement.lang.startsWith("zh")'
        '?"AI 生成":"AI-generated"}'
        'function mobileHarnessLabelCopy(text){return text?mobileHarnessAiLabel()+"\\n\\n"+text:text}'
    )
    entry = "const AssistantMarkdown="
    source = replace_one(source, entry, helpers + entry)
    label = (
        'if(groupPart!=="reasoning"&&blocks.some(block=>block.kind==="text"&&block.text.trim()))'
        'rendered.push((0,react_jsx_runtime.jsx)("div",{style:{fontSize:"0.75rem",opacity:0.75,marginBottom:"4px"},'
        'children:mobileHarnessAiLabel()},"mobile-harness-ai-label"));'
    )
    source = replace_one(source, "const rendered=[];", "const rendered=[];" + label)
    return replace_one(source, "text:assistantText(closing.blocks)",
                       "text:mobileHarnessLabelCopy(assistantText(closing.blocks))")


def appgallery_models(source):
    notice = (
        'if(!(`dshDesktop`in globalThis))ctx.slots.inject(`settings.onboarding`,()=>ctx.slots.register('
        '{name:`settings.onboarding`,id:`welcome-notice`,order:-100,inject:welcomeInjected},WelcomeNotice));'
    )
    return replace_one(source, notice, "")


def appgallery_preset(source):
    rows = list(PRESET_ROW.finditer(source))
    beginning = 0
    kept = []
    for index, row in enumerate(rows):
        if row.start() < beginning or row[2] not in RESTRICTED_TOOLS:
            continue
        kept.append(source[beginning:row.start()])
        depth = len(row[1])
        beginning = next((next_row.start() for next_row in rows[index + 1:] if len(next_row[1]) <= depth),
                         len(source))
    if not kept:
        raise ValueError("Unexpected pinned AppGallery preset structure")
    return "".join(kept) + source[beginning:]


def stage_layer(root, source, raw):
    manifest = json.loads((source / MANIFEST).read_text())
    archives = [source / chunk["file"] for chunk in manifest["chunks"]]
    archives.append(source / OPTIONAL_ARCHIVE)
    overlay = (root / "runtime/harmonyos/web/settings-appgallery.js").read_text()
    transforms = {
        SETTINGS: lambda text: appgallery_settings(text, overlay),
        CHAT: appgallery_chat,
        MODELS: appgallery_models,
        DOCUMENT_PREVIEW: lambda text: replace_one(text, "apply$2(ctx,config.office);", ""),
        **{PRESETS + preset + ".patch.yml": appgallery_preset
           for preset in ("cordis", "minimal", "ptc", "standard")},
    }
    required = set(transforms) | set(LICENSES)
    pending = raw / (ARCHIVE + ".tmp")
    destination = raw / ARCHIVE
    try:
        with ZipFile(pending, "w") as output:
            for archive in archives:
                with ZipFile(archive) as packaged:
                    for member in packaged.infolist():
                        name = member.filename
                        license_name = LICENSES.get(name)
                        if license_name:
                            (raw / license_name).write_bytes(packaged.read(name))
                            required.remove(name)
                        if name.endswith((".node", ".exe", ".dll", ".dylib")) or name.startswith(EXCLUDED_PREFIXES):
                            continue
                        with packaged.open(member) as contents:
                            prefix = contents.read(4)
                            if prefix == b"\x7fELF":
                                continue
                            info = ZipInfo(name)
                            info.compress_type = ZIP_DEFLATED
                            with output.open(info, "w") as target:
                                transform = transforms.get(name)
                                if transform:
                                    payload = (prefix + contents.read()).decode("utf-8")
                                    target.write(transform(payload).encode("utf-8"))
                                    required.remove(name)
                                else:
                                    target.write(prefix)
                                    shutil.copyfileobj(contents, target)
            if required:
                raise ValueError(f"Missing locked AppGallery layer inputs: {sorted(required)}")
        pending.replace(destination)
    finally:
        pending.unlink(missing_ok=True)
    checksum = hashlib.sha256()
    with destination.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    (raw / (ARCHIVE + ".sha256")).write_text(checksum.hexdigest(), encoding="utf-8")


def stage_appgallery_url(raw, variable, filename):
    path = raw / filename
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


def stage_appgallery_image(root, libraries):
    sdk = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents")) / "sdk/default/openharmony/native"
    subprocess.run([
        sdk / "llvm/bin/clang", "--target=aarch64-linux-ohos26.0.0", f"--sysroot={sdk / 'sysroot'}",
        "-shared", "-fPIC", "-O2", "-DNAPI_VERSION=8", "-I", root / "vendor/repos/node/src",
        root / "runtime/harmonyos" / "native/dsh-image.c", "-L", libraries, "-lnode", "-limage_source", "-limage_packer",
        "-lpixelmap", "-lm", "-Wl,-z,defs", "-o", libraries / "libdshimage.so",
    ], check=True)


def stage_appgallery_search(root, libraries, raw):
    sdk = Path(os.environ.get("DEVECO_HOME", "/Applications/DevEco-Studio.app/Contents")) / "sdk/default/openharmony/native"
    target = "aarch64-unknown-linux-ohos"
    artifacts = root / ".build/search-cargo"
    cargo = shutil.which("cargo") or Path.home() / ".cargo/bin/cargo"
    subprocess.run([
        cargo, "build", "--locked", "--release", "--target", target, "--target-dir", artifacts,
        "--manifest-path", root / "runtime/harmonyos" / "search/Cargo.toml",
    ], check=True)
    metadata = json.loads(subprocess.check_output([
        cargo, "metadata", "--offline", "--locked", "--filter-platform", target,
        "--format-version", "1", "--manifest-path", root / "runtime/harmonyos" / "search/Cargo.toml",
    ]))
    notices = ["HarmonyOS workspace search dependencies"]
    for package in sorted(metadata["packages"], key=lambda package: package["name"]):
        if not package["source"]:
            continue
        package_directory = Path(package["manifest_path"]).parent
        license_file = package_directory / "LICENSE-MIT"
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
    (raw / "NOTICE.workspace-search.txt").write_text("\n\n".join(notices) + "\n", encoding="utf-8")
    subprocess.run([
        sdk / "llvm/bin/clang", "--target=aarch64-linux-ohos26.0.0", f"--sysroot={sdk / 'sysroot'}",
        "-shared", "-fPIC", "-O2", "-DNAPI_VERSION=8", "-I", root / "vendor/repos/node/src",
        root / "runtime/harmonyos" / "native/dsh-search.c", artifacts / target / "release/libdsh_search.a",
        "-L", libraries, "-lnode", "-Wl,--exclude-libs,ALL", "-Wl,-z,defs",
        "-o", libraries / "libdshsearch.so",
    ], check=True)
