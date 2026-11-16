#!/bin/bash
set -euo pipefail
probe=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$probe/../../.." && pwd)
stage="$root/.build/stage/harmonyos-workflow-sandbox"
deveco=${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}
mkdir -p "$stage"

git -C "$root" archive HEAD apps/harmonyos | tar -x -C "$stage" --strip-components=2
rm -rf "$stage/entry/src/main/ets/runtime"
cp "$probe/EntryAbility.ets" "$stage/entry/src/main/ets/entryability/"
cp "$probe/Index.ets" "$stage/entry/src/main/ets/pages/"
mkdir -p "$stage/entry/src/main/cpp/types/libworkflowprobe"
cp "$probe/probe.c" "$stage/entry/src/main/cpp/"
cat > "$stage/entry/src/main/cpp/CMakeLists.txt" <<'CMAKE'
cmake_minimum_required(VERSION 3.5.0)
project(workflowprobe)
add_library(workflowprobe SHARED probe.c)
target_link_libraries(workflowprobe PUBLIC libace_napi.z.so)
CMAKE
cat > "$stage/entry/src/main/cpp/types/libworkflowprobe/index.d.ts" <<'TYPES'
interface WorkflowProbe {
  run(): string;
}
declare const probe: WorkflowProbe;
export default probe;
TYPES
cat > "$stage/entry/src/main/cpp/types/libworkflowprobe/oh-package.json5" <<'PACKAGE'
{"name":"libworkflowprobe.so","version":"1.0.0","types":"./index.d.ts"}
PACKAGE
python3 - "$stage" <<'PY'
from pathlib import Path
import sys

stage = Path(sys.argv[1])
config = stage / 'AppScope/app.json5'
config.write_text(config.read_text().replace('org.sayact.nodepoc', 'org.mobileharness.workflowsandbox'))
manifest = stage / 'entry/oh-package.json5'
manifest.write_text(manifest.read_text().replace('libpoc', 'libworkflowprobe'))
PY
install -m 600 "$stage/build-profile.example.json5" "$stage/build-profile.json5"

export JAVA_HOME="$deveco/jbr/Contents/Home"
export DEVECO_SDK_HOME="$deveco/sdk"
export LC_ALL=C
export PATH="/usr/bin:/bin:/opt/homebrew/bin:$deveco/tools/node/bin"
cd "$stage"
"$deveco/tools/ohpm/bin/ohpm" install
"$deveco/tools/node/bin/node" "$deveco/tools/hvigor/bin/hvigorw.js" \
    --mode module -p module=entry@default -p product=default -p buildMode=debug assembleHap --no-daemon
