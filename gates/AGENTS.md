# AGENTS.md — 门禁系统（`gates/`）

## 规则

1. **registry 是单一来源**：`gates/registry.json` 由 `scripts/adaptation/registry.py` 生成；
   加用例改生成器，不手改 JSON（可在 `--check` 中防漂移）。
2. **层级归属**：G0 静态、G1 host 合同、G2 模拟器、G3 真机、G4 构建/发布；不要混层。
3. **命令可重复**：每条命令必须能在干净环境执行；需要环境的条目标记 `requires`，缺失时应 skip（exit 2）。
4. **证据格式**：`gates/run.py` 写入 `docs/evidence/gates/<tier>/<commit>.json`；包含 exit/duration/output tail；
   `--record` 写 RSI 台账。
5. **flake**：重试上限 2 次；`PASS (flake)` 单独计数，禁止用重试掩盖真失败。
6. **发布闸门**：tag/release 必须有当前 commit 和发行范围对应的绿色 release evidence；由 `release_gate.py` 强制。Store 预览通过显式 `--store-only` 校验，其他发行沿用完整变体验收。
7. **新增 gate 的 DoD**：registry 行 + 命令可跑 + 一次绿色证据 + 周报可见。
8. **真机目标**。设备门禁要求 HDC 显示 `USB Connected`。接有多台设备时，使用 `device_lab.py --target <connection-key> run --suite verify` 明确指定目标。

## 检查清单

- [ ] `python3 gates/run.py --tier G0,G1` 通过；
- [ ] 新 gate 在本机跑出证据；
- [ ] weekly scoreboard 能看到该 gate 的 first/flake/fail。
