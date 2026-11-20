# Adaptation and gate architecture (2026-11-20)

目标：让 Mobile Harness 在**持续追上游 DSH** 的同时，把我们在不同层面打的补丁变成
可清点、可验证、可回滚、可自动回归的体系，并最终形成 RSI（自改进闭环）式的门禁：
每次上游升级/每次改动都由同一套 gate 证明，失败自动进 backlog，发布只认 gate 证据。

参考体系：
- 核心 `/Users/gongmeng/dev/code/deepseek-harness`：all-plugin Cordis、profile/bundle 组合、
  `patches/` 只放第三方 npm 依赖补丁、大量分域 CI（ci/ci-master/e2e/expected-filenames/
  pr-check-*/release-*）、`docs/architecture.md` + `capability-seams` + `.agents/notes` 决策记录。
- 同类 `/Users/gongmeng/dev/code/dsh-Go`：`runtime/patches/series`（quilt 式补丁序列 + TARGETS）、
  `docs/maintenance/*-contract.md`（60+ 维护合同）、`docs/official-parity.md` 官方功能对照、
  `tooling/ohos/run-gates.sh` 门禁矩阵、CI（pr-gate/ci/goldens/runtime/ohos-compile/iOS 系列）。

## 1. 现状清点

上游输入（pin 层）：

| 输入 | 位置 | 说明 |
| --- | --- | --- |
| DSH 官方包 | `runtime/harmonyos/dsh/package-lock.json` | 0.2.2-rc.5 npm 装配，不改上游源码 |
| 子模块 | `.gitmodules` / `vendor/repos/*` | dsh、node、proot、dshm、termony、typescript(-language-server)、pyright |
| 构建输入 | `docs/build-inputs.sha256` | Node/PRoot/DSH layer 等不可变输入 |
| guest 工具/库 | `docs/guest-tools-lock.json` | Alpine APK + 新增 libraries/extensions overlay |

适配面（按层）：

| 层 | 位置 | 形式 | 脆弱点 |
| --- | --- | --- | --- |
| L1 Host 运行时 overlay | `packages/dsh-host/*`（13 个文件） | 启动时 `registerHooks`/模块替换/`replacePinned` 字符串锚点 | **高危**：锚点是上游源码字符串，RC 升级即断 |
| L1 Web 客户端注入 | `runtime/harmonyos/web/*` → settings client | 字符串注入到上游 `dsh-client-ui-settings-general` | 高危 |
| L2 兼容 shim | `runtime/harmonyos/compat/*`（10 个文件） | 替换/包裹上游能力（forge/liveshare/office/speech/package/pnpm/sharp/inspector/boot cache/fetch shim） | 中高 |
| L2 诊断 | `runtime/harmonyos/diagnostics/*` | seccomp/probe 脚本 | 低 |
| L3 原生运行时 | `runtime/harmonyos/native/*` | poc/dsh-shell/workflow/ptc/shim/loader/addon | 中（与 ABI/平台强相关） |
| L3 打包 | `runtime/harmonyos/packaging/*` | 构建/装配脚本，输入哈希校验 | 中 |
| L4 App/平台 | `apps/harmonyos/**`（ArkTS + CMake） | 宿主、DshEngine、native 插件 | 中 |
| L5 变体开关 | `HARMONY_SELF_BUILD` / `HARMONY_GUEST_LIB_GROUPS` / `HARMONY_UNSIGNED` / signing profile | 环境变量 + 编译宏 | 低（但缺矩阵化验证） |
| L6 测试与证据 | `tests/smoke/*`、`tests/bench/*`、`docs/evidence/*` | 手工/脚本运行，证据靠约定 | **无强制门禁** |

现有 CI 只有 `.github/workflows/harmonyos.yml`（手动 dispatch，self-hosted macOS，构建 unsigned HAP）。
门禁实际是"人工按需跑脚本"，没有 PR 门禁、没有 nightly、没有 flake 记录、没有发布闸门。
这就是"还不是自闭环"的核心原因。

## 2. 目标架构

### 2.1 单一适配清单（adaptation manifest）

`adaptation/manifest.json` 由 `scripts/adaptation/inventory.py` 生成，逐条记录：
`id / layer / kind / source / destination / sha256 / upstreamTouchpoints / fragility / gates / owner`。
任何 overlay、原生 shim、输入 pin、变体开关都必须出现在清单里；CI 的 G0 用
`scripts/adaptation/verify.py` 校验清单与工作树一致（文件缺失、哈希漂移、锚点失效直接失败）。

### 2.2 版本锁定图（versions.lock.json）

把"上游是谁"固定成一份可 diff 的 JSON：DSH 版本 + npm lock 哈希 + 各子模块 gitlink +
`docs/build-inputs.sha256` 哈希 + `docs/guest-tools-lock.json` 哈希 + Node 版本。
升级 = 改这份文件 + 走 bump 流程，其它层不许各自记版本。

### 2.3 上游 seams 与合同文档

对齐 deepseek-harness 的 `capability-seams` 与 dsh-Go 的 `maintenance/*-contract.md`：
`docs/architecture/seams/` 下每个高脆弱适配点一份合同文档，写清：
上游包/文件/锚点、我们依赖的行为、失败模式、对应 gate、历史破坏记录。
首期先写 6 份最关键的：bash-local/bash-sandbox 替换锚点、settings client 注入、
dshm hostcore 接口、PRoot preloader/loader 行为、npm 装配 pin、guest 工具/库 overlay。

### 2.4 门禁分层（gates）

| 层 | 名称 | 内容 | 运行时机 |
| --- | --- | --- | --- |
| G0 | 静态/一致性 | manifest 校验、输入/锁哈希、子模块 pin、许可证/NOTICE、禁止文件 | 每次 PR / 本地 pre-commit |
| G1 | Host 合同 | host overlay/compat 模块单测、锚点快照、模块装配 dry-run | 每次 PR（macOS runner） |
| G2 | 模拟器能力 | 现有 `capability-parity` 10 步 + exec/overlay/liveshare/语音等 | nightly + 合并前 |
| G3 | 真机实验 | mate60-verify/exec/native-overlay/liveshare | 设备在线时 / release 前 |
| G4 | 构建与发布 | store/self/lab 变体构建、HAP 体积预算、store 构建不含 shim/overlay、signed/unsigned 哈希、证据打包 | 发布前 + 每日 dry-run |

`gates/registry.json` 是门禁的机器可读定义；`gates/run.py`（下一步）按层执行并写
`docs/evidence/gates/<gate>/<commit>.json`，失败自动生成 issue 草稿。

### 2.5 变体矩阵

把"上架 build / 自建 build / 实验 build"从口口相传的环境变量升级为一等公民：
`variants/{store,self,lab}.json`（启用哪些 overlay、exec shim、库组、签名），
G4 对每个变体做构建断言（例如 store 不得包含 `/usr/bin/mh-exec`、不得出现 `LD_PRELOAD`）。
现有 `HARMONY_SELF_BUILD` / `HARMONY_GUEST_LIB_GROUPS` 保持兼容，变体文件生成这些环境变量。

### 2.6 上游 bump 流程

1. `scripts/adaptation/bump.py --dsh <version>`：拉取新 npm 包到缓存，对比旧 pin；
2. 运行 `verify.py`：所有锚点/文件/子模块一致性检查，输出兼容性报告；
3. 构建 + G0/G1/G2 门禁；失败项自动映射到 manifest 条目（哪个补丁要改）；
4. 通过后更新 `versions.lock.json` 和证据，一次 PR 提交。
5. 每次逃逸的线上问题必须回流为 G2/G3 的一个新 gate case（RSI 规则）。

## 3. 迁移路线

**P0（本轮已开始）**：目录与清单骨架
- `docs/architecture/*`、`adaptation/manifest.json`（自动生成）、`versions.lock.json`、
  `gates/registry.json`、`scripts/adaptation/{inventory,verify}.py`；
- 生成现状清单并提交，作为后续所有重构的基线。

**P1（下一轮）**：G0/G1 可执行
- `gates/run.py` 实现 G0（verify + hashes + submodule/pins）与 G1（host overlay 冒烟/锚点快照）；
- 新增 GitHub Actions：`gate-pr.yml`（G0/G1）、`gate-nightly.yml`（G2 emulator，self-hosted macOS）；
- 证据目录与 schema（`docs/evidence/gates/…`），失败自动开 issue。

**P2**：补丁收敛
- 把 L1 的字符串替换逐步迁移到 `pnpm patch`（上游 npm 包补丁）或 Cordis 扩展点/bundle；
- 为每个高危 seam 写合同测试（锚点不存在即 fail），把 `replacePinned` 的隐式假设显式化；
- 完成一次真实 DSH bump 演练（记录耗时与破坏点）。

**P3**：RSI 闭环
- flake 台账（重试策略 + 历史通过率），gate scoreboard；
- 发布闸门：只有 G0–G4 全绿且证据齐备才能打 tag/发布；
- 每周自动生成 gate 覆盖与失败趋势报告，逃逸问题回流为 gate case。

## 4. 风险与开放问题

- 子模块 + 大输入（HAP/Node/PRoot）使 CI 机器很重：G2/G3 只能跑在 self-hosted/真机 lab；
- npm 装配 pin 与子模块 pin 可能不一致（当前 DSH 用 npm 0.2.2-rc.5，子模块是另一路径），
  需要在 P1 明确"唯一上游来源"；
- L1 的运行时字符串替换是最脆弱资产，收敛到 pnpm patch 需要上游包发布结构稳定；
- 真机 gate 依赖用户在线，需要"设备可用即跑、失败可重试"的异步模型。

## 5. 参考要点摘录

- deepseek-harness：核心全插件，**没有必须改的特权 core**；优先用 profile/bundle/plugin 扩展；
  第三方依赖用 `patches/`（pnpm patch），并用大量分域 CI + `expected-filenames` +
  capability-seams 文档约束适配面。
- dsh-Go：`runtime/patches/series` 用一个序列文件管理 20+ 上游补丁（含应用顺序与
  TARGETS.md），配合 `docs/maintenance/*-contract.md`（每个行为合同一个文档）与
  `tooling/ohos/run-gates.sh` 门禁矩阵；CI 分 pr-gate/ci/goldens/runtime/ohos-compile。


## 6. 实施进度

### 2026-11-20（P0 完成，P1 进行中）

已落地：

- `adaptation/manifest.json`（60 条，自动生成）+ `versions.lock.json` + `scripts/adaptation/{inventory,verify}.py`
  —— `python3 gates/run.py --tier G0` 为绿；
- `adaptation/anchors.json` + `scripts/adaptation/anchors.py`（bash-local/bash-sandbox 命令锚点、
  session-persistence 锚点、settings client 锚点、native addon/ripgrep 存在性）；
  `scripts/adaptation/host_checks.py`（23 个 host/compat overlay 的 `node --check`）
  —— `python3 gates/run.py --tier G1` 为绿（本地用能力分支组装的 dsh-layer.zip 校验 6 个锚点通过）；
- `gates/run.py`（按 registry 运行、占位符跳过、exit 2 视为环境不可用、逐 commit 证据）；
- CI：`.github/workflows/gate-pr.yml`（PR 跑 G0+G1，ubuntu）与
  `.github/workflows/gate-nightly.yml`（self-hosted macOS 构建+安装+跑 G2 capability gate）；
- G4 增加 `scripts/adaptation/store_build_check.py`（store HAP 不得包含 mh-exec/exec shim/overlay 库）。

未完成（下一轮继续）：

- G1 的 host 合同测试（overlay 行为级断言，锚点快照 diff）；
- `scripts/adaptation/bump.py` 上游 bump 排练（先对 0.2.2-rc.5 → 下一 RC dry-run）；
- store/self/lab 变体矩阵（`variants/*.json`）与 G4 尺寸/特性预算；
- 真机 G3 的 CI 调度（等设备可用性协议）；
- RSI 闭环：flake 台账、失败自动 issue、发布闸门与周报。
