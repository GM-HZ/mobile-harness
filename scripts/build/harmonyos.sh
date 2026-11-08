#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
project=$PWD
deveco=${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}
stage="$project/.build/stage/harmonyos"
if [[ ${HARMONY_EXPERIMENTAL_HOST_PROCESS:-0} == 1 ]]; then
  stage="$project/.build/stage/harmonyos-process-probe"
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
if [[ ${1:-} == --prepare-only ]]; then exit 0; fi
cd "$stage"
"$deveco/tools/ohpm/bin/ohpm" install
"$deveco/tools/node/bin/node" "$deveco/tools/hvigor/bin/hvigorw.js" \
  --mode module -p module=entry@default -p product=default -p buildMode=debug assembleHap --no-daemon
