"""Prepare the pinned pnpm package for the HarmonyOS private filesystem."""
import argparse
import base64
import hashlib
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INTEGRITY = "SEVj0wtMKtJ8tIqpT/KzAtvOvI/2vyiBbCWJiG4UbOf3bzVPO8GkOOb16XaMMCqgpvet2CMpA81M+BQmy8FNng=="
REGISTRATION = b"    await registerProject(storeDir, lockfileDir);\n"


def package(archive):
    with archive.open("rb") as source:
        checksum = base64.b64encode(hashlib.file_digest(source, "sha512").digest()).decode()
    if checksum != INTEGRITY:
        raise ValueError("Expected the pinned pnpm 11.28.5 registry archive")
    target = ROOT / "entry/src/main/resources/rawfile/pnpm-layer.zip"
    with tarfile.open(archive) as npm, zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for entry in sorted(npm, key=lambda member: member.name):
            path = PurePosixPath(entry.name)
            if not entry.isfile() or path.parts[0] != "package" or ".." in path.parts or path.suffix == ".node":
                continue
            data = npm.extractfile(entry).read()
            relative = "/".join(path.parts[1:])
            if relative == "dist/pnpm.mjs":
                if data.count(REGISTRATION) != 1:
                    raise ValueError("Unexpected pnpm project store registration")
                data = data.replace(REGISTRATION, b"")
            bundle.writestr(zipfile.ZipInfo("pnpm-harmony/" + relative), data, compress_type=zipfile.ZIP_DEFLATED)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pnpm_11_28_5", type=Path)
    package(parser.parse_args().pnpm_11_28_5)
