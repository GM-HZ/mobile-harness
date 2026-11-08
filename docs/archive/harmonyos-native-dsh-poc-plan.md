> 2026-11-06 原始 PoC 任务书。文中的约束针对当时的纯原生实验。现行鸿蒙原型保留原生 Host，并为部分命令增加按需 PRoot。见[研究索引](../research/harmonyos-runtime.md)。

# HarmonyOS 原生 DSH：本机模拟器 PoC 验证任务书

> 版本：2026-11-06。目标是验证 **HarmonyOS HAP 内嵌 Node.js + 官方 DSH**，不使用 QEMU、PRoot、完整 Linux RootFS 或远程 Host。

## 1. 核心判断和边界

- DSH 是运行于 Node.js 上的 Agent Harness，不内在依赖 Linux 发行版；官方未提供现成鸿蒙发行物。
- 真正的困难主要在 HarmonyOS 手机的 Node.js Runtime、V8/WASM、Node native addon、进程与工具链、包安装生态。
- 本项目追求一个**长期存在、持久化的 DSH 应用环境**，与手机其他 App 通过鸿蒙 App Sandbox 隔离；**不需要按任务创建容器**。
- 仅凭 HAP 模拟器执行通过，不能断言零售 Phone 上的签名、`execve`、`child_process`、ACL、后台保活、耗电也通过。
- 本轮 PoC **不追求** Linux 命令 100% 兼容、`apt`/`apk`、任意 ELF 执行、动态安装所有 npm 原生模块。

## 2. 候选参考代码（先读关键入口）

1. DSHM（运行时与 DSH 适配）：https://github.com/sol5766/dshm
   - `hostruntime/`、`hostcore/`、`entry/src/main/cpp/`、`docs/parity-matrix.md`
   - 手机执行限制案例：https://github.com/sol5766/dshm/issues/2
2. electerm-harmony（另一个进程内 Node + ArkWeb 的实现）：https://github.com/electerm/electerm-harmony
   - 留意 README 所指的 `dev2` 分支；架构为 `libnode_ctl.so` 通过 `dlopen` 启动 `libnode.so`。
3. ohos-node-shared（OpenHarmony 共享 Node 运行时构建脚本）：https://github.com/electerm/ohos-node-shared
   - 示例 `libnode` 为 Node **24.2.0**，**低于**当前 DSH 仓库 `>=24.9.0` 的 Node 版本要求。不得直接用该版本测试最新 DSH；应重编满足目标 DSH 版本的运行时。
4. DSH 官方项目：https://github.com/deepseek-ai/deepseek-harness
   - 当前仓库开发前置条件见 `docs/development.md`；必须锁定测试的 DSH commit/tag，并读取该版本的 `engines.node`。

## 3. 目标架构

```text
HarmonyOS Phone HAP / ArkUI
  ├─ 应用内 UI（初始只做状态页，不复刻完整 dsh-Go）
  ├─ NAPI / C++ runtime bridge
  │    └─ libnode.so (HarmonyOS ABI, in-process, not childProcessManager)
  │         └─ official DSH Host (bundled JS + required dependencies)
  │              ├─ HTTP / WebSocket only on 127.0.0.1
  │              └─ pure-JS + permitted native tool adapters
  └─ App Sandbox (filesDir / home / sessions / plugins / workspace)
```

工程原则：官方 DSH 源码与鸿蒙特有的 runtime、shim、tool adapter 分离；版本固定，不能把 Node 升级与 DSH 升级混在一个实验里。

## 4. 实验环境与预检查

- 使用 DevEco Studio 创建 **Phone** 模拟器，尽量选择与目标真机相近的 HarmonyOS API；不能以 Tablet/2in1 替代 Phone 结论。
- macOS Apple Silicon 可运行官方本地模拟器。`hdc list targets` 先验证连接。
- 在模拟器执行：

```bash
hdc list targets
hdc shell 'param get const.product.cpu.abilist'
hdc shell 'param get const.ohos.apiversion'
hdc shell 'param get const.product.devicetype'
```

> `param` 返回的 ABI 才是准绳。**ARM 模拟器需对应 ARM64 `.so`；x86_64 模拟器需重新构建 x86_64 `.so`。** 不可在架构不匹配时把加载错误当成 Node/DSH 兼容问题。不同系统镜像的部分参数名称可能存在差异，若返回空值改用 `hdc shell param list` 或设备信息界面核对。

- 编译检查 `build-profile.json5` 中 `externalNativeOptions.abiFilters`、HAP 中 `libs/<ABI>/libnode.so`、桥接 `.so` 的 ABI 一致。
- 初期使用 Debug HAP，保存全部 hilog 和 Host stdout/stderr；模拟器可不需要正式上架签名，但要在最终真机环节验证签名安全策略。

## 5. 分阶段实验（不要跳级）

### P0 — 原生 libnode 自举（最优先）

只建一个最简 ArkUI + NAPI HAP，不放 DSH。由 C++ 桥接以**同进程**方式加载 Node 运行时，执行独立 JS 入口，打印：

- `process.version`, `process.versions`, `process.platform`, `process.arch`, `process.cwd()`
- `typeof WebAssembly`, `typeof fetch`，是否启用了 `--jitless`
- `require('node:fs')`, `require('node:http')`, `require('node:crypto')`, `require('node:worker_threads')` 的基础行为

通过标准：应用启动、Node entry 到达、进程不崩溃、ArkUI 能读到 Node ready/error。**若无法加载/启动 libnode，停止进入 DSH 阶段，先解决 Node 构建和桥接。**

### P1 — Node 核心 API 与沙箱

- 在 App 私有 filesDir 创建/读取/重命名/删除文件；退出重启后持久化。
- `node:http` 在 `127.0.0.1:<测试端口>` 建立服务，ArkUI/ArkWeb 请求成功。
- 事件循环、Promise、定时器、流式响应、DNS/HTTPS、加密操作、TLS 测试。
- 测试 `fetch`/`undici`；如果 `--jitless` 禁止 WASM，必须标记并单独实现/复用兼容 shim，而不是宣称 Node 完整兼容。
- 检查进程权限：确认只能访问应用沙箱授权范围；没有理由主动申请全盘权限。

通过标准：连续 100 次 loopback 请求、文件操作、冷启动恢复均成功；任何 `SIGSYS`、`EACCES` 或网络失败留下最小复现和日志。

### P2 — npm 纯 JS 生态

- 在宿主开发机准备一份仅含纯 JS 包的**离线依赖闭包**，打包进 HAP 或资源文件，启动后按官方资源接口解包进 filesDir。
- 测试 Node ESM/CJS `import`/`require`、模块查找、exports、符号链接/包解析，真实导入多个 DSH 依赖。
- **不要直接在模拟器里运行 `npx`/`pnpm`**：其 CLI 启动过程可能依赖不可用的 `execve`。首个 PoC 应在宿主机准备依赖、在 HAP 内只执行 JS 入口。

通过标准：固定 Node 版本下，已打包的纯 JS 包可加载且不依赖系统 Shell。

### P3 — DSH Host 最小启动

- 固定一个当前官方 DSH commit/tag（从仓库确认 `engines.node`），不要同时升级 Node 与 DSH。
- 尽量复用 DSHM 的 core packaging / Host 启动方式，将官方构建好的 DSH 核心与必要兼容层作为资源打包，而不是直接在鸿蒙里跑 `npx @deepseek-ai/dsh web`。
- 绑定 `127.0.0.1`，记录 Host-ready 时间、监听端口、profile 载入、插件挂载情况。
- 先验证 HTTP 服务、创建会话、WebSocket 连接、静态页面；模型调用允许使用测试 Key，**不要写入源码或日志**。

通过标准：Host ready，能够建立会话、收发一轮消息，并把会话写入持久化目录。若失败，区分 Node ABI/加载失败、WASM/undici、native addon、平台识别、subprocess 依赖。

### P4 — 工具兼容矩阵

依次测试：

| 类别 | 实验 | 预期口径 |
|---|---|---|
| 文件 | read/write/edit/glob/grep | 优先纯 JS；应可用 |
| 网络 | HTTP/WebSocket/fetch | shim 后验证 |
| 插件 | 无原生依赖的 Cordis 插件 | 可尝试，但不预先承诺 |
| Native addon | `system.node` 等目标 `.node` | 需 OHOS ABI + 签名 + 依赖闭包 |
| 子进程 | `child_process.spawn` / `execve` | 单独记录，不能由模拟器推断零售手机 |
| Shell | bash、git、python、rg | 预期存在平台边界，不纳入 P0 成败条件 |

**禁止**为让测试通过而引入 QEMU、PRoot，或用远程 Host 假装本机执行。

### P5 — 生命周期与性能

- 冷启动到 Node ready、Host ready；会话恢复时长。
- 空闲 10 分钟 CPU 占用、RSS/Native Heap、唤醒次数；持续运行 30 分钟的内存趋势。
- 连续多轮工具调用、模拟断网、关闭/重启 HAP 后恢复。
- 与宿主机原生 Node 做同一批纯 JS、JSON、文件扫描基准，**仅做参考**；模拟器数据不能代表真实手机性能和功耗。

## 6. 失败分支决策

- **P0 失败**：换/重编 OHOS Node `libnode.so`，核查 ABI、符号、依赖、签名与 NAPI 生命周期；暂不碰 DSH。
- **P0 成功、P1 网络失败**：查 `libuv`、seccomp、TLS、JITless、undici；做最薄平台适配层。
- **P2 成功、P3 失败**：按 DSH 依赖树找 native addon、`process.platform`、内部模块/进程假设；优先外置兼容插件/垫片，不大规模 Fork 官方核心。
- **P3 成功但 Shell 不可用**：证明“原生 DSH Host 成立”，后续实现 HarmonyOS Tool Adapter；Shell 生态是另一个项目，不影响核心路径结论。
- **模拟器全通过**：进入真实 Phone 上的签名、权限、后台、发热、功耗验证；**不能直接宣称产品化可行**。

## 7. 本轮交付物（交给 Codex / Claude Code）

```text
harmony-dsh-poc/
  README.md               # 环境、安装、运行命令
  entry/                  # 最小 ArkUI + NAPI HAP
  native/                 # Node 启动桥接（或引用独立可复现源码）
  js/smoke-test.mjs       # Node API smoke test
  js/http-server.mjs      # 回环服务验证
  scripts/                # 编译、打包、部署与抓日志
  reports/
    environment.md        # 模拟器版本、ABI、libnode/DSH 版本
    compatibility.md      # 每一测试项 PASS/FAIL/NOT TESTED
    metrics.csv           # 冷启、内存、CPU、测试时长
    failure-notes.md      # 错误/日志/复现步骤
```

### 最小设备调试命令

```bash
hdc list targets
hdc shell 'param get const.product.cpu.abilist'
hdc install -r <已构建的-debug.hap>
hdc shell 'aa start -a EntryAbility -b <你的应用包名>'
hdc hilog
```

> 调试时优先 DevEco Studio Run/Debug 来启动；`aa` 启动参数以项目实际 Ability 名称为准。覆盖安装可保留数据，**不要为了重复测试直接 uninstall 清空私有工作区**。

## 8. Go / No-Go 决策

- **GO / 进入产品原型**：模拟器中 Node≥目标 DSH 要求、Host 连接与会话、基础文件工具、持久化都通过，并且真机上完成关键签名/原生模块验证。
- **CONDITIONAL**：Node/DSH 能运行，但系统 Shell/二进制工具不可用——继续做原生 Tool Adapter；不要把它当“完整 Linux”。
- **NO-GO（当前方案）**：普通零售 Phone 不允许必要的 libnode/目标原生模块加载，或兼容层无法稳定支持 DSH 关键依赖。届时再评估限定插件集或其他执行后端，而非默认上 QEMU。

## 参考资料

- DSH 官方：https://github.com/deepseek-ai/deepseek-harness
- DSH 当前开发前置条件：https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/development.md
- DSHM：https://github.com/sol5766/dshm
- DSHM Phone 案例：https://github.com/sol5766/dshm/issues/2
- electerm-harmony：https://github.com/electerm/electerm-harmony
- OpenHarmony Node.js 共享库：https://github.com/electerm/ohos-node-shared
- 华为模拟器差异：https://developer.huawei.com/consumer/cn/doc/harmonyos-guides-V13/ide-emulator-specification-V13/
- 华为 hdc：https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/hdc/
