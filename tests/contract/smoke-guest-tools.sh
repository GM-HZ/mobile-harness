#!/bin/bash
# Run from the DSH work directory using an approved HarmonyOS Bash tool call.
set -eu
test "$(whoami)" = mobile-harness
test "$(id -u)" -gt 0
test "$(stat -c %F /usr/share/zoneinfo/Asia/Shanghai)" = 'regular file'
test "$(TZ=Asia/Shanghai date +%z)" = +0800
test "$(sqlite3 :memory: 'select 42;')" = 42
test "$(curl --max-time 5 --silent --show-error -o /dev/null -w '%{http_code}' http://127.0.0.1:19592/)" = 401
test "$(node -e 'fetch("http://127.0.0.1:19592/").then(r => console.log(r.status))')" = 401
python3 -m pip --version
work=$(mktemp -d ./mh-guest-tools.XXXXXX)
trap 'rm -rf "$work"' EXIT
python3 - "$work" <<'PY'
import pathlib
import sys
import zipfile

directory = pathlib.Path(sys.argv[1])
for version in ("1.0", "2.0"):
    info = f"mh_fixture-{version}.dist-info"
    wheel = directory / f"mh_fixture-{version}-py3-none-any.whl"
    records = {
        "mh_fixture.py": f"VERSION = {version!r}\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{info}/METADATA": f"Metadata-Version: 2.1\nName: mh-fixture\nVersion: {version}\n",
    }
    records[f"{info}/RECORD"] = "".join(f"{path},,\n" for path in [*records, f"{info}/RECORD"])
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, value in records.items():
            archive.writestr(name, value)
PY
for version in 1.0 2.0; do
    target="$work/project-$version/.python-packages"
    python3 -m pip --disable-pip-version-check install --no-index --no-deps --target "$target" \
        "$work/mh_fixture-$version-py3-none-any.whl"
    test "$(PYTHONPATH="$target" python3 -c 'import mh_fixture; print(mh_fixture.VERSION)')" = "$version"
done
printf 'HARMONY_TOOLKIT_OK\n'
