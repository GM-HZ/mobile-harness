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
