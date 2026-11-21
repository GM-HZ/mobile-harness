# AGENTS.md — Mobile Harness 开发规则（AI 与人类共用）

本仓库是「把 DeepSeek Harness 装进手机」的适配工程：上游 DSH 是 npm/子模块 pin，
我们在其上叠加补丁、兼容层、原生运行时、HarmonyOS App、工具链与门禁。

**动手前必读（按顺序）：**

1. `docs/architecture/framework.md` —— 框架分层、所有权、扩展点、硬性不变量（本仓库的"宪法"）；
2. `docs/architecture/feature-roadmap.md` —— 能力矩阵与新增功能的落点；
3. 你要改的目录下的 `AGENTS.md`（`packages/dsh-host/`、`runtime/harmonyos/{compat,native,packaging}/`、`apps/harmonyos/`、`tests/smoke/`、`gates/`、`patches/`）。

## 当前阶段（2026-11-21 起）：功能锁定 / 第一可用版本

- `main` 进入 **feature freeze**：不再新增能力；只做 **bugfix、稳定性、体验、性能、文档**。
- 功能状态以 `docs/architecture/feature-roadmap.md` 的能力矩阵为准；任何新增能力需要先在
  `docs/work/` 写明理由并明确"解锁功能"，否则不合并。
- 所有改动先在 feature/bugfix 分支验证，再合并回 `main`；合并后在 `main` 重跑
  G0/G1/G2/G3 回归，证据落盘。
- 第一可用版本的验收口径见 `docs/work/2026-11-21-first-usable-version.md`。

## 常驻规则（违反任何一条视为 blocking）

1. **适配面单一来源**：任何 overlay、原生绑定、输入 pin、变体开关、运行时 patch 都必须出现在
   `adaptation/manifest.json`；新文件/哈希变化用 `python3 scripts/adaptation/inventory.py` 重生成。
2. **补丁必须可验证**：不要新增"启动时字符串替换"作为默认做法。次序是
   **上游 seam > 包级 patch（`patches/series.json` + `patches/TARGETS.md`）> 运行时 patch**；
   运行时 patch 必须同时有锚点（`adaptation/anchors.json`）、G1 合同与迁移目标（`adaptation/convergence.json`）。
3. **每项能力有门禁**：新增/修改功能必须落到 `gates/registry.json` 的某一层，并能在本机跑通；
   没有 gate 的"能跑"不算完成。
4. **证据即交付**：门禁运行写 `docs/evidence/gates/`；真机/模拟器证据写 `docs/evidence/device-lab/`、
   `docs/evidence/forge/` 等；发布记录写 `docs/evidence/release/`；RSI 台账自动记录。
5. **store / self / lab 变体语义不可混用**：store 构建 **不得** 包含 `mh-exec`、exec shim、overlay 库；
   self 构建才包含。改 `HARMONY_SELF_BUILD` 相关行为必须同时跑 `store_build_check` 与 `variant_check`。
6. **安全与凭据**：不得把真实 token/密码写入仓库、日志或证据；夹具只能用 loopback 模拟器；
   真机验证用的临时凭据结束即清理。
7. **上游锁定图**：升级 DSH 版本 = 改 `versions.lock.json` + 跑 bump 排练 + 全门禁；
   不允许只改 package-lock 或只看模拟器。
8. **文档同改**：行为/接口/补丁变化时，同一提交内更新对应模块 `AGENTS.md`、seam/contract、
   `patches/TARGETS.md`、`docs/architecture/feature-roadmap.md`（若能力状态变化）。
9. **不要发明入口**：新行为放到 framework.md 指定的层与扩展点；不确定时先写方案到
   `docs/work/` 再实现，不要直接塞进 `dsh-native-web.cjs` 或 `DshEngine.ets`。

## 常用命令

```sh
python3 gates/run.py --tier G0,G1            # 静态/合同门禁（每次改动）
python3 gates/run.py --tier G1 --record      # + 写 RSI 台账
MH_EMULATOR=127.0.0.1:5555 python3 gates/run.py --tier G2 --only capability-parity-gate,nightly-recovery
python3 scripts/adaptation/device_lab.py run --suite verify|exec|overlay    # 真机
./scripts/adaptation/release_dry_run.sh 0.4.69                               # G4 发布演练
python3 scripts/adaptation/bump.py                                           # 上游 bump 排练
python3 scripts/adaptation/gate_report.py                                    # 周报 scoreboard
```

## 完成定义（DoD）

- [ ] 改动在 framework 指定层，且 manifest/anchors/TARGETS/convergence 已同步；
- [ ] 有对应 gate（G0–G4 至少一层）并在本机通过；
- [ ] store/self 变体语义未被破坏（涉及构建时）；
- [ ] 证据已落盘、RSI 台账已记录；
- [ ] 模块 `AGENTS.md` 与相关合同文档已更新；
- [ ] 工作树干净、分支已推送。
