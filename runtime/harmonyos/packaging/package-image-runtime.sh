#!/bin/bash
set -euo pipefail
project=$(cd "$(dirname "$0")/../../.." && pwd)
stage=${HARMONY_STAGE:-"$project/.build/stage/harmonyos"}
modules=${HARMONY_DSH_MODULES:?set the staged DSH node_modules directory}
libraries="$stage/entry/libs/arm64-v8a"
install -m 755 "$modules/@img/sharp-linuxmusl-arm64/lib/sharp-linuxmusl-arm64-0.35.5.node" "$libraries/libguest_sharp.so"
install -m 755 "$modules/@img/sharp-libvips-linuxmusl-arm64/lib/libvips-cpp.so.8.18.7" "$libraries/libguest_vips.so"
