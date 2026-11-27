# Gate scoreboard

Generated 2026-11-27 19:28 from 135 ledger runs (of 135 recorded).

| Tier | Registry entries | Runs | First-pass | Flake-pass | Fail | Last run |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| G0 | 3 | 52 | 45 | 0 | 7 | f9a4d30ae151 PASS 2026-11-27T00:04:50+0800 |
| G1 | 14 | 52 | 46 | 0 | 6 | f9a4d30ae151 PASS 2026-11-27T00:04:50+0800 |
| G2 | 73 | 20 | 17 | 1 | 2 | c59ee85f300d PASS 2026-11-27T09:41:41+0800 |
| G3 | 3 | 16 | 10 | 0 | 6 | 33574c7b00fd PASS 2026-11-27T08:53:25+0800 |
| G4 | 8 | 22 | 22 | 0 | 0 | f9a4d30ae151 PASS 2026-11-27T00:05:45+0800 |

## Recent failures

- `9484278baf1c` G0,G1 2026-11-21T20:50:21+0800 — failures=1
- `97e4367f904b` G0,G1 2026-11-21T21:43:56+0800 — failures=1
- `717cc3312ebb` G0,G1 2026-11-22T21:32:32+0800 — failures=2
- `a4b022b343e6` G3 2026-11-25T21:30:23+0800 — Mate 60 v1.0.0/77 startup crashes in V8 SetPermissions; exec and overlay blocked on startup.
- `3e695423e334` G3 2026-11-25T21:44:50+0800 — Both verify runs passed. Exec and overlay expected stdout was absent for the copied Node and installed jq probes.
- `3e695423e334` G2 2026-11-25T21:53:47+0800 — failures=1
- `542c510bb452` G3 2026-11-25T22:06:44+0800 — Exact signed build on Mate 60. Both starts plus actual Workflow passed. Copied Node and installed jq outputs were absent in the strict exec and overlay probes.
- `58b9751cba1a` G3 2026-11-25T22:38:51+0800 — Mate 60: verify and overlay pass on the signed candidate. Copied Node exec remains unresolved.
- `3737f3af3746` G3 2026-11-25T23:10:45+0800 — Mate 60 verify, signed overlay, inert jq upgrade and controlled exit-status tests pass. Original copied Node exec requirement remains unresolved.
- `33574c7b00fd` G2 2026-11-27T09:00:57+0800 — First exact revision parity run failed the ArkWeb native-microphone UI step; nine other cases passed

## Gate registry snapshot

- G0 (static/consistency): 3 entries
- G1 (host contracts): 14 entries
- G2 (emulator capability): 73 entries
- G3 (real-device lab): 3 entries
- G4 (build/release): 8 entries
