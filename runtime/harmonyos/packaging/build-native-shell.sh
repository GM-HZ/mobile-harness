#!/bin/bash
set -euo pipefail
project=$(cd "$(dirname "$0")/../../.." && pwd)
stage=${HARMONY_STAGE:-"$project/.build/stage/harmonyos"}
sdk=${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}/sdk/default/openharmony/native
node_source=${HARMONY_NODE_SOURCE:-"$project/vendor/repos/node"}
"$sdk/llvm/bin/clang" --target=aarch64-linux-ohos --sysroot="$sdk/sysroot" \
  -shared -fPIC -O2 -DNAPI_VERSION=8 -I "$node_source/src" "$project/runtime/harmonyos/native/dsh-shell.c" \
  -L "$stage/entry/libs/arm64-v8a" -lnode -Wl,-z,defs -o "$stage/entry/libs/arm64-v8a/libdshshell.so"
"$sdk/llvm/bin/clang" --target=aarch64-linux-ohos --sysroot="$sdk/sysroot" \
  -shared -fPIC -O2 -DNAPI_VERSION=8 -I "$node_source/src" "$project/runtime/harmonyos/native/dsh-workflow.c" \
  "$project/runtime/harmonyos/native/ptc-file-filter.c" \
  -L "$stage/entry/libs/arm64-v8a" -lnode -ldl -Wl,-z,defs -o "$stage/entry/libs/arm64-v8a/libdshworkflow.so"

shim="$stage/entry/libs/arm64-v8a/libguest_mh_exec_shim.so"
if [[ ${HARMONY_SELF_BUILD:-0} == 1 ]]; then
  "$sdk/llvm/bin/clang" --target=aarch64-linux-ohos --sysroot="$sdk/sysroot" \
    -shared -nostdlib -fPIC -O2 "$project/runtime/harmonyos/native/mh-exec-shim.c" -o "$shim"
else
  rm -f "$shim"
fi
