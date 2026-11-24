# Mobile Harness 框架（分层、所有权与硬规则）

本文件是仓库的"宪法"：定义每类改动应放在哪一层、层与层之间靠什么契约连接、什么做法被禁止。
它描述**当前状态**；历史与决策过程在 `docs/work/`。

## 1. 分层

```
L5 App / 平台宿主     apps/harmonyos (ArkTS + CMake)          —— 生命周期、模式、rawfile 装配
L4 原生运行时         runtime/harmonyos/native (C/CMake)       —— PRoot、shell、workflow、shim、N-API
L3 打包/装配          runtime/harmonyos/packaging, scripts/build —— 输入 pin、DPH layer 装配、patch 应用
L2 兼容层             runtime/harmonyos/compat (JS)            —— 上游没有 seam 的能力适配
L1 Host 运行时 overlay packages/dsh-host (CJS/MJS)             —— 启动注入、模块级 patch、桥
L0 上游 DSH           runtime/harmonyos/dsh/package-lock.json  —— 官方 npm 包（不 fork）
L0' 上游 vendored     vendor/repos/* (子模块)                  —— Node/PRoot/Termony/Dshm/TS 等
G  门禁/证据         gates/, scripts/adaptation/, docs/evidence
```

**核心原则：L0 永远不改源码。** 对上游的修改只能是：上游扩展点（plugin/bundle/provider）→
`patches/` 包级补丁 → 最后才是 L1 运行时 patch（且必须有锚点与合同）。

## 2. 所有权（一条事实只有一个家）

| 内容 | 家 |
| --- | --- |
| 上游版本与输入 hash | `versions.lock.json` + `docs/build-inputs.sha256` + `docs/guest-tools-lock.json` |
| 适配面清单 | `adaptation/manifest.json`（自动生成） |
| 锚点/补丁/目标 | `adaptation/anchors.json`、`adaptation/anchors.full.json`、`patches/series.json`、`patches/TARGETS.md`、`patches/targets.json` |
| 收敛状态与迁移目标 | `adaptation/convergence.json` |
| compat 决策 | `adaptation/compat.json` + `docs/architecture/compat-layer.md` |
| 上游接触点合同 | `docs/architecture/seams/*.md` |
| 门禁定义/运行/证据 | `gates/registry.json`、`gates/run.py`、`docs/evidence/gates/` |
| 构建变体 | `variants/{store,self,lab}.json` + `scripts/adaptation/variant_check.py` |
| 发布记录/闸门 | `scripts/adaptation/release_evidence.py`、`release_gate.py`、`docs/evidence/release/` |
| RSI 台账/周报 | `docs/evidence/rsi/ledger.jsonl`、`scoreboard.md` |
| 模块开发规则 | 各目录 `AGENTS.md` |

## 3. 硬性不变量

1. **manifest 覆盖**：新增/删除/改名任何适配文件，必须重生成 manifest 且 G0 通过。
2. **补丁闭环**：`series.json` 的每条补丁必须能在 `patch_rehearsal` 中应用到 pin 的 tarball，
   必须在 `TARGETS.md` 有行，必须有 Gate（至少 G1）。
3. **锚点闭环**：`anchors.json` 的每个锚点要么是字面量、要么是 patch marker，必须能被
   `anchors.py` 在当前工作树的装配层上校验；bump 时全量重验。
4. **boot 期零字符串改写为默认**：session/bash/settings 已收敛；新的运行时改写需要
   convergence 条目 + 迁移目标，否则不合并。
5. **变体隔离**：store 无 loader/shim/overlay；self 有；lab 固定全组。G4 断言强制。
6. **凭据边界**：真实 token 不落仓库/证据；设备夹具只跑 loopback 模拟器。
7. **输入不可变**：构建所需外部输入走 `docs/build-inputs.sha256` / lock；禁止构建时隐式下载未 pin 文件。
8. **证据可追溯到 commit**：每个 gate/release 证据包含 commit；release gate 只认当前 commit 的绿色记录。

## 4. 改动落点决策树

```
需要改变行为？
├─ 上游已有 plugin/bundle/provider/slot 扩展点？ → 写 bundle/plugin（不改上游源码）
├─ 上游 npm 包内小修？                          → patches/<pkg>@<ver>.patch + series/TARGETS
├─ 需要 mobile 专有的宿主/平台能力？             → L1 host overlay（packages/dsh-host）或 L4 native
├─ 上游能力在手机上无法原样运行？                → L2 compat（必须登记 compat.json + gate + seam doc）
└─ 只是构建/打包/输入问题？                      → L3 packaging/scripts（更新 pin 与 sha256）
```

禁止：把业务逻辑塞进 `DshEngine.ets`；在 `dsh-native-web.cjs` 里新增未登记的 patch 函数；
用 `globalThis.__x` 传业务状态（必须有名有主的 service 或显式参数）。

## 5. 补丁/适配生命周期

1. 选型：确认上游无 seam，记录到 `convergence.json`（target 与优先级）。
2. 实现：`patches/` 或 host overlay / compat / native。
3. 验证：`patch_rehearsal`、`anchors.py`、`host_contracts.py`、对应 G2/G3 用例。
4. 证据：gate 证据 + 台账；需要设备时 `device_lab`。
5. 收敛：上游出现 seam 时按 `convergence.json` 迁移并删除运行时改写。
6. 锚点映射：构建后运行 `python3 scripts/adaptation/anchor_scan.py --map --layer <dsh-chunks.json>`，
   把每个字面量锚点映射到装配层模块；`anchors.full.json` 同时是 bump 全量校验的输入。
   重复出现的锚点标记 `layerAmbiguous`，只做存在性覆盖、不做 drift 判定。

## 6. 上游 bump 流程

1. `scripts/adaptation/bump.py`（dry-run：拉 npm 包、逐条锚点、列受影响 manifest 条目）；
2. 更新 `versions.lock.json`/lock/子模块 gitlink；
3. 应用到 `patches/` 的包版本（`patch_rehearsal`）；
4. 构建 store/self（或 release dry run）；
5. G0–G4 全绿 + 证据 → 合并；失败项按锚点定位到 manifest 条目。

## 7. 门禁与证据模型

| 层 | 触发 | 内容 |
| --- | --- | --- |
| G0 | 每次改动/PR | manifest、pin、子模块、补丁索引、workflow 接线 |
| G1 | 每次改动/PR | host 语法、锚点、host 行为合同、compat 清单/合同、真实设备回归守卫 |
| G2 | nightly/合并前 | capability gate + 无模型 nightly 子集（模拟器） |
| G3 | 设备在线/lab | verify/exec/overlay + forge 等；解锁检测、flock、证据 |
| G4 | 发布/每日 | store/self 构建、形状/体积断言、release evidence + gate |

证据目录与 schema 由 `gates/run.py` 统一写入；`docs/evidence/rsi/ledger.jsonl` 记录每次运行，
`gate_report.py` 生成周报。flake 重试上限 2 次并单独计数。

## 8. 已知边界（不要假装支持）

- 运行时下载任意未签名 `.so` 的 `dlopen`：不支持（只有构建期签名 overlay）；
- PTY/终端：平台限制，已延期；GUI 自动化/容器/systemd 等：不在范围；
- 真机夹具（forge 等）只接受 loopback 模拟器；真机用真实账号走真实网络；
- 真机屏幕锁定时 `aa start` 会被系统拒绝：用 `device_lab.py run --wait-unlock` 或先解锁。

## 9. 相关文档

- 能力矩阵与新增功能落点：[feature-roadmap.md](feature-roadmap.md)
- 补丁收敛清单：[../architecture/seams/](../architecture/seams/README.md)、`adaptation/convergence.json`
- 发布 runbook：[release-runbook.md](release-runbook.md)
- 交付与证据：[../work/2026-11-20-architecture-delivery.md](../work/2026-11-20-architecture-delivery.md)
