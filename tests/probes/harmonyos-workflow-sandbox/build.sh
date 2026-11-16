#!/bin/bash
set -euo pipefail
probe=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$probe/../../.." && pwd)
stage="$root/.build/stage/harmonyos-workflow-sandbox"
deveco=${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}
inputs=${HARMONY_INPUTS_DIR:-$root/.build/inputs/harmonyos}
mkdir -p "$stage"

git -C "$root" archive HEAD apps/harmonyos | tar -x -C "$stage" --strip-components=2
rm -rf "$stage/entry/src/main/ets/runtime"
cp "$probe/EntryAbility.ets" "$stage/entry/src/main/ets/entryability/"
cp "$probe/Index.ets" "$stage/entry/src/main/ets/pages/"
mkdir -p "$stage/entry/src/main/cpp/types/libworkflowprobe"
cp "$probe/probe.c" "$probe/launch-node.c" "$probe/workflow-node.c" "$stage/entry/src/main/cpp/"
cp "$root/runtime/harmonyos/native/workflow-broker.c" "$root/runtime/harmonyos/native/workflow-broker.h" \
    "$stage/entry/src/main/cpp/"
mkdir -p "$stage/entry/libs/arm64-v8a" "$stage/entry/src/main/resources/rawfile"
node_asset=entry/libs/arm64-v8a/libnode.so
awk -v asset="$node_asset" '$2 == asset {print; found=1} END {exit !found}' "$root/docs/build-inputs.sha256" |
    (cd "$inputs" && LC_ALL=C shasum -a 256 -c -)
cp "$inputs/$node_asset" "$stage/entry/libs/arm64-v8a/"
cp "$root/vendor/repos/node/src/node_api.h" "$root/vendor/repos/node/src/node_api_types.h" \
    "$root/vendor/repos/node/src/js_native_api.h" "$root/vendor/repos/node/src/js_native_api_types.h" \
    "$stage/entry/src/main/cpp/"
cat > "$stage/entry/src/main/cpp/CMakeLists.txt" <<'CMAKE'
cmake_minimum_required(VERSION 3.5.0)
project(workflowprobe)
add_library(workflowprobe SHARED probe.c launch-node.c workflow-broker.c)
target_link_libraries(workflowprobe PUBLIC libace_napi.z.so dl)
add_library(workflownode SHARED workflow-node.c)
target_include_directories(workflownode PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(workflownode PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../../../libs/arm64-v8a/libnode.so)
CMAKE
cat > "$stage/entry/src/main/cpp/types/libworkflowprobe/index.d.ts" <<'TYPES'
interface WorkflowProbe {
  run(): string;
  runNode(entry: string): string;
}
declare const probe: WorkflowProbe;
export default probe;
TYPES
cat > "$stage/entry/src/main/cpp/types/libworkflowprobe/oh-package.json5" <<'PACKAGE'
{"name":"libworkflowprobe.so","version":"1.0.0","types":"./index.d.ts"}
PACKAGE
python3 - "$stage" "$probe" "$root" <<'PY'
import json
from pathlib import Path
import sys
from urllib.parse import quote

stage, probe, root = map(Path, sys.argv[1:])
config = stage / 'AppScope/app.json5'
config.write_text(config.read_text().replace('org.sayact.nodepoc', 'org.mobileharness.workflowsandbox'))
manifest = stage / 'entry/oh-package.json5'
manifest.write_text(manifest.read_text().replace('libpoc', 'libworkflowprobe'))
workflow = root / 'vendor/repos/dsh/packages/workflow/workflow-ptc/src'
guest = (workflow / 'guest-source.ts').read_text().split('export const WORKFLOW_GUEST_SOURCE = ', 1)[1]
guest_url = 'data:text/javascript,' + quote(json.loads(guest), safe='')
worker = (probe / 'workflow-worker.cjs').read_text().replace('PACKAGED_WORKFLOW_GUEST_URL', json.dumps(guest_url), 1)
(stage / 'entry/src/main/resources/rawfile/workflow-worker.cjs').write_text(worker)
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
