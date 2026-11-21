#!/usr/bin/env bash
# Local G4 dry run: build store + self, record release evidence and assert the
# release gate passes for the current commit.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
version="${1:-0.4.69}"
mkdir -p .build/release-check
echo "== store build"
HARMONY_UNSIGNED=1 ./build.sh --package
cp .build/artifacts/harmonyos/*-unsigned.hap .build/release-check/store.hap
echo "== self build"
HARMONY_UNSIGNED=1 HARMONY_SELF_BUILD=1 ./build.sh --package
cp .build/artifacts/harmonyos/*-unsigned.hap .build/release-check/self.hap
echo "== release evidence"
python3 scripts/adaptation/release_evidence.py --store .build/release-check/store.hap \
  --self .build/release-check/self.hap --version "$version"
echo "== release gate"
python3 scripts/adaptation/release_gate.py --version "$version"
