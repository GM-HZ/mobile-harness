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
