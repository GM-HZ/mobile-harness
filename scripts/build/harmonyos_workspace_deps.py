"""Stage the upstream Office Python package set for the Alpine guest."""

import hashlib
import json
from pathlib import PurePosixPath
import shutil
import stat
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from harmonyos_guest_extras import PYTHON, PIP_WHEEL, locked_archive


def stage_workspace_dependencies(root, raw):
    lock_path = root / "runtime/harmonyos/dsh/office-wheels.json"
    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    upstream = root / "vendor/repos/dsh/scripts/primary-runtime/lock.json"
    packages = {wheel["name"]: wheel["version"] for wheel in lock["wheels"]}
    if packages != json.loads(upstream.read_text())["pythonPackages"]:
        raise ValueError("Harmony Office wheels do not match the pinned DSH distribution versions")
    abi, platform = lock["pythonAbi"], lock["platform"]
    if (abi, platform) != ("cp312", "musllinux_1_2_aarch64"):
        raise ValueError("Expected the Harmony guest's CPython 3.12 ARM64 musl wheels")

    identity = hashlib.sha256(lock_bytes).hexdigest()
    site = "opt/tools/office-python/" + identity + "/site-packages/"
    cache = root / ".build/runtime-package-inputs/office-wheels"
    seen = set()
    layer = raw / "workspace-python-v1.zip"
    with ZipFile(layer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(ZipInfo("opt/tools/node_modules/"), b"")
        for wheel in lock["wheels"]:
            url = urlsplit(wheel["url"])
            directory, filename = wheel["url"].rsplit("/", 1)
            if (url.scheme != "https" or url.netloc != "files.pythonhosted.org"
                    or url.query or url.fragment or not filename.endswith((
                        f"-{abi}-{abi}-{platform}.whl", "-none-any.whl",
                    ))):
                raise ValueError(f"Unexpected wheel source or platform: {wheel['name']}")
            source = locked_archive(directory + "/", {"archive": filename, "sha256": wheel["sha256"]}, cache)
            with ZipFile(source) as package:
                for member in package.infolist():
                    if member.is_dir():
                        continue
                    entry = PurePosixPath(member.filename)
                    if (entry.is_absolute() or ".." in entry.parts or "\\" in member.filename
                            or stat.S_ISLNK(member.external_attr >> 16)
                            or member.filename in seen):
                        raise ValueError(f"Unsafe wheel path: {member.filename}")
                    if entry.parts[0].endswith(".data") and entry.parts[1:2] != ("scripts",):
                        raise ValueError(f"Unsupported wheel install scheme: {member.filename}")
                    seen.add(member.filename)
                    output = ZipInfo(site + entry.as_posix())
                    output.compress_type = ZIP_DEFLATED
                    with package.open(member) as contents, archive.open(output, "w") as destination:
                        shutil.copyfileobj(contents, destination)

    with layer.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (raw / "workspace-python-id.txt").write_text(digest)
    # site.py resolves a .pth entry relative to the distro site-packages directory.
    (raw / "workspace-python.pth").write_text("../../../../" + site.rstrip("/") + "\n")
    descriptor = {
        "python": "/usr/bin/python3",
        "node": "/bin/node",
        "pnpm": "/pnpm-harmony-v2/bin/pnpm.mjs",
        "pythonPackages": "/" + site.rstrip("/"),
        "nodePackages": "/opt/tools/node_modules",
        "pythonDistributions": {**packages, "pip": PIP_WHEEL.split("-")[1]},
    }
    (raw / "dsh-harmony-workspace-deps.json").write_text(json.dumps(descriptor) + "\n")
