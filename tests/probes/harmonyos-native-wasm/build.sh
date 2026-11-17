#!/bin/bash
set -euo pipefail
probe=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$probe/../../.." && pwd)
stage="$root/.build/stage/harmonyos-native-wasm"
deveco=${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}
inputs=${HARMONY_INPUTS_DIR:-$root/.build/inputs/harmonyos}
mkdir -p "$stage"
git -C "$root" archive HEAD apps/harmonyos | tar -x -C "$stage" --strip-components=2
rm -rf "$stage/entry/src/main/ets/runtime"
cp "$probe/EntryAbility.ets" "$stage/entry/src/main/ets/entryability/"
cp "$probe/Index.ets" "$stage/entry/src/main/ets/pages/"
cp "$probe/probe.c" "$stage/entry/src/main/cpp/"
mkdir -p "$stage/entry/libs/arm64-v8a" "$stage/entry/src/main/resources/rawfile"
asset=entry/libs/arm64-v8a/libnode.so
awk -v asset="$asset" '$2 == asset {print; found=1} END {exit !found}' "$root/docs/build-inputs.sha256" | (cd "$inputs" && LC_ALL=C shasum -a 256 -c -)
cp "$inputs/$asset" "$stage/$asset"
cp "$probe/native-wasm.cjs" "$stage/entry/src/main/resources/rawfile/"
cat > "$stage/entry/src/main/cpp/CMakeLists.txt" <<'CMAKE'
cmake_minimum_required(VERSION 3.5.0)
project(nativewasmprobe)
add_library(poc SHARED probe.c)
target_link_libraries(poc PUBLIC libace_napi.z.so dl)
CMAKE
printf 'declare const probe: { run(entry: string): string }; export default probe;\n' > "$stage/entry/src/main/cpp/types/libpoc/index.d.ts"
python3 - "$stage" <<'PY'
from pathlib import Path
import json,sys
root=Path(sys.argv[1]);p=root/'AppScope/app.json5';x=json.loads(p.read_text());x['app'].update(bundleName='org.mobileharness.nativewasmprobe',versionCode=1,versionName='0.0.1');p.write_text(json.dumps(x,indent=2)+'\n')
for p in root.glob('**/resources/base/element/string.json'):
 x=json.loads(p.read_text())
 for item in x.get('string',[]):
  if item['name']=='app_name':item['value']='Native WASM probe'
 p.write_text(json.dumps(x,indent=2)+'\n')
PY
install -m 600 "$stage/build-profile.example.json5" "$stage/build-profile.json5"
export JAVA_HOME="$deveco/jbr/Contents/Home" DEVECO_SDK_HOME="$deveco/sdk" LC_ALL=C
export PATH="/usr/bin:/bin:/opt/homebrew/bin:$deveco/tools/node/bin"
cd "$stage"
"$deveco/tools/ohpm/bin/ohpm" install
"$deveco/tools/node/bin/node" "$deveco/tools/hvigor/bin/hvigorw.js" --mode module -p module=entry@default -p product=default -p buildMode=debug assembleHap --no-daemon
