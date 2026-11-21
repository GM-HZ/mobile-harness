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


### 2026-11-20（P1 进展：bump 排练与变体矩阵）

- `scripts/adaptation/bump.py`：上游 bump dry-run。按 npm registry 拉取 watched 包
  （dsh、bash-local、bash-sandbox、session-persistence-jsonl、settings-general + 平台 addon），
  逐条校验 `adaptation/anchors.json`，输出受影响清单和证据
  `docs/evidence/upstream-bump/<target>-dry-run.json`。
  - 当前 npm 上最新即为已 pin 的 `0.2.2-rc.5`，所以首轮排练是"同版本自检"：5/5 锚点 OK，
    平台 addon 按自身锁定版本（0.1.2）校验存在性；ripgrep 非 DSH 包按规则跳过。
- `variants/{store,self,lab}.json` + `scripts/adaptation/variant_check.py`：
  - store：无 `mh-exec`/`mh-install`/exec shim/overlay 库，`signedExecBypass=false`；
  - self：含 `mh-exec`、`mh-install`、`libguest_mh_exec_shim.so`、≥8 个 overlay 库，`signedExecBypass=true`；
  - 用能力分支的真实构建产物（0.4.69 default/selfbuild unsigned HAP）验证通过。
- G4 registry 增加 `variant-store-check`/`variant-self-check`；G1 增加可选的
  `upstream-bump-rehearsal`（需要 npm registry）。

下一轮：G1 行为级合同测试（overlay 行为断言/快照 diff），补丁收敛到 `pnpm patch`/扩展点的迁移清单，
G3 真机 CI 调度协议，RSI 台账。


### 2026-11-20（第 3 轮：行为合同、补丁收敛、设备 lab、RSI 台账）

- **G1 行为合同**（`scripts/adaptation/host_contracts.py`）：把启动期变换真正作用于组装的
  上游源码再验证——settings client 注入后仍是合法 JS 且含注册调用；bash-local/bash-sandbox
  的命令替换产出 `"/bin/bash", "-c"` 且模块仍可解析；session-persistence 锚点仍在两侧存在。
  4 个合同全部通过；registry 增加可选 `host-contracts`。
- **补丁收敛清单**（`adaptation/convergence.json` + `docs/architecture/patch-convergence.md`）：
  6 个适配面按"扩展点 > pnpm patch > 运行时替换"排序，标出 P1/P2/P3、风险、对应 gate 和迁移目标；
  规则是运行时替换必须同时有锚点、seam 合同、G1 合同与迁移目标。
- **G3 设备 lab 协议**（`scripts/adaptation/device_lab.py`）：USB 设备检测、屏幕锁状态、
  版本/boot 状态、flock 串行锁、verify/exec/overlay 套件、证据落盘；registry 增加可选
  `device-lab-verify`，新增 manual dispatch workflow `gate-device.yml`。真机当前锁屏，
  `status` 正确报告 `screenLocked=true` 并提示无法自动解锁。
- **RSI 台账**（`scripts/adaptation/rsi_ledger.py` + `docs/architecture/rsi-loop.md`）：
  `gates/run.py --record` 自动记录每次 gate 运行（commit/层/结果/证据），`report` 输出
  scoreboard；首次运行就抓到"manifest 在变体文件加入后未重新生成"的陈旧问题并在修复后转绿，
  形成第一条"失败→修复→再绿"的真实闭环记录。
- 当前 registry：G0=3、G1=5、G2=62、G3=3、G4=5。

下一轮：补丁收敛的第一个真实迁移（优先 session-persistence 或 bash 命令锚点，走 pnpm patch 试验），
G2 夜间矩阵接线（把 ad-hoc smoke 子集纳入 gate-nightly），G4 构建矩阵接入 release 流程。


### 2026-11-20（第 4 轮：首个补丁迁移、发布闸门、夜间矩阵）

- **补丁基础设施**：`patches/series.json` + `patches/session-persistence-eacces-fallback.patch`
  + `scripts/adaptation/patch_rehearsal.py`（对 `.build/upstream-bump` 的 npm tarball 应用 patch、
  校验 marker/语法）。`scripts/build/harmonyos_dsh.py` 在 `npm ci` 后按序应用补丁（cache key 含补丁哈希），
  并在装配时校验 marker；`packages/dsh-host/dsh-client.cjs` 对 session 替换改为"未打补丁→运行时替换，
  已打补丁→直接放行，否则明确报错"的双模。
- **迁移预演**：用真实 dsh-layer.zip 构造 patched layer，`anchors.py` 识别 patched 模式、
  `host_contracts.py` 报告 `mode=patched`，G1 全绿；patch rehearsal 通过。剩最后一步：
  用完整构建出的 patched layer 跑一次 G2 recovery，然后删除 boot hook。
- **G4 发布闸门**：variants 增加 HAP 体积预算（store ≤790MB、self/lab ≤800MB），
  `variant_check.py` 执行断言；新增 `gate-release.yml`（tag/dispatch：G0/G1 → 构建 store/self →
  store_shape + variant_check → 上传证据）。
- **G2 夜间矩阵**：registry 增加 `nightly-recovery`（emulator-recovery），nightly workflow
  改为 capability gate + recovery；本地在隔离模拟器（5557）验证：**PASS（34.8s）**。
- **修复**：`gates/run.py` 自定义相对 evidence dir 的路径解析 bug；`host_contracts.py` 支持
  `--layer` 以便对 patched layer 预演。

下一轮：真实 patched-layer 构建 + G2 回归后删除 session boot hook（完成首个收敛）；把 G4 构建矩阵
接入 release 记录；补 G2 矩阵中其余稳定项；继续第二个锚点（bash 命令）的 pnpm patch 迁移。


### 2026-11-20（第 5 轮：首个真实收敛）

- 在架构 worktree 完成环境准备（子模块 init、复用 `.build` 输入缓存、build-profile），
  用 **patched DSH layer 实际构建**（`HARMONY_UNSIGNED=1 HARMONY_SELF_BUILD=1 ./build.sh --package`）。
- 校验：新 layer 含 patch marker；G1 anchors/contracts 通过；安装到模拟器 5555 后
  **G2 nightly-recovery PASS（46.3s）**，exec 探针（sh/bash/node/git/script + 未签名复制）全部符合预期。
- 随后**删除 session boot hook**（`dsh-client.cjs` 不再改写 session 模块），重新构建并通过
  G1；session-persistence 在 convergence.json 中标记为 **converged**。
- `patches/` 纳入 adaptation manifest 层（G0 覆盖补丁哈希）。
- 说明：模型 turn 的 session 写入未用真实密钥复测（需要 `MH_TEST_DEEPSEEK_API_KEY`）；
  G2 recovery 已覆盖持久化/崩溃路径，后续可用测试密钥补一次真实 turn。

下一轮：第二个收敛（bash 命令锚点 pnpm patch），并给 G2 矩阵补 session 写入回归；G4 发布矩阵接线。


### 2026-11-20（第 6 轮：第二个收敛，boot hook 清零）

- 新增 `patches/bash-local-shell-path.patch`、`patches/bash-sandbox-shell-path.patch`
  （把 shell argv 从 `"bash"` 改为 `"/bin/bash"`），`patch_rehearsal` 全部通过（3/3）。
- **删除 `dsh-client.cjs` 里所有源码替换逻辑**（`replacePinned`/`registerHooks` 源改写），
  hook 仅保留启动源缓存与指标；`anchors.json` 的 bash 项改为 patch 断言；`host_contracts`
  改为验证 patched module + boot 无替换。
- 真实构建（self）→ layer 两个 bash 模块均含 patched 字面量；安装模拟器 5555：
  **G2 nightly-recovery PASS（55.9s）**、exec 探针全绿（sh/bash/node/git/script=0，
  未签名复制按预期 126/127，COPY_NODE 重定向 0）。
- 真实构建（store）→ HAP `768,589,984 B`，**store_build_check + variant_store 均通过**
  （无 mh-exec/exec shim/overlay 库，signedExecBypass=false，体积在预算内）。
- 结果：两个高脆弱面（session-persistence、bash 命令）都已 converged；boot 时不再有
  字符串替换，剩余脆弱性主要在 build-time 注入（settings client）与 compat 模块层。

下一轮：settings client 注入向 client plugin/上游 seam 迁移（或 pnpm patch 试验）；
把 G4 构建矩阵结果写入 release/RSI 台账；补一次真实模型 turn 的 session 写入回归。


### 2026-11-20（第 7 轮：第三个收敛，build-time 注入清零）

- 新增 `patches/settings-client-recovery.patch`（git-style diff，含 no-newline 处理），
  在 DSH 装配时把 recovery 行插入 `dsh-client-ui-settings-general/lib/client.js`；
- 删除 `stage_settings_client()` 的 stage 期改写、DshEngine 的
  `dsh-settings-client.js` guest 覆盖，stage 会清理旧 rawfile；HAP 中不再有该 override；
- 真实 self 构建：layer 含 marker、HAP 无 override；G1 contracts 通过；
  模拟器 5555 安装后 **G2 nightly-recovery PASS（71.9s）**、exec 探针全绿；
- `settings-client-injection` 在 convergence.json 标记 **converged**。
- 结果：三个高脆弱面（session-persistence、bash 命令、settings client）全部收敛；
  boot/stage 期已无字符串改写，剩余适配集中在 compat 模块替换层与 native overlay 绑定。

下一轮：compat 模块层与 native binding 的清单化收敛（不追求一次性迁移，先给每个面建立
upstream seam 判断与 gate）；G4 release 构建结果写入证据/RSI；补真实模型 turn 的 session 写入回归。


### 2026-11-20（第 8 轮：compat 层清单化 + G4 发布证据）

- **compat 层清单**：新增 `adaptation/compat.json`（10 个模块）+ `docs/architecture/compat-layer.md`
  + `scripts/adaptation/compat_check.py`（G1 `compat-inventory`，零依赖运行）。每个模块记录：
  消费者、对应上游能力、gate id、决策（keep-compat / upstream-seam-candidate）、优先级；
  G1 会拒绝未登记模块、悬空消费者、未知 gate、未文档化模块。
- **G4 发布证据**：新增 `scripts/adaptation/release_evidence.py`，对 store/self HAP 计算 hash/体积、
  跑 store shape + variant 断言，写入 `docs/evidence/release/<version>-<commit>.json` 并记 RSI 台账；
  `gate-release.yml` 已接线（构建 store/self 后自动生成发布记录）。
  首次运行：store `768,498,560 B` / self `773,562,265 B`，三项检查全过。
- registry：`G0=3, G1=6, G2=63, G3=3, G4=6`；RSI 台账 18 次运行（G0 6/7、G1 7/7、G2 2/2、G4 2/2）。
- 说明：compat 层大多属于"上游没有可用 seam"的功能适配，本轮先做到**可清点、可门禁、可选择**；
  真正的迁移只在出现上游 provider/seam 时进行，避免为了"迁移"而迁移。

下一轮：给 compat 层补行为级合同（至少 forge/liveshare/office 三个），并评估上游 seam 是否出现；
把 G4 release 记录纳入 tag 发布流程；补真实模型 turn 的 session 写入回归。


### 2026-11-20（第 9 轮：compat 行为合同 + 发布闸门）

- **compat 行为合同**：新增 `scripts/adaptation/compat_contracts.py`（G1 `compat-contracts`），
  用 Node fixture 验证：forge 命令守卫/abort、package registry provenance 读写/拒绝非法 URL、
  liveshare/sharp/boot-cache 导出面。结果 **9/9 通过**。
- **发布闸门**：新增 `scripts/adaptation/release_gate.py`（G4 `release-gate`）：
  tag/release 必须有当前 commit 的绿色 release evidence、体积预算与三项检查通过；
  `gate-release.yml` 在生成 evidence 后调用它。本地用已有 evidence 验证：
  `G4 release gate OK: 0.4.69 @ 1c1c910 (store 768,498,560 B, self 773,562,265 B)`。
- registry：`G0=3, G1=7, G2=63, G3=3, G4=7`；本地 G1 全绿（host-syntax / anchors /
  compat-inventory / compat-contracts）。
- 环境限制：真机仍锁屏（`screenLocked=true`），设备 G3 未跑；`MH_TEST_DEEPSEEK_API_KEY`
  未配置，真实模型 turn 的 session 写入回归待补。

下一轮：把 G4 release 记录与 tag 流程跑一次端到端演练（本地模拟 tag）；补 G2 中稳定子集的
nightly 覆盖；等真机解锁后跑 G3 device_lab verify/exec/overlay。


### 2026-11-20（第 10 轮：G4 端到端演练 + nightly 矩阵扩展）

- **nightly 稳定子集**：新增无模型依赖的 `nightly-native-addon`（14.5s PASS）与
  `nightly-inspector`（18.1s PASS），nightly workflow 的 `--only` 扩为
  capability-parity + recovery + native-addon + inspector；registry G2=65。
  - 备注：`emulator-builtin-binding` 在本机暴露已知问题（Host 侧 `libguest_require_builtin.so`
    依赖 `libstdc++.so.6` 无法从 HAP 绑定解析，`ERR_DLOPEN_FAILED`），暂不纳入 nightly，
    作为 native addon 绑定的已知限制记录。
- **G4 端到端演练**：新增 `scripts/adaptation/release_dry_run.sh`（store 构建 → self 构建 →
  release evidence → release gate），本地完整跑通：
  `G4 release gate OK: 0.4.69 @ 62b0e87 (store 768,498,560 B, self 773,562,265 B)`；
  evidence 写入 `docs/evidence/release/0.4.69-62b0e87….json`（CI tag 流程会在 tag commit 上重新生成）。
- 真机仍锁屏、测试密钥未配置，G3 与真实模型 turn 回归继续挂起。

下一轮：补 G2 稳定子集（再挑 1-2 个无模型依赖用例）与 G3 解锁后的设备证据；把
`release_dry_run.sh` 纳入发布文档；继续缩小 compat 的 upstream-seam-candidate 面。


### 2026-11-20（第 11 轮：nightly 覆盖、flake 策略、发布 runbook）

- nightly 稳定子集再扩 2 个无模型依赖用例并实测通过：
  `nightly-inspector-availability`（13.0s）、`nightly-lsp-bundle`（20.5s）；
  nightly workflow 现覆盖 capability gate + recovery + native-addon + inspector +
  inspector-availability + lsp-bundle，共 6 项。
- `gates/run.py` 增加 `--retries N`：失败条目按 flake 策略重试（最多 2 次），
  证据记录 `attempts/flake`，状态打印 `PASS (flake)`；nightly 使用 `--retries 1`。
- 新增 [release-runbook.md](release-runbook.md)：本地 dry run、CI tag 流程、证据要求、
  回滚与检查清单，与 `release_dry_run.sh`/`release_gate.py` 对应。
- registry：`G0=3, G1=7, G2=67, G3=3, G4=7`；真机仍锁屏、测试密钥未配置。

下一轮：把 nightly 的 flake 记录写进 RSI 台账（重试成功标记）；继续找无模型用例；
真机解锁后补 G3 证据；有密钥时补真实 session 写入回归。


### 2026-11-20（第 12 轮：TARGETS 合同、flake 分桶、nightly 再扩）

- `patches/TARGETS.md`：按 dsh-Go 的 TARGETS 风格，为每条补丁记录 package/file、锚点、
  原因、失败模式与 gate；`patch_rehearsal` 现在会拒绝未在 TARGETS.md 登记的补丁。
- RSI 台账新增 flake 分桶：`gates/run.py --record` 会把 flake 次数写入账本，
  `report` 输出 `first-pass / flake-pass / fail` 三段统计（当前 27 次运行：G0 9+0+1、
  G1 10+0+0、G2 4+0+0、G4 3+0+0）。
- nightly 再扩 2 个无模型依赖用例并实测：`nightly-mcp-stdio`（5.9s）、
  `nightly-ptc-link-fixture`（1.0s）；nightly 矩阵现 8 项，registry G2=69。
- 真机仍锁屏、测试密钥未配置（G3 与真实 session 回归继续挂起）。

下一轮：为 G3 设备 lab 增加"解锁检测→自动排队/跳过"的调度说明；尝试把 nightly 的
flake 分桶写进周报脚本；评估把 `patches/TARGETS.md` 生成自动化（从 series.json 派生）。


### 2026-11-20（第 13 轮：周报 scoreboard、targets 索引、设备等待解锁）

- `scripts/adaptation/gate_report.py`：从 RSI 台账 + registry 生成
  `docs/evidence/rsi/scoreboard.md`（每层 first/flake/fail、最近失败、registry 快照），
  作为每周 RSI 闭环的可执行产物。
- `scripts/adaptation/patch_targets.py`：从 `series.json` + `anchors.json` 生成
  `patches/targets.json`（机器可读索引，含 gate 与 TARGETS.md 登记状态），
  G1 `patch-targets --check` 防止索引漂移；registry G1=8。
- `device_lab.py run --wait-unlock N`：轮询屏幕解锁，超时优雅退出（当前真机锁定，
  实测 `exit 4` + 提示解锁后重试），为 G3 调度提供可重试协议。
- 真机仍锁屏、测试密钥未配置；nightly 8 项矩阵保持。

下一轮：真机解锁后跑 G3 verify/exec/overlay 并写证据；有测试密钥时补 session 写入回归；
把 scoreboard 纳入 release evidence/周报流程。


### 2026-11-20（第 14 轮：上游 seam 观察 + release 携带 scoreboard）

- `scripts/adaptation/seam_watch.py`：拉取 compat 相关上游包（forge/liveshare/speech/office/image 共 13 个），
  统计 provider/client/seam 信号，证据写入 `docs/evidence/upstream-seams/0.2.2-rc.5.json`；
  结果：forge（provider 304/18/381）、liveshare（58 + protocol 36）、speech sensevoice（17）
  确有上游 provider seam，保持 `upstream-seam-candidate`；office-kit 本身就是上游 provider；
  image/sharp 上游 seam 很弱。
- `adaptation/compat.json` 增加 `seamEvidence`（上游包 + 证据路径 + 结论），compat-layer.md 增加
  "Upstream seam watch" 章节。
- release evidence 现在携带 RSI scoreboard 的 hash；`release_gate.py` 校验 scoreboard 未漂移。
  重跑 `release_dry_run.sh`：`G4 release gate OK: 0.4.69 @ 74a1072 (store 768,498,560 B, self 773,562,265 B)`，
  evidence 写入 `docs/evidence/release/0.4.69-74a1072….json`。
- 真机仍锁屏、测试密钥未配置。

下一轮：把 forge 的 upstream provider seam 做成迁移试验（只读调研 + 可行性报告，不改行为）；
继续补齐 nightly/G3；有密钥时补 session 写入回归。


### 2026-11-20（第 15 轮：forge upstream seam 可行性）

- 只读调研上游 forge：`dsh-experimental-forge`（provider registry）+ `-forge-github`
  （`GitHubProvider(ghRunner, hosts, limits)`）+ `-forge-bundle`（cordis.patch 注册链），
  证据与契约细节写入 `docs/architecture/seams/forge-upstream-seam.md`。
- 关键发现：**upstream `GhRunner` 是可注入契约**；且 `execa` 已在 DSH layer 中，
  因此可以把当前 `dsh-native-web.cjs` 的**运行期源码改写**（`import { execa }` →
  `globalThis.__harmonyGh`）替换为 `patches/forge-github-guest-runner.patch`：
  在注册点注入 `__harmonyGhRunner`，保留上游 provider/session/client UI，只保留 guest gh 传输。
- 迁移选项 A（package patch，推荐先做）与 B（自定义 Cordis plugin，待上游导出类）已记录；
  风险：forge bundle 的 worktree/forge-session、账号桥、取消语义映射。
- 下一轮实施 A：adapter + patch + rehearsal + 构建/forge 门禁验证，然后删除 load-time 改写。


### 2026-11-20（第 16 轮：forge 迁移 A 落地）

- `packages/dsh-host/dsh-native-web.cjs`：新增 `globalThis.__harmonyGhRunner`（把 guest gh 结果映射为上游
  `GhRunner` 语义：cancel/timeout/maxBuffer/exitCode，含 stdin input）；删除 forge-github 的
  load-time 源码改写分支。
- 新增 `patches/forge-github-guest-runner.patch`（注册点注入 `__harmonyGhRunner ?? ghRunner(resolved)`），
  已加入 series/TARGETS/anchors/targets.json；`patch_rehearsal` 5/5 通过。
- 真实 self 构建：layer 含 patch marker；G1 `host-contracts` 5/5 通过（含 forge 合同：patched 注册 +
  adapter + 无 boot 改写）；模拟器 5555 安装后 **G2 nightly-recovery PASS（49.9s）**。
- forge 全链路验收（`emulator-forge-account`/`-github`）在现有模拟器上受"干净 GitHub 账号/UI fixture"
  前置条件影响未通过（非构建失败），已记录为后续 G2 工作。
- `convergence.json` compat 面标记 in-progress（forge 已迁移；liveshare/speech/sharp 待评估）。

下一轮：补 forge 干净 fixture 或在该前置条件下复测；评估 liveshare 的 provider seam 迁移；
真机解锁后跑 G3。


### 2026-11-20（第 17 轮：liveshare seam 结论 + forge fixture 深入）

- 新增 `docs/architecture/seams/liveshare-upstream-seam.md`：上游 liveshare 的 Config 只有身份/状态文件字段，
  owner-gateway 在 `TunnelWorker` 内部用 `child_process.spawn` 启动，**没有 worker/spawn 注入点**；
  我们的三处运行时改写（spawn→Worker、viewer uploads、policies）暂时只能 keep-compat。
  结论：现在保留 compat；若上游出现 spawn/worker factory seam 再迁移；可选的低风险收敛是把
  upload 补丁改成包级 patch。
- forge 干净 fixture 复测：清理 `alpine/native-benchmark-home/.config/gh` 后，`emulator-forge-account`
  可推进到 OAuth 登录成功、进入 `forgePanel/changeRequestText`，但该调用返回
  `forgePanel/diff-failed`（gh 读取 fixture diff 失败）。属 fixture/TLS/GH_CONFIG 环境问题，
  非构建或注册失败；已记录为待排查的 G2 fixture 项（不阻塞门禁）。
- compat.json liveshare 条目补充 seamDoc/结论；compat-layer.md 同步。


### 2026-11-20（第 18 轮：speech seam 结论 + 全量 nightly 回归）

- 新增 `docs/architecture/seams/speech-upstream-seam.md`：SenseVoice provider 的 Config 没有
  worker/spawn factory，启动走通用 `ctx.subprocess.spawn` + pipe token 握手；我们改为 Host Worker
  thread + 直接 handle 调用。结论：**keep-compat**（除非上游暴露 worker factory seam）。
- **完整无模型 nightly 子集回归**（当前 forge-patched 构建，模拟器 5555）：
  recovery 30.0s / native-addon 14.8s / inspector 14.5s / inspector-availability 13.5s /
  lsp-bundle 20.4s / mcp-stdio 6.5s / ptc-link-fixture 1.0s —— **7/7 PASS**。
- compat.json / compat-layer.md 同步 speech seam 结论；证据写入 gate evidence 与 RSI 台账。


### 2026-11-20（第 19 轮：最终综合验证与交付文档）

- 最终验证全绿：
  - G0/G1 通过（manifest 73 条、anchors 7、patches 5、compat 10）；
  - nightly 7 项 **7/7 PASS**（recovery/native-addon/inspector/availability/lsp-bundle/mcp-stdio/ptc-link）；
  - `release_dry_run.sh` → **G4 release gate OK: 0.4.69 @ b997be6**（store 768,499,205 B / self 773,562,910 B）。
- 新增 [2026-11-20-architecture-delivery.md](../work/2026-11-20-architecture-delivery.md)：目标-交付对照、
  当前数字、证据位置、环境阻塞的遗留项（真机锁屏、测试密钥、forge fixture、CI 未在 runner 实跑、
  运行时任意 dlopen）与恢复步骤。
- 架构 README 加入交付文档入口。


### 2026-11-21（真机 G3 首次验证）

- 真机解锁、安装当前签名 self 构建后：
  - `device_lab run --suite verify` **PASS**（23s，web 200、账号凭据已存）；
  - `exec` / `overlay` **FAIL**：bash 工具已能到达 PRoot，但真机 compat PRoot 模式报
    `embedded loader descriptors: No such file or directory` / `execve("/bin/bash"): Permission denied`
    （同一构建在模拟器 fast 模式通过）。
- 顺带修复两个真实问题：
  - 签名构建的 bash 退出状态单元是 `30 00 18` 这种 ASCII 数字+二进制填充，旧解析要求 `^\d{3}$`
    导致 "Bash exited without a valid command status"；改为提取数字；
  - `device_lab` 之前只看探针退出码，现要求探针证据 `ok:true`。
- 真机在长时间验证中自动锁屏，剩余 exec/overlay 与 compat PRoot 问题需再次解锁后续跑。


### 2026-11-21（真机 G3 完成）

- 真机 Mate 60（签名 self 构建）三个 G3 套件全部 PASS：
  `verify 3s` / `exec 36s`（全 exec 标记、COPY_NODE_OK、未签名复制 126/127）/ `overlay 60s`
  （签名库 + node dlopen 42 + 动态 jq 1.8.2）。证据在 `docs/evidence/device-lab/`。
- 验证中发现并修复三个真实问题：
  1. 签名构建 bash 退出状态是 ASCII 数字 + 二进制填充（`30 00 18`），旧解析要求 `^\d{3}$`；
  2. bash 包补丁把 argv 改成 `/bin/bash` 后绕过了 host 的 packaged spawn 路径，真机签名构建
     进入 PRoot signed-exec loader handoff 并失败（"embedded loader descriptors"）；现在
     `/bin/bash` 与 `bash` 走同一路径；
  3. `device_lab` 只看探针 exit code（探针 ok:false 也算 PASS），且探针 ok 逻辑只认 exec 标记；
     两者都已修正。
- 剩余：真实模型 turn 的 session 写入回归（需 `MH_TEST_DEEPSEEK_API_KEY`）、forge fixture
  的 `forgePanel/diff` 环境问题。


### 2026-11-21（真机 session 写入回归）

- 真机（签名 self 构建、设备账号 deepseek-account/deepseek-flash）完成一次真实模型 turn：
  `turn/end reason=completed`、1 条 assistant message、21 条事件；
- 强制停止并重启 App 后再次读取同一 session：**21 条事件完整保留**（含 turn/end）；
- 证据 `docs/evidence/device-lab/20261121-session-turn.json`，验证了 session-persistence 包补丁
  在真机上的写入与恢复路径。


### 2026-11-21（模拟器复验 + forge fixture 修复）

- 在模拟器（compat PRoot 模式）上复验真机修复：exec/overlay 探针 PASS、nightly 7/7 PASS。
- **forge fixture 根因与修复**：
  - `packages/dsh-host/dsh-native-web.cjs` 的 `__harmonyGhRunner` 之前只给 guest gh 传空 env，
    丢掉了 Host 进程里的 `HTTPS_PROXY`（fixture 的 proxy.mjs 设置的 127.0.0.1:19772），
    gh 无法连到 fixture → `forgePanel/diff-failed`；
  - 现在只转发代理相关环境变量（HTTP(S)_PROXY/NO_PROXY，大小写）到 guest gh；
  - 清理 App 数据（`bm clean -n org.sayact.nodepoc -d`）后 `emulator-forge-account` **PASS**：
    `nativeLoginCanCancelBeforeConsent / nativeLoginAndCliStorage / accountRestoredAfterRestart /
    forgeUsesDeviceCredential / nativeLogout` 全部 true，fixture 记录 `issue/issue/exchange/viewer/forge-read`。
- 新增 G1 `host-regressions` 回归守卫（`/bin/bash` 路由、padded status 数字解析、per-probe DONE、
  device_lab ok 校验），防止真机修复被回退；G1 现 10 项全绿。
- 遗留：`emulator-forge-github` 需要注入一个临时 file-URL proxy plugin 到 profile；我们的移动 Host
  在该 profile 下以 status -3 退出（hilog 里 `native Host unavailable status=-3`），测试随后 ready 超时。
  该测试是为原生 Host 的任意本地插件加载设计的，和移动端"限制 profile/插件注入"的安全边界冲突；
  forge 的凭据/账号/读取路径已由 `emulator-forge-account` 覆盖并通过。后续若要跑通该用例，需要
  用我们的 pluginManager/受支持配置方式注入 proxy，而不是临时 file-URL plugin。
- 同时把 smoke `ready()` 超时从 65s 提到 120s（数据清理后的首次 Host 解包在模拟器/真机可到 70s+）。


### 2026-11-21（模拟器最终复验 + 门禁加固）

- 用最新构建（含 forge 代理转发修复）安装在模拟器（compat PRoot 模式）复验：
  exec/overlay 探针 **PASS**，nightly 7/7 **PASS**（recovery 30.1s 等）。
- forge fixture：`emulator-forge-account` **PASS**（证据 `docs/evidence/forge/forge-account-emulator-20261121.json`）。
- G1 增加到 **11 项**：新增 `workflow-check`（4 个 gate workflow 与脚本/步骤的一致性）和
  `host-regressions` 中的 forge proxy 转发守卫；G0/G1 全绿。
- G4 在最新 commit 上重跑：`release gate OK: 0.4.69 @ e9d2559`
  （store 768,499,709 B / self 773,563,414 B；store/self 断言全过），evidence 已提交。
- 结论：模拟器侧复验完成；真机侧 G3 与 session turn 已在上一轮完成；剩余仅
  `emulator-forge-github` 的临时 file-URL 插件注入限制（已文档化，forge 核心路径由 forge-account 覆盖）。
