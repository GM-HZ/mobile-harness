#!/usr/bin/python3
"""Download a tool and register it as a PATH command.

When a pinned APK has a matching signed tool in the HAP, verify the APK and
register a launcher for that bundled executable. Other existing installations
are stored under /usr/lib/mh-tools/<name>/ with a shim in /usr/bin/<name>.

Shipped only in self-built HAPs (alongside /usr/bin/mh-exec):

    #!/bin/sh
    export MH_ELF_ARGV0=<argv0>
    exec /usr/bin/mh-exec /usr/lib/mh-tools/<name>/tool "$@"

Usage:

    mh-install <name> <url> [member] [argv0]

`member` is the path inside a tar.gz/apk archive (for example
`bin/busybox.static`); omit it when the URL is the executable itself. `argv0`
defaults to <name> and is what the tool sees as argv[0] (busybox needs its
applet name or "busybox").
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory

ROOT = "/usr/lib/mh-tools"
MH_EXEC = "/usr/bin/mh-exec"
SIGNED_TOOLS = Path("/usr/share/mobile-harness/signed-tools.json")


def run(command, **kwargs):
    return subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kwargs)


def install_signed(name, package):
    program = package["guestPath"]
    if not os.path.isfile(program):
        print("MH_INSTALL_ERROR signed tool is missing: " + program)
        return 1
    shim = Path("/usr/bin") / name
    pending = None
    try:
        with TemporaryDirectory(prefix="mh-install-") as folder:
            archive = Path(folder) / "archive"
            run(["curl", "-fsSL", "--proto", "=https", "--proto-redir", "=https", "--max-time", "45",
                 "--max-filesize", str(package["bytes"]), "-o", str(archive), package["url"]])
            with archive.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            if checksum != package["sha256"]:
                print("MH_INSTALL_ERROR signed tool package checksum mismatch")
                return 1
        with NamedTemporaryFile(mode="w", dir=shim.parent, prefix=".mh-install-", delete=False) as handle:
            pending = Path(handle.name)
            handle.write("#!/bin/sh\nexec " + shlex.quote(program) + ' "$@"\n')
        pending.chmod(0o755)
        pending.replace(shim)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    print("MH_INSTALL_OK " + str(shim))
    print("MH_INSTALL_TOOL " + program)
    return 0


def main():
    if len(sys.argv) < 3:
        print("usage: mh-install <name> <url> [member] [argv0]")
        return 2
    name = sys.argv[1]
    url = sys.argv[2]
    member = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
    argv0 = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else name
    if not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
        print("MH_INSTALL_ERROR invalid name")
        return 2
    try:
        signed = json.loads(SIGNED_TOOLS.read_text()).get(name)
    except FileNotFoundError:
        signed = None
    if signed and (url, member, argv0) == (signed["url"], signed["member"], name):
        try:
            return install_signed(name, signed)
        except (OSError, subprocess.CalledProcessError) as error:
            print("MH_INSTALL_ERROR " + str(error)[:300])
            return 1
    if not os.path.exists(MH_EXEC):
        print("MH_INSTALL_ERROR /usr/bin/mh-exec is missing (store build?)")
        return 2
    destination = os.path.join(ROOT, name)
    shutil.rmtree(destination, ignore_errors=True)
    os.makedirs(destination, exist_ok=True)
    archive = os.path.join(destination, "download")
    tool = os.path.join(destination, "tool")
    try:
        run(["curl", "-fsSL", "-o", archive, url])
        if member:
            tarball = os.path.join(destination, "archive.tar")
            with open(tarball, "wb") as handle:
                subprocess.run(["gzip", "-dc", archive], check=True, stdout=handle)
            # Stream the single member to the tool file: extracting the whole tree
            # fails in the guest because symlink creation is denied there.
            with open(tool, "wb") as handle:
                streamed = subprocess.run(["tar", "-xOf", tarball, member], check=False, stdout=handle)
            if streamed.returncode != 0 or os.path.getsize(tool) == 0:
                print("MH_INSTALL_ERROR member not found: " + member)
                return 1
        else:
            shutil.copy2(archive, tool)
        with open(tool, "rb") as handle:
            magic = handle.read(4)
        if magic != b"\x7fELF":
            print("MH_INSTALL_ERROR downloaded file is not an ELF binary")
            return 1
        os.chmod(tool, 0o755)
        shim = os.path.join("/usr/bin", name)
        with open(shim, "w") as handle:
            # A shell shim crashes at exit because the PRoot loader state does not
            # survive a nested exec from a loader-managed /bin/sh. Use a Python
            # shebang and run the loader code in this interpreter instead.
            handle.write(
                "#!/usr/bin/python3\n"
                "import os, sys\n"
                "os.environ['MH_ELF_ARGV0'] = " + repr(argv0) + "\n"
                "sys.argv = [" + repr(MH_EXEC) + ", " + repr(tool) + "] + sys.argv[1:]\n"
                "exec(compile(open(" + repr(MH_EXEC) + ").read(), " + repr(MH_EXEC) + ", 'exec'),\n"
                "     {'__name__': '__main__'})\n")
            os.chmod(shim, 0o755)
        json.dump({"name": name, "url": url, "member": member, "argv0": argv0, "tool": tool},
                  open(os.path.join(destination, "mh-tool.json"), "w"))
        print("MH_INSTALL_OK " + shim)
        print("MH_INSTALL_TOOL " + tool)
        return 0
    except subprocess.CalledProcessError as error:
        print("MH_INSTALL_ERROR " + str(error.returncode) + " " + str(error.stdout)[:300])
        return 1


if __name__ == "__main__":
    sys.exit(main())
