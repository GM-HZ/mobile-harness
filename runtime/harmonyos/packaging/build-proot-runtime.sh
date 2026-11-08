#!/bin/bash
set -euo pipefail
project=$(cd "$(dirname "$0")/../../.." && pwd)
stage=${HARMONY_STAGE:-"$project/.build/stage/harmonyos"}
sdk=${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}/sdk/default/openharmony/native
src="$(cd "${1:?pass the patched PRoot source tree}" && pwd)"
libs="$stage/entry/libs/arm64-v8a"
talloc="$(cd "${HARMONY_TALLOC_ROOT:?set the prepared talloc root}" && pwd)"
headers="$talloc/talloc-stage/data/local/tmp/harmony-proot-validation/include"
export LC_ALL=C
export PATH="$sdk/llvm/bin:/opt/homebrew/bin:$PATH"
cd "$src/src"
CFLAGS="--sysroot=$sdk/sysroot -D__OHOS__ -I$headers -fPIC" \
  LDFLAGS="--sysroot=$sdk/sysroot -L$talloc/static-talloc -shared -Wl,-soname,libproot_core.so" \
  gmake -j8 CC=aarch64-unknown-linux-ohos-clang READELF=llvm-readelf \
  OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip \
  PROOT_UNBUNDLE_LOADER=/data/local/tmp/harmony-proot-validation
install -m 755 proot "$libs/libproot_core.so"
aarch64-unknown-linux-ohos-clang --sysroot="$sdk/sysroot" -shared -nostdlib -fPIC -ffreestanding \
  -fno-stack-protector -O2 -I. -D_start=ohos_guest_loader -Wl,-soname,libproot_preloader.so \
  -Wl,--no-undefined loader/loader.c -o "$libs/libproot_preloader.so.new"
mv "$libs/libproot_preloader.so.new" "$libs/libproot_preloader.so"
