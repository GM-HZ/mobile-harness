#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

mode=debug
prepare=0
while (($#)); do
  case "$1" in
    --debug|--release) mode=${1#--} ;;
    --prepare-only) prepare=1 ;;
    *) echo "Usage: ./build.sh android [--prepare-only] [--debug|--release]" >&2; exit 2 ;;
  esac
  shift
done

signing_file=
if [[ $mode == release ]] && (( ! prepare )); then
  : "${ANDROID_SIGNING_PROPERTIES:?Set ANDROID_SIGNING_PROPERTIES for a release build}"
  if [[ ! -s "$ANDROID_SIGNING_PROPERTIES" || ! -f "$ANDROID_SIGNING_PROPERTIES" ]]; then
    echo "ANDROID_SIGNING_PROPERTIES must be a nonempty Gradle properties file" >&2
    exit 1
  fi
  signing_file=$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=True))' "$ANDROID_SIGNING_PROPERTIES")
fi

stage="$PWD/.build/stage/android"
mkdir -p "$(dirname "$stage")"
lock="$stage.lock"
if ! mkdir "$lock" 2>/dev/null; then
  echo "Another build is using $stage" >&2
  exit 1
fi
staged_signing="$stage/app/android/key.properties"
cleanup() {
  if [[ -n "$signing_file" && -L "$staged_signing" ]]; then
    unlink "$staged_signing"
  fi
  rmdir "$lock"
}
trap cleanup EXIT
python3 scripts/build/stage-android.py
if ((prepare)); then exit 0; fi
if [[ -n "$signing_file" ]]; then
  ln -s "$signing_file" "$staged_signing"
fi

if [[ -n ${FLUTTER_ROOT:-} ]]; then
  export PATH="$FLUTTER_ROOT/bin:$PATH"
fi
command -v flutter >/dev/null || { echo "Flutter 3.47.7 is required. Set FLUTTER_ROOT or PATH." >&2; exit 1; }
export LC_ALL=C
export FLUTTER_SUPPRESS_ANALYTICS=true
export DSH_MAVEN_MIRRORS=${DSH_MAVEN_MIRRORS:-0}
cd "$stage"
python3 app/tool/l10n_merge.py
tooling/build-apk.sh "--$mode" --build-name 0.1.0 --keep-daemon
