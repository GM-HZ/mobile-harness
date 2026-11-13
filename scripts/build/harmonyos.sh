#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
project=$PWD
deveco=${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}
mode=${1:-}
if [[ $# -gt 1 || ( -n $mode && $mode != --prepare-only && $mode != --package && $mode != --appgallery ) ]]; then
  echo 'Usage: ./build.sh [--prepare-only | --package | --appgallery]' >&2
  exit 2
fi
stage="$project/.build/stage/harmonyos"
if [[ ${HARMONY_EXPERIMENTAL_HOST_PROCESS:-0} == 1 ]]; then
  stage="$project/.build/stage/harmonyos-process-probe"
fi
if [[ $mode == --appgallery ]]; then
  if [[ ${HARMONY_EXPERIMENTAL_HOST_PROCESS:-0} == 1 || -z ${HARMONY_APPGALLERY_BUNDLE:-} ]]; then
    echo 'Set HARMONY_APPGALLERY_BUNDLE to the bundle name registered in AppGallery Connect.' >&2
    exit 2
  fi
  export HARMONY_APPGALLERY_BUILD=1
  stage="$project/.build/stage/harmonyos-appgallery"
fi
mkdir -p "$(dirname "$stage")"
lock="$stage.lock"
if ! mkdir "$lock" 2>/dev/null; then
  echo "Another build is using $stage" >&2
  exit 1
fi
trap 'rmdir "$lock"' EXIT
export JAVA_HOME="$deveco/jbr/Contents/Home"
export DEVECO_SDK_HOME="$deveco/sdk"
export LC_ALL=C
export PATH="/usr/bin:/bin:/opt/homebrew/bin:$deveco/tools/node/bin"
scripts/vendor/verify.sh
python3 scripts/build/stage-harmonyos.py
if [[ $mode == --prepare-only ]]; then exit 0; fi
cd "$stage"
"$deveco/tools/ohpm/bin/ohpm" install
hvigor=( "$deveco/tools/node/bin/node" "$deveco/tools/hvigor/bin/hvigorw.js" )
if [[ $mode == --appgallery ]]; then
  rm -f build/outputs/default/*.app
  "${hvigor[@]}" --mode project -p product=default -p buildMode=release assembleApp --no-daemon
  version=$(python3 -c 'import json; print(json.load(open("AppScope/app.json5"))["app"]["versionName"])')
  artifacts="$project/.build/artifacts/harmonyos-appgallery"
  mkdir -p "$artifacts"
  packages=( build/outputs/default/*-unsigned.app )
  if [[ ${#packages[@]} != 1 || ! -s ${packages[0]} ]]; then
    echo 'Expected one unsigned Release .app from Hvigor' >&2
    exit 1
  fi
  name="dsh-mh-arm64-v$version-unsigned.app"
  cp "${packages[0]}" "$artifacts/$name"
  (cd "$artifacts" && shasum -a 256 "$name" > "$name.sha256")
  printf '%s/%s\n' "$artifacts" "$name"
  exit 0
fi
output=entry/build/default/outputs/default
rm -f "$output/entry-default-signed.hap" "$output/entry-default-unsigned.hap"
"${hvigor[@]}" \
  --mode module -p module=entry@default -p product=default -p buildMode=debug assembleHap --no-daemon

if [[ $mode == --package ]]; then
  version=$(python3 -c 'import json; print(json.load(open("AppScope/app.json5"))["app"]["versionName"])')
  artifacts="$project/.build/artifacts/${stage##*/}"
  mkdir -p "$artifacts"
  test -s "$output/entry-default-unsigned.hap"
  for kind in unsigned signed; do
    name="dsh-mh-${stage##*/}-arm64-v$version-$kind.hap"
    if [[ -s "$output/entry-default-$kind.hap" ]]; then
      cp "$output/entry-default-$kind.hap" "$artifacts/$name"
      (cd "$artifacts" && shasum -a 256 "$name" > "$name.sha256")
      printf '%s/%s\n' "$artifacts" "$name"
    else
      rm -f "$artifacts/$name" "$artifacts/$name.sha256"
    fi
  done
fi
