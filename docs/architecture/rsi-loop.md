# RSI loop

The gate suite exists so the repo can improve itself without a human memory of
"what used to work": every run is recorded, every escape becomes a new case.

## Signals

- **Gate run** → `docs/evidence/rsi/ledger.jsonl` (one line per run: commit,
  tiers, ok, evidence path, note). `gates/run.py --record` appends it.
- **CI run** → uploaded evidence artifact; the nightly workflow keeps the last
  90 artifacts (GitHub retention) and mirrors the summary into the ledger on a
  release job (planned).
- **Escape** (bug found after merge, or a nightly/device failure that does not
  reproduce on the same commit) → the run is recorded with `ok=false` and a
  `note`, and a new gate case is added before fixing.

## Rules

1. Every escaped defect adds at least one durable gate case (G2/G3, or a G1
   contract if it is an upstream-anchor issue).
2. Flaky tests are retried at most twice and quarantined after two consecutive
   non-repro results; quarantined tests must be fixed or removed within a week.
3. A release is blocked unless G0/G1/G4 pass on the release commit and the last
   G2 run is green; G3 real-device evidence is required for device-facing changes.
4. The scoreboard is reviewed weekly (`python3 scripts/adaptation/rsi_ledger.py report`).

## Current coverage

- G0/G1: automatic (PR gate + local).
- G2: `gate-nightly.yml` runs the consolidated capability gate; ad-hoc smoke
  suites are listed in `gates/registry.json` and run by hand until the matrix is
  wired.
- G3: `device_lab.py` protocol + `gate-device.yml` (manual dispatch while the
  device is not always attached).
- G4: variant builds and `variant_check.py`; wire the build matrix into the
  nightly release job next.
