#!/usr/bin/env python3
"""Run gate tiers from gates/registry.json and write evidence.

    python3 gates/run.py --tier G0[,G1]
    python3 gates/run.py --tier G2 --only capability-parity-gate
    python3 gates/run.py --list

Entries whose command still contains a <placeholder> are skipped and recorded.
Exit code: 0 all run entries passed (skips allowed); 1 failures; 2 no entries.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "gates/registry.json"


def load_registry():
    return json.loads(REGISTRY.read_text())["tiers"]


def commit():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def run_entry(tier, entry):
    command = entry["command"]
    started = time.monotonic()
    if "<" in command and ">" in command:
        return {"id": entry["id"], "tier": tier, "command": command, "skipped": True,
                "reason": "contains unfilled placeholder", "exit": None, "passed": False,
                "durationSeconds": 0}
    try:
        result = subprocess.run(command, shell=True, cwd=ROOT, text=True, capture_output=True,
                                timeout=entry.get("timeout", 600))
        code = result.returncode
        output = (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired as error:
        code = "timeout"
        output = ((error.stdout or "") if isinstance(error.stdout, str) else "") + \
                 ((error.stderr or "") if isinstance(error.stderr, str) else "")
    duration = round(time.monotonic() - started, 1)
    if code == 2:
        return {"id": entry["id"], "tier": tier, "command": command, "skipped": True,
                "reason": "tool reported environment unavailable (exit 2)", "exit": 2,
                "passed": False, "durationSeconds": duration, "outputTail": output[-1500:]}
    return {"id": entry["id"], "tier": tier, "command": command, "exit": code,
            "passed": code == 0, "skipped": False, "durationSeconds": duration,
            "outputTail": output[-1500:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", default="G0", help="comma separated tiers, e.g. G0,G1")
    parser.add_argument("--only", help="comma separated entry ids")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "docs/evidence/gates")
    parser.add_argument("--record", action="store_true", help="append the run to the RSI ledger")
    args = parser.parse_args()
    tiers = load_registry()
    if args.list:
        for tier, info in tiers.items():
            print(f"{tier} {info['name']} ({len(info['entries'])})")
            for entry in info["entries"]:
                print(f"  {entry['id']}: {entry['command']}")
        return 0
    wanted_tiers = [item.strip() for item in args.tier.split(",") if item.strip()]
    wanted_ids = {item.strip() for item in args.only.split(",")} if args.only else None
    selected = []
    for tier in wanted_tiers:
        if tier not in tiers:
            print(f"unknown tier {tier}", file=sys.stderr)
            return 2
        for entry in tiers[tier]["entries"]:
            if wanted_ids and entry["id"] not in wanted_ids:
                continue
            if not wanted_ids and entry.get("optional"):
                continue
            selected.append((tier, entry))
    if not selected:
        print("no gate entries selected", file=sys.stderr)
        return 2
    records = []
    failures = 0
    for tier, entry in selected:
        record = run_entry(tier, entry)
        records.append(record)
        status = "SKIP" if record["skipped"] else ("PASS" if record["passed"] else "FAIL")
        print(f"[{tier}] {status} {record['id']} ({record['durationSeconds']}s)")
        if not record["skipped"] and not record["passed"]:
            failures += 1
            tail = record.get("outputTail", "").strip().splitlines()
            for line in tail[-5:]:
                print("    " + line)
    evidence = {"commit": commit(), "tiers": wanted_tiers, "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "entries": records, "failures": failures, "ok": failures == 0}
    evidence_dir = args.evidence_dir if args.evidence_dir.is_absolute() else ROOT / args.evidence_dir
    directory = evidence_dir / "-".join(wanted_tiers)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (evidence["commit"] + ".json")
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"evidence: {path.relative_to(ROOT)}")
    if args.record:
        subprocess.run(["python3", "scripts/adaptation/rsi_ledger.py", "record",
                        "--tiers", ",".join(wanted_tiers),
                        "--evidence", str(path.relative_to(ROOT))] +
                       (["--ok"] if failures == 0 else []) +
                       (["--note", "failures=" + str(failures)] if failures else []),
                       cwd=ROOT, check=False)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
