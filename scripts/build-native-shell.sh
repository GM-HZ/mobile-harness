#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
sdk=/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native
node_source=${HARMONY_NODE_SOURCE:-../.build/node-target/node-v24.14.1}
"$sdk/llvm/bin/clang" --target=aarch64-linux-ohos --sysroot="$sdk/sysroot" \
  -shared -fPIC -O2 -DNAPI_VERSION=8 -I "$node_source/src" native/dsh-shell.c \
  -L entry/libs/arm64-v8a -lnode -Wl,-z,defs -o entry/libs/arm64-v8a/libdshshell.so
