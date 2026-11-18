#!/bin/bash
set -euo pipefail
export LC_ALL=C
target="${1:?pass the loopback DevEco Phone emulator target}"
mode="${2:-restart}"
case "$target" in
  127.0.0.1:*) ;;
  *) echo 'This measurement only accepts a loopback emulator target' >&2; exit 2 ;;
esac
case "$mode" in
  fresh|restart) ;;
  *) echo 'Expected fresh or restart' >&2; exit 2 ;;
esac
hdc="${HARMONY_HDC:-/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc}"
bundle=org.sayact.nodepoc
device=("$hdc" -t "$target")
type=$("${device[@]}" shell 'param get const.product.devicetype' | tr -d '[:space:]')
test "$type" = phone
previous_pids=$("${device[@]}" shell pidof "$bundle")
"${device[@]}" shell aa force-stop "$bundle"
if [[ "$mode" == fresh ]]; then
  cleaned=$("${device[@]}" shell bm clean -n "$bundle" -d)
  printf '%s\n' "$cleaned"
  printf '%s\n' "$cleaned" | grep -qi 'success'
fi
started=$("${device[@]}" shell aa start -a EntryAbility -b "$bundle")
printf '%s\n' "$started"
printf '%s\n' "$started" | grep -q 'start ability successfully'
for ((second=0; second<60; second++)); do
  pids=$("${device[@]}" shell pidof "$bundle")
  for pid in $pids; do
    [[ "$pid" =~ ^[0-9]+$ && " $previous_pids " != *" $pid "* ]] || continue
    logs=$("${device[@]}" shell hilog -x -P "$pid" | grep 'DSHClient:' || true)
    if printf '%s\n' "$logs" | grep -q 'ArkWeb loaded.*complete'; then
      printf '%s\n' "$logs" | grep -E 'startup archive|starting native Web|native loopback ready|ArkWeb loaded'
      exit 0
    fi
  done
  sleep 1
done
echo 'ArkWeb load milestone was not observed within 60 checks' >&2
exit 1
