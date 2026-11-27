#!/usr/bin/env bash
# Local G4 dry run for the current commit.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
store_only=0
if [[ ${1:-} == --store-only ]]; then
  store_only=1
  shift
fi
if [[ $# -gt 1 || ${1:-} == --* ]]; then
  echo 'Usage: release_dry_run.sh [--store-only] [version]' >&2
  exit 2
fi
build_version=$(python3 -c 'import json; print(json.load(open("apps/harmonyos/AppScope/app.json5"))["app"]["versionName"])')
version="${1:-$build_version}"
if [[ $store_only == 1 && $version != "$build_version" ]]; then
  echo 'Store preview version must match AppScope/app.json5.' >&2
  exit 2
fi
unsigned_hap=".build/artifacts/harmonyos/dsh-mh-harmonyos-arm64-v$build_version-unsigned.hap"
output=".build/release-check/$version"
mkdir -p "$output"
echo "== store build"
HARMONY_UNSIGNED=1 HARMONY_SELF_BUILD=0 HARMONY_APPGALLERY_BUILD=0 \
  HARMONY_EXPERIMENTAL_HOST_PROCESS=0 ./build.sh --package
cp "$unsigned_hap" "$output/store.hap"
if [[ $store_only == 1 ]]; then
  python3 scripts/adaptation/release_evidence.py --store "$output/store.hap" \
    --version "$version" --store-only --require-self-build-metadata
  python3 scripts/adaptation/release_gate.py --version "$version" --store-only
  exit 0
fi
echo "== self build"
HARMONY_UNSIGNED=1 HARMONY_SELF_BUILD=1 ./build.sh --package
cp "$unsigned_hap" "$output/self.hap"
echo "== AppGallery build"
HARMONY_UNSIGNED=1 HARMONY_SELF_BUILD=0 \
  HARMONY_APPGALLERY_BUNDLE="${HARMONY_APPGALLERY_BUNDLE:-org.mobileharness.dshmh}" \
  HARMONY_APPGALLERY_VERSION_NAME= HARMONY_APPGALLERY_VERSION_CODE= ./build.sh --appgallery
cp ".build/artifacts/harmonyos-appgallery/dsh-mh-arm64-v$build_version-unsigned.app" "$output/appgallery.app"
echo "== release evidence"
python3 scripts/adaptation/release_evidence.py --store "$output/store.hap" \
  --self "$output/self.hap" --appgallery "$output/appgallery.app" --version "$version" \
  --require-self-build-metadata
echo "== release gate"
python3 scripts/adaptation/release_gate.py --version "$version" --require-appgallery
