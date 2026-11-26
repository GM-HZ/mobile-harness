# Mobile Harness

*面向 Mobile AGI 的执行底座 · The execution harness for Mobile AGI.*

[官方网站 / Official website](https://gm-hz.github.io/mobile-harness/) · [官网源码 / Website source](site/) · [能力矩阵 / Capability matrix](docs/architecture/feature-roadmap.md) · [构建与验证 / Build and validate](docs/development.md)

Mobile Harness 把 DeepSeek Harness（DSH）带到鸿蒙手机。你可以在手机上交代任务，由本机 Agent 宿主调度工具、管理权限、保存会话和任务结果。云端执行、跨设备接力和 Android 适配是后续方向。

Mobile Harness brings DeepSeek Harness (DSH) to HarmonyOS phones. Give it a task on your phone, and the on-device agent host runs tools, manages permissions, and saves sessions and results. Cloud execution, cross-device handoff, and Android support are planned.

## 产品能力 / Capabilities

| 能力 / Capability | 中文 | English |
| --- | --- | --- |
| 会话与工作区 / Sessions and workspaces | 在应用内继续已有会话，读取、搜索和编辑工作区文件。工具调用沿用 DSH 的权限和审批流程。 | Resume a session in the app and read, search, or edit workspace files. Tool calls follow DSH permissions and approvals. |
| 命令与代码 / Commands and code | 普通包按需通过 Alpine / PRoot 调用随包 Bash、Git、Python 等命令行工具，默认包含通用 PTC（程序化工具调用）。 | The standard build runs bundled command-line tools such as Bash, Git, and Python through Alpine / PRoot on demand. It includes general-purpose PTC (programmatic tool calling) by default. |
| 模型、工具与集成 / Models, tools, and integrations | 沿用 DSH 模型配置、Skills 和 Workflow。Forge 已用真实 GitHub 账号验证 PR 读取和授权后的写操作。 | Uses DSH model settings, Skills, and Workflow. Forge has been tested with a real GitHub account for PR reads and authorized writes. |
| 恢复与后台 / Recovery and background tasks | 启动故障可进入安全模式，并从恢复页回滚插件配置。鸿蒙长时任务可选开启，已在真机验证后台运行和锁屏。 | Startup failures can trigger safe mode with plugin configuration rollback from the recovery screen. Optional HarmonyOS long-running tasks have been tested in the background and with the screen locked on a physical device. |

LiveShare 已完成模拟器跨设备浏览验证，真机和官方公网中继仍待验证。语音输入、Office 预览与转换、LSP 和插件包管理各有不同的验证范围。远程 HTTPS 直连是自建和实验构建的实验入口。终端（PTY）已延期。

LiveShare browser viewing across devices has passed emulator testing. Physical-device testing and the official public relay are still pending. Voice input, Office preview and conversion, LSP, and plugin package management have different validation scopes. Direct HTTPS connections are experimental in self and lab builds. PTY terminal support is deferred.

[查看逐项状态与证据 / See capability status and evidence](docs/architecture/feature-roadmap.md)

## 版本与构建变体 / Release status and build variants

当前基线为鸿蒙 `1.0.0` 候选，处于功能锁定期。运行时锁定 Node.js 24.14.1 和官方 npm DSH `0.2.2-rc.5`，DSH 源码子模块同步锁定官方 RC.5 标签。普通包保留既有 Office 和 HTTP/1 适配。

The current baseline is the HarmonyOS `1.0.0` release candidate under a feature freeze. The runtime pins Node.js 24.14.1 and the official DSH npm release `0.2.2-rc.5`. The DSH source submodule is pinned to the official RC.5 tag. The standard build retains the existing Office and HTTP/1 adapters.

| 变体 / Variant | 中文 | English |
| --- | --- | --- |
| 普通包 / Standard (`store`) | 常规本机使用，包含随包命令行工具。 | Standard on-device build with bundled command-line tools. |
| 自建包 / Self (`self`) | 面向本地自建，启用额外执行工具和随包签名库。 | Self-built variant with additional execution tools and signed libraries. |
| 实验包 / Lab (`lab`) | 用于设备实验和回归验证。 | Variant for device experiments and regression testing. |
| AppGallery 候选 / AppGallery candidate (`appgallery`) | 从同一源码生成的独立原生候选包，包含独立包名、隐私同意界面和原生图片处理、工作区搜索。 | Separate native release candidate from the same source, with its own bundle ID, privacy consent screen, native image handling, and workspace search. |

[第一可用版本计划 / First usable release plan](docs/work/2026-11-21-first-usable-version.md) · [发布手册 / Release runbook](docs/architecture/release-runbook.md)

## 本地构建 / Build locally

在 DevEco Studio SDK 26 环境中检出仓库、初始化子模块并准备校验过的构建输入，再为 ARM64 Phone 模拟器打包。输入清单、签名和设备安装步骤见构建指南。

Check out the repository with DevEco Studio SDK 26 available, initialize its submodules, and prepare the verified inputs before packaging for the ARM64 Phone emulator. The build guide covers input preparation, signing, and device installation.

```sh
git submodule update --init --depth=1
./scripts/vendor/verify.sh
HARMONY_UNSIGNED=1 ./build.sh --package
```

DevEco 源工程位于 `apps/harmonyos/`，构建在 `.build/stage/` 生成可打开的 DevEco 工程。`packages/dsh-host/` 和 `packages/bundles/` 持有 DSH 装配，`runtime/harmonyos/` 持有平台代码，`vendor/repos/` 记录上游子模块。

The DevEco source project lives in `apps/harmonyos/`. The build generates a DevEco project under `.build/stage/`. DSH assembly is in `packages/dsh-host/` and `packages/bundles/`, platform code is in `runtime/harmonyos/`, and upstream submodules are in `vendor/repos/`.

[完整构建与验证指南 / Full build and validation guide](docs/development.md)

## 交付与证据 / Delivery and evidence

`0.4.69` 交付了 PTC 单链接读取与并发父目录边界加固、LiveShare 自建中继的双模拟器浏览验证、本机 Ollama 模型端点接入、原生 addon 加载测试，以及 Forge 公开读取和全新安装后的账号入口复验。Forge 写操作在临时私有 GitHub 仓库完成，验证后该仓库已删除。真机麦克风、官方公网 LiveShare Relay 和真实身份提供方的验证仍在跟踪。

`0.4.69` hardened PTC single-link reads and workspace boundaries during concurrent parent directory moves. It tested LiveShare browser viewing through a self-hosted relay on two emulators, a local Ollama model endpoint, native addon loading, public Forge reads, and account entry after a fresh install. Forge writes were tested in a temporary private GitHub repository that was removed afterward. Physical-device microphone testing, the official public LiveShare relay, and a real identity provider remain open validation items.

[交付清单与证据索引 / Delivery summary and evidence](docs/work/2026-11-20-final-delivery.md) · [能力回归闸门 / Capability parity gate](docs/work/2026-11-20-capability-parity-gate.md)

## 文档 / Documentation

| 内容 / Topic | 入口 / Link |
| --- | --- |
| 为什么从手机出发 / Why start with the phone | [项目愿景 / Vision](docs/vision.md) |
| 鸿蒙、云端、远端控制、Android 的阶段目标 / Milestones for HarmonyOS, cloud, remote control, and Android | [路线图 / Roadmap](docs/roadmap.md) |
| 当前运行方式与跨设备设计 / Runtime and cross-device design | [架构 / Architecture](docs/architecture.md) |
| 鸿蒙调研与历史原件 / HarmonyOS research and historical material | [研究索引 / Research index](docs/research/harmonyos-runtime.md) |
| 签名包、实测范围及失败记录 / Signed packages, test coverage, and failures | [版本记录 / Release history](docs/releases.md) · [回归矩阵 / Validation matrix](docs/workspace-validation.md) · [证据目录 / Evidence](docs/evidence/) |
| GitHub Pages 静态官网 / Static GitHub Pages site | [官网开发与发布 / Website development and publishing](docs/product-website.md) |

## 开发规则 / Contributor guidelines

改动前先读仓库与模块的 `AGENTS.md`、框架规则和能力矩阵。适配、补丁和功能改动须通过对应门禁，并留下可追溯的验证证据。

Before making changes, read the repository and module `AGENTS.md` files, the framework rules, and the capability matrix. Adaptations, patches, and feature changes require the applicable gate to pass and traceable validation evidence.

[开发规则 / AGENTS.md](AGENTS.md) · [框架规则 / Framework](docs/architecture/framework.md) · [能力矩阵 / Capability matrix](docs/architecture/feature-roadmap.md) · [门禁系统 / Quality gates](gates/README.md)
