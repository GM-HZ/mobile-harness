#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
deveco=/Applications/DevEco-Studio.app/Contents
export JAVA_HOME="$deveco/jbr/Contents/Home"
export DEVECO_SDK_HOME="$deveco/sdk"
export LC_ALL=C
export PATH="/usr/bin:/bin:/opt/homebrew/bin:$deveco/tools/node/bin"
"$deveco/tools/ohpm/bin/ohpm" install
"$deveco/tools/node/bin/node" "$deveco/tools/hvigor/bin/hvigorw.js" \
  --mode module -p module=entry@default -p product=default -p buildMode=debug assembleHap --no-daemon
