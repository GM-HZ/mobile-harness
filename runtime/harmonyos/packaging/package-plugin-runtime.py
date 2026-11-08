"""Prepare the pinned pnpm package for the HarmonyOS private filesystem."""
import argparse
import base64
import hashlib
import os
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

PROJECT = Path(__file__).resolve().parents[3]
ROOT = Path(os.environ.get("HARMONY_STAGE", PROJECT / ".build/stage/harmonyos"))
INTEGRITY = "SEVj0wtMKtJ8tIqpT/KzAtvOvI/2vyiBbCWJiG4UbOf3bzVPO8GkOOb16XaMMCqgpvet2CMpA81M+BQmy8FNng=="
REGISTRATION = b"    await registerProject(storeDir, lockfileDir);\n"
FETCH_DISPATCH = b"""    dispatcher
  });
}
function createDispatchedFetch"""
FETCH_DISPATCH_HARMONY = b"""    dispatcher,
    harmonyNetwork: !opts3.dispatcherOptions.httpProxy && !opts3.dispatcherOptions.httpsProxy &&
      !opts3.dispatcherOptions.ca && !opts3.dispatcherOptions.cert && !opts3.dispatcherOptions.key &&
      !opts3.dispatcherOptions.localAddress && opts3.dispatcherOptions.strictSsl !== false &&
      !hasClientCertificates(opts3.dispatcherOptions.clientCertificates)
  });
}
function createDispatchedFetch"""
FETCH_IMPL = b"""  const { retry: _retry, timeout, dispatcher, ...fetchOpts } = opts3;
  const res = await (0, import_undici2.fetch)(urlString, {
    ...fetchOpts,
    dispatcher: withInactivityTimeout(dispatcher, timeout)
  });"""
FETCH_IMPL_HARMONY = b"""  const { retry: _retry, timeout, dispatcher, harmonyNetwork, ...fetchOpts } = opts3;
  let res;
  if (harmonyNetwork) {
    const headers = new globalThis.Headers(fetchOpts.headers);
    headers.set("accept-encoding", "identity");
    res = await globalThis.fetch(urlString, { ...fetchOpts, headers }, { timeoutMs: timeout });
  } else {
    res = await (0, import_undici2.fetch)(urlString, {
      ...fetchOpts,
      dispatcher: withInactivityTimeout(dispatcher, timeout)
    });
  }"""


def package(archive):
    with archive.open("rb") as source:
        checksum = base64.b64encode(hashlib.file_digest(source, "sha512").digest()).decode()
    if checksum != INTEGRITY:
        raise ValueError("Expected the pinned pnpm 11.28.5 registry archive")
    target = ROOT / "entry/src/main/resources/rawfile/pnpm-layer-v2.zip"
    with tarfile.open(archive) as npm, zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for entry in sorted(npm, key=lambda member: member.name):
            path = PurePosixPath(entry.name)
            if not entry.isfile() or path.parts[0] != "package" or ".." in path.parts or path.suffix == ".node":
                continue
            data = npm.extractfile(entry).read()
            relative = "/".join(path.parts[1:])
            if relative == "dist/pnpm.mjs":
                for original, replacement in (
                    (REGISTRATION, b""), (FETCH_DISPATCH, FETCH_DISPATCH_HARMONY), (FETCH_IMPL, FETCH_IMPL_HARMONY),
                ):
                    if data.count(original) != 1:
                        raise ValueError("Unexpected pnpm integration source")
                    data = data.replace(original, replacement)
            bundle.writestr(zipfile.ZipInfo("pnpm-harmony-v2/" + relative), data, compress_type=zipfile.ZIP_DEFLATED)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pnpm_11_28_5", type=Path)
    package(parser.parse_args().pnpm_11_28_5)
