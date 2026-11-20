#!/usr/bin/env python3
"""RSI ledger: record gate runs and report pass rates.

Record a run (also done automatically by `gates/run.py --record`):

    python3 scripts/adaptation/rsi_ledger.py record --tiers G0,G1 --ok \
        --evidence docs/evidence/gates/G0/<commit>.json

Report the scoreboard:

    python3 scripts/adaptation/rsi_ledger.py report [--limit 50]
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/evidence/rsi/ledger.jsonl"


def record(entry):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    recorder = sub.add_parser("record")
    recorder.add_argument("--tiers", required=True)
    recorder.add_argument("--ok", action="store_true")
    recorder.add_argument("--evidence", default="")
    recorder.add_argument("--note", default="")
    reporter = sub.add_parser("report")
    reporter.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if args.command == "record":
        commit = __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        record({"commit": commit, "tiers": args.tiers.split(","), "ok": bool(args.ok),
                "evidence": args.evidence, "note": args.note,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        print(f"ledger entry recorded ({args.tiers} ok={bool(args.ok)})")
        return 0
    if not LEDGER.is_file():
        print("ledger is empty")
        return 0
    rows = [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()]
    recent = rows[-args.limit:]
    tiers = sorted({tier for row in recent for tier in row["tiers"]})
    print(f"runs: {len(recent)} (of {len(rows)} recorded)")
    for tier in tiers:
        selected = [row for row in recent if tier in row["tiers"]]
        passed = sum(1 for row in selected if row["ok"])
        print(f"  {tier}: {passed}/{len(selected)} passed")
    last = recent[-1]
    print(f"last: {last['commit'][:12]} {'PASS' if last['ok'] else 'FAIL'} {last['tiers']} {last['at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
