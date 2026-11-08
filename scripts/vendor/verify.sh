#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
while read -r key component; do
  expected=$(git ls-files -s -- "$component" | awk '$1 == 160000 { print $2 }')
  if [[ -z "$expected" || ! -e "$component/.git" ]]; then
    echo "Missing gitlink or checkout: $component. Run git submodule update --init." >&2
    exit 1
  fi
  actual=$(git -C "$component" rev-parse HEAD)
  if [[ "$actual" != "$expected" || -n $(git -C "$component" status --porcelain --ignore-submodules=all) ]]; then
    echo "Submodule does not match the clean index pin: $component" >&2
    exit 1
  fi
  expected_url=$(git config -f .gitmodules "${key%.path}.url")
  if [[ $(git -C "$component" remote get-url origin) != "$expected_url" ]]; then
    echo "Unexpected submodule source: $component" >&2
    exit 1
  fi
  printf '%s %s\n' "$component" "$actual"
done < <(git config -f .gitmodules --get-regexp '^submodule\..*\.path$')
