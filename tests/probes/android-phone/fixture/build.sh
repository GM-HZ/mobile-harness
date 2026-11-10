#!/bin/bash
set -euo pipefail
fixture=$(cd "$(dirname "$0")" && pwd)
project=$(cd "$fixture/../../../.." && pwd)
sdk=${ANDROID_HOME:-${ANDROID_SDK_ROOT:?Set ANDROID_HOME}}
tools="$sdk/build-tools/35.0.0"
platform="$sdk/platforms/android-36/android.jar"
out="$project/.build/android-phone-fixture"
mkdir -p "$out"
work=$(mktemp -d "$out/build.XXXXXX")
trap 'rm -rf "$work"' EXIT
cd "$work"

javac --release 8 -classpath "$platform" -d . "$fixture/MainActivity.java"
"$tools/d8" --lib "$platform" --min-api 26 org/mobileharness/phonefixture/MainActivity.class
"$tools/aapt2" link -I "$platform" --manifest "$fixture/AndroidManifest.xml" \
  --min-sdk-version 26 --target-sdk-version 35 -o fixture.apk
zip -q fixture.apk classes.dex
"$tools/zipalign" 4 fixture.apk aligned.apk

key="$out/debug.keystore"
if [[ ! -f "$key" ]]; then
  keytool -genkeypair -keystore "$key" -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -validity 3650 -dname 'CN=Mobile Harness Test'
fi
"$tools/apksigner" sign --ks "$key" --ks-pass pass:android --out "$out/phone-fixture.apk" aligned.apk
printf '%s\n' "$out/phone-fixture.apk"
