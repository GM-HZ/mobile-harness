#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ${1:-} == android ]]; then
  shift
  exec scripts/build/android.sh "$@"
fi
exec scripts/build/harmonyos.sh "$@"
