#!/usr/bin/env python3
"""Weekly gate scoreboard from the RSI ledger + gate registry.

    python3 scripts/adaptation/gate_report.py [--limit 200]

Writes docs/evidence/rsi/scoreboard.md and prints a short summary.
"""
import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/evidence/rsi/ledger.jsonl"
REGISTRY = ROOT / "gates/registry.json"
OUTPUT = ROOT / "docs/evidence/rsi/scoreboard.md"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text())["tiers"]
    rows = []
    if LEDGER.is_file():
        rows = [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()]
    recent = rows[-args.limit:]
    tiers = sorted({tier for row in recent for tier in row["tiers"]})
    stats = {}
    for tier in tiers:
        selected = [row for row in recent if tier in row["tiers"]]
        stats[tier] = {
            "runs": len(selected),
            "first": sum(1 for row in selected if row["ok"] and not row.get("flakes")),
            "flake": sum(1 for row in selected if row["ok"] and row.get("flakes")),
            "fail": sum(1 for row in selected if not row["ok"]),
            "last": selected[-1] if selected else None,
        }
    failures = [row for row in recent if not row["ok"]][-10:]
    lines = [f"# Gate scoreboard", "",
             f"Generated {time.strftime('%Y-%m-%d %H:%M')} from {len(recent)} ledger runs "
             f"(of {len(rows)} recorded).", ""]
    lines += ["| Tier | Registry entries | Runs | First-pass | Flake-pass | Fail | Last run |",
              "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for tier in tiers:
        row = stats[tier]
        last = row["last"]
        last_text = (f"{last['commit'][:12]} {'PASS' if last['ok'] else 'FAIL'} {last['at']}" if last else "-")
        lines.append(f"| {tier} | {len(registry.get(tier, {}).get('entries', []))} | {row['runs']} | "
                     f"{row['first']} | {row['flake']} | {row['fail']} | {last_text} |")
    lines += ["", "## Recent failures", ""]
    if failures:
        for row in failures:
            lines.append(f"- `{row['commit'][:12]}` {','.join(row['tiers'])} {row.get('at', '')}"
                         + (f" — {row.get('note')}" if row.get("note") else ""))
    else:
        lines.append("No failures in the recent window.")
    lines += ["", "## Gate registry snapshot", ""]
    for tier, info in registry.items():
        lines.append(f"- {tier} ({info['name']}): {len(info['entries'])} entries")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")
    displayed_path = output.relative_to(ROOT) if output.is_relative_to(ROOT) else output
    print(f"scoreboard: {displayed_path}")
    for tier, row in stats.items():
        print(f"  {tier}: {row['runs']} runs = {row['first']} first + {row['flake']} flake + {row['fail']} fail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
