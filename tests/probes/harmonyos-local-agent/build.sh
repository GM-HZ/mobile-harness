#!/bin/bash
set -euo pipefail

if [[ $# != 1 ]]; then
  printf 'Usage: %s <static HarmonyOS ARM64 llama.cpp build directory>\n' "$0" >&2
  exit 2
fi

export MH_LLAMA_BUILD
MH_LLAMA_BUILD=$(cd "$1" && pwd)
probe=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$probe/../../.." && pwd)
app="$root/apps/harmonyos"
stage="$root/.build/stage/harmonyos-local-agent-probe"
deveco=${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}

mkdir -p "$stage"
lock="$stage.lock"
if ! mkdir "$lock" 2>/dev/null; then
  printf 'Another build is using %s\n' "$stage" >&2
  exit 1
fi
trap 'rmdir "$lock"' EXIT

cp -R "$probe/project/." "$stage/"
cp -R "$app/hvigor" "$stage/"
cp "$app/hvigorfile.ts" "$app/oh-package.json5" "$stage/"
cp "$app/entry/hvigorfile.ts" "$stage/entry/"
mkdir -p "$stage/AppScope/resources/base/media"
cp "$app/AppScope/resources/base/media/icon.svg" "$stage/AppScope/resources/base/media/"
resources="$app/entry/src/main/resources/base"
entry_resources="$stage/entry/src/main/resources/base"
mkdir -p "$entry_resources/media" "$entry_resources/element" "$entry_resources/profile"
cp "$resources/media/icon.svg" "$entry_resources/media/"
cp "$resources/element/color.json" "$entry_resources/element/"
cp "$resources/profile/main_pages.json" "$entry_resources/profile/"
install -m 600 "$app/build-profile.example.json5" "$stage/build-profile.json5"

export JAVA_HOME="$deveco/jbr/Contents/Home"
export DEVECO_SDK_HOME="$deveco/sdk"
export LC_ALL=C
export PATH="/usr/bin:/bin:/opt/homebrew/bin:$deveco/tools/node/bin"

cd "$stage"
"$deveco/tools/ohpm/bin/ohpm" install
"$deveco/tools/node/bin/node" "$deveco/tools/hvigor/bin/hvigorw.js" \
  --mode module -p module=entry@default -p product=default -p buildMode=debug assembleHap --no-daemon
artifact="$stage/entry/build/default/outputs/default/entry-default-unsigned.hap"
test -s "$artifact"
printf '%s\n' "$artifact"
