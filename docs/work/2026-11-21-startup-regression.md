# 启动时间回归调查（2026-11-21）

分支：`codex/harmonyos-experience`（基于 `main` @ a3ce284）
目标：找出"优化后约 10s，后来变慢"的原因，并给出优化方案。

## 1. 现状测量（模拟器 127.0.0.1:5557，当前构建）

用 `scripts/adaptation/startup.py` 采集；证据：
`docs/evidence/startup/cold-baseline.json`、`warm-baseline.json`。

### 冷启动（清理解包 marker 后，相当于全新安装/升级后首次启动）

| 阶段 | 耗时 |
| --- | --- |
| 准备与解包（总） | **25.1s** |
| ├ node-layer.zip | 0.12s |
| ├ shell-tools / extras / pnpm | 0.45s |
| ├ workspace-python-v1.zip | 1.6s |
| └ **dsh-layer.zip** | **22.7s** |
| native Host 启动（startNative → loopback ready） | 7.2s |
| ArkWeb 加载 | 5.0s |
| **合计** | **约 40s** |

### 温启动（解包 marker 命中，正常打开 App）

| 阶段 | 耗时 |
| --- | --- |
| 准备（copyGuest/时区/DNS 等） | 0.2s |
| native Host 启动（ability foreground → loopback ready） | ~6.2s |
| ArkWeb 加载 | ~2.6-3.4s |
| **合计** | **约 10-11s** |

历史对照（`docs/releases.md` / `docs/evidence/native-web-comparison-0.4.6.json`）：
- 0.4.6 Mate 60 冷启动 → 聊天页 **10.2s**（Host loopback 6.95s + Web 2.76s）；
- 全新安装模拟器首次启动 **15.4s**（dsh-layer 解包 8.6s）；
- 0.4.23 模拟器冷启动 15.6s、强停重启 6.0-7.5s。

## 2. 结论

**温启动基本没坏（约 10-11s，接近历史值）**；回归主要发生在**首次启动/升级后首次启动**：

1. `dsh-layer.zip` 从早期规模增长到 **332MB（解压后 1.08GB、99,770 个文件）**，
   解包从 8.6s → **22.7s**；
2. 层内大体积可选内容占比高：
   - libreoffice-kit-wasm **152MB**（Office 预览）
   - speech onnxruntime **34.6MB**
   - inspector **25MB**（开发用）
   - node-pty prebuilds **24MB**（PTY 已延期，实际不用）
   - pyright **19.5MB** + LSP TypeScript **~48MB**
   - forge/liveshare/documentpreview 等各 10-24MB
3. Host 启动加载 5,771-6,295 个模块（历史 ~5,004），profile/LSP/扩展使 Host 约 6-7s；
4. WebView 加载 2.6-5.0s（冷启动时更长）。

也就是说：**每次安装/升级后都会按新的 runtime identity 全量重解 1.08GB**，
用户感知到的"启动变慢"主要是这一段；温启动没有 22s 的解包。

## 3. 优化方案（按收益排序）

### P0：拆分 dsh-layer，减少首次解包
1. 把可选大块拆成独立 archive，按需/后台解包，核心层只保留聊天与工具链必需：
   - `office-layer.zip`（libreoffice wasm）——首次打开 Office 预览时解包；
   - `speech-layer.zip`（onnx/sherpa）——首次语音输入时解包；
   - `lsp-layer.zip`（pyright + typescript LSP）——LSP 启用时解包；
   - `devtools-layer.zip`（inspector 等）——self/调试构建才包含；
   - PTY prebuilds 直接不进包（PTY 已延期）。
2. 目标：核心层解压后 ≤ ~400MB、解包 ≤ 8s；首次启动恢复到 15-20s，温启动 ≤ 10s。
3. 拆分后仍要保证 profile 挂载前所需包已就位；可选能力未解包时，对应 bundle 延迟挂载/禁用，
   不影响核心聊天。

### P1：升级时增量解包
- 维护 `name → (size, crc32)` 清单；新 layer 与旧清单比较，只解压新增/变化文件；
- 保持旧解压目录（不删除），避免每次升级全量 1.08GB；
- 目标：升级后首次启动 ≤ 15s。

### P1：并行解包
- 6 个 archive 目前串行；dsh-layer 之外约 2.2s，可并行重叠；
- 拆分后各 feature layer 可并行或后台解包。

### P1：Host 启动优化
- profile 默认 bundle 精简：LSP/forge/liveshare 等非核心 bundle 延迟挂载；
- 目标：Host loopback ≤ 4s（当前 6-7s）。

### P2：copyGuest 去重
- 目前每次启动从 rawfile 复制 25+ 文件；可按 rawfile 大小/mtime 缓存，预计节省 100-300ms。

## 4. 验收

- `scripts/adaptation/startup.py --warm/--cold` 纳入回归，记录冷/温启动证据；
- 温启动 ≤ 10s（模拟器目标，真机另测）、冷启动（清 marker）≤ 20s；
- 升级后首次启动 ≤ 15s；
- 启动阶段日志与证据落盘，列入第一可用版本 P0 清单。


## 5. 已实施（第一轮）

### 5.1 dsh-layer 瘦身 + 可选层拆分

`scripts/build/harmonyos_dsh.py`：
- 核心层剔除运行时不需要的内容：`*.map`、`*.d.ts`、`test/tests/__tests__/spec` 目录、
  `node-pty/prebuilds`（PTY 已延期）；
- 大体积按需内容拆到 `dsh-layer-optional.zip`（随包但不在启动关键路径）：
  `libreoffice-kit-wasm`（Office）、`sherpa-onnx`（语音）、`dsh-experimental-inspector`（开发）、
  `pyright` + LSP TypeScript（代码智能）；
- 目标是在需要时按需解包，不阻塞聊天可用。

`apps/harmonyos/entry/src/main/ets/runtime/DshEngine.ets`：
- 核心 dsh-layer 解包与 node/shell/pnpm/python 层并行；
- optional 层在 **Host ready 之后后台解包**（实测 1.4s），不占用首屏关键路径；
- 新增 `dsh-optional-runtime-id.txt` 作为 optional 层的解包 identity。

### 5.2 效果（模拟器 127.0.0.1:5557，当前构建）

| 指标 | 优化前 | 优化后 |
| --- | --- | --- |
| 冷启动 解包（dsh-layer） | 22.7s | **9.7-11.5s** |
| 冷启动 前景到 ArkWeb（readyMs） | 约 35-40s | **16.9s** |
| 冷启动 wall（含脚本轮询开销） | 40.2s | 22.1s |
| 温启动 前景到 ArkWeb（readyMs） | 约 10-11s | **6.4s** |
| optional 层后台解包 | — | 1.4s（after ready） |

证据：`docs/evidence/startup/cold-final.json`、`warm-split-opt2.json`、
`cold-baseline.json`、`warm-baseline.json`。

### 5.3 门禁

新增 G2 `startup-warm-budget`：`startup.py --warm --max-wall 15`（nightly 用 store/jitless 构建，预算按 15s；self/JIT 构建真机目标 10s）。

### 5.4 已知限制与后续

- 冷启动首次打开后约 1-2s 内 Office/语音/LSP 的可选文件仍在后台解包；
  首次立即使用这些能力可能失败，需要能力入口等待或提示（后续优化）；
- 下一步按顺序：升级增量解包（P1）、Host/profile 并行与 bundle 延迟（P1）、
  copyGuest 去重（P2）、真机复测（需要设备重新连接）。


## 6. 真机验证（Mate 60，2026-11-21）

A/B 对比：同一台真机、同一 clean profile（base + web-app + LSP），旧构建 vs 本分支构建。

| 指标 | 旧构建（741MB） | 本分支（656MB） |
| --- | --- | --- |
| 冷启动 前景 → ArkWeb（readyMs） | **59.7s** | **29.0s** |
| 冷启动 wall | 64.4s | 34.3s |
| 温启动 前景 → ArkWeb（readyMs） | 13.1s | **13.3s** |
| 温启动 native loopback | 9.95s | 9.89s |
| dsh-layer 解包 | 全量 | 核心层 + 后台 optional |

结论：
- **冷启动提升约 51%**（60s → 29s），主要来自解包瘦身/拆分；
- **温启动没有实质变化（约 13s）**：瓶颈在 Host 启动（真机 ~10s，约 5,768 个模块；
  设备 CPU + jitless Node），与解包无关；本次尝试的 Node compile cache 在真机上反而显著变慢，已回退；
- 真机 G3 `verify` / `exec` / `overlay` 在该构建全部 PASS；
- 证据：`docs/evidence/startup/device-baseline-{cold,warm}.json`、
  `device-final2-{cold,warm}.json`。

后续若要真机温启动继续下降，需要单独做 **Host 启动优化**（模块/启动路径裁剪、jitless 限制评估），
不再属于解包优化范围；增量升级解包仍未实现（需要 chunked layer 设计）。


## 7. Host 温启动优化：self/lab 构建启用 V8 JIT

真机时间线显示温启动瓶颈在 Host：`cli-imported` → `web-announced` 约 8-9s（5,768 个模块，
jitless V8 在手机上解释执行）。

`runtime/harmonyos/native/nativehost.c`：
- **self/lab 构建**：Host Node 去掉 `--jitless`，启用 V8 JIT；
- **store 构建**：保持 `--jitless`，等商店侧策略确认后再切换。

验证（Mate 60）：
- 温启动 前景 → ArkWeb：**13.3s → 9.6-9.9s**；
- native loopback：**9.9s → 6.5-6.7s**；
- 模拟器温启动：7.7-9.2s → **6.9-7.4s**；
- JIT 在真机/模拟器均可稳定启动，G3 verify/exec 通过（overlay 因锁屏未跑）。

冷启动（解包为主）仍在 29-40s 区间，受设备空闲/锁屏影响波动；下一步做增量解包降低升级成本。

证据：`docs/evidence/startup/device-jit-warm-{1,2}.json`。


## 8. 增量解包：chunked dsh layer

`scripts/build/harmonyos_dsh.py` 现在把 core layer 按包分组写成 8 个 chunk
（`dsh-layer-0..7.zip`）+ `dsh-chunks.json`（每 chunk 的 sha256）；optional 层继续保持独立。
构建期读取层内容的脚本（PTC/HTTP/startup-sources）已改为扫描 chunk。

`DshEngine` 启动时读取 manifest，只解压 **缺失或 sha256 变化** 的 chunk：
- 首次安装：按顺序解 8 个 chunk（首次冷启动与之前单层相近）；
- 升级：只有内容变化的包组 chunk 会重新解压，其余 marker 命中直接跳过；
- 实测：模拟器删掉 1 个 chunk marker 后启动，日志 `startup chunks extracted=1/8 ms=808`，
  温启动 8.9s；真机同法 1 个 chunk，温启动 11.1s（比全量首启 27.8s 快）；
- 串行优于并发：同树并发 ArkTS zlib 解压会互相拖慢，已保留串行。

最终真机数据（Mate 60，chunked + JIT self 构建）：
| 指标 | 旧构建 | 优化后 |
| --- | --- | --- |
| 冷启动 前景 → ArkWeb | 59.7s | **27.8s** |
| 温启动 前景 → ArkWeb | 13.1s | **9.65–9.96s** |
| 首次安装后首启（全 chunk） | — | 约 28s（与冷启动一致） |
| 增量升级首启（1 个 chunk 变化） | 约 28s | 约 11s |
| G3 verify/exec/overlay | — | PASS |

store 构建保持 jitless，且 chunked store HAP shape 检查通过。

剩余已知问题：
- optional 层（Office/语音/Forge 等）仍在 Host ready 后后台解包（约 1.5-6s 取决于设备），
  极早使用这些能力可能遇到短暂未就绪；
- 真机增量升级的“包内容实际变化”场景未单独构造，仅通过 marker 失效验证了 chunk 选择逻辑；
- Host JIT 只影响 self/lab；store 仍 jitless（待商店策略确认后评估）。
