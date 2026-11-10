# HarmonyOS Phone Use 可行性与接入方案

2026-11-08。开发基线为 Mobile Harness `7952466` / `v0.4.25-bench`，DSH 固定于 `fcc0ad4`。0.4.25 的 Mate 60 回归已覆盖会话和插件保留、安全模式及 Host 受控恢复。普通包仍在应用进程内运行 Node。 [Mate 60 基线](../evidence/mate60-restructure-0.4.25.json) · [Host 与恢复设计](../proposals/2026-11-08-host-plugin-recovery.md)

## 能力边界

现有架构可以接入 Phone Use。鸿蒙首发范围取决于系统允许普通签名 HAP **观察什么、操作什么，以及切到目标 App 后还能运行多久**。这些能力分别验证。

| 能力 | 鸿蒙 Phone 结论 | 验收方式 |
| --- | --- | --- |
| 授权截图 | `screenshot.capture` 从 API 21 开始支持 Phone，可由用户授予 `CUSTOM_SCREEN_CAPTURE`。API 26 模拟器已实测前台截图。 | 用独立签名 HAP 在 Mate 60 检查允许、拒绝和撤权。用合成测试界面确认切换到目标 App、锁屏及隐私窗口时的返回行为。 [截图接口](https://developer.huawei.com/consumer/en/doc/harmonyos-references/js-apis-screenshot/) · [截图与隐私模式](https://developer.huawei.com/consumer/en/doc/harmonyos-guides/screenshot-and-privacy-mode/) |
| 前台打开 App 或页面 | 优先验证目标 App 公布的 Deep Link 和可启动组件。后台启动另有规则。业务操作优先走目标 App 提供的接口、MCP 或 A2A。 | 在 Mobile Harness 前台、用户批准后打开一个已知测试页面，再检查目标和回读。逐个验证目标的入口与返回值。 [UIAbilityContext](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/js-apis-inner-application-uiabilitycontext/) · [意图框架接入](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/intents-access-flow/) |
| 通用读树、点按、滚动、输入 | 旧的 `getWindowRootElement`、`performAction` 和 `injectGestureSync` 自 API 12 起停用。当前公开 ArkTS 触控控制器及 C 触控注入接口文档均将有效设备限定为 PC／二合一。Mate 60 普通签名探针调用 `createTouchController()` 返回 `801`，编译器也报告该接口在 Phone 上不可用。 | 正式验收由 DSH 发起，通过鸿蒙原生执行器观察目标、执行动作并回读。HDC 调试行为仅用于诊断系统能力。 [真机证据](../evidence/mate60-phone-use-probe.json) · [无障碍上下文](https://developer.huawei.com/consumer/en/doc/harmonyos-references/js-apis-inner-application-accessibilityextensioncontext/) · [ArkTS 输入注入](https://developer.huawei.com/consumer/en/doc/harmonyos-references/js-apis-inputeventclient/) · [C 输入注入](https://developer.huawei.com/consumer/en/doc/harmonyos-references/capi-oh-input-manager-h/) |
| 华为伙伴 GUI 通道 | 华为接受伙伴申请，并按约定业务范围开放系统级 GUI 辅助操作。受限权限目录中的 `CONTROL_DEVICE` 也区分面向 AI Agent 的系统授权和面向 PC／二合一远程控制的授权。 | 核实独立 App 的接入资格、支持机型、测试签名、目标 App 范围、授权方式以及观察与执行接口。以获准后跑通真机闭环为准。 [GUI 生态合作](https://developer.huawei.com/consumer/cn/doc/service/agent-gui-0000002680521240/) · [受限权限目录](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/restricted-permissions/) |
| 开发环境和远端调试 | HDC/UiTest 支持电脑侧测试。Open-AutoGLM 已采用 HDC 驱动鸿蒙。DSH 生态已有 `dsh-hos-scrcpy` 与 `dsh-scrcpy-core`，可作为桌面调试驱动候选。 | 在开发设备上显式选定测试目标，观察、点击可逆控件并回读。评估第三方插件的固定版本、依赖与运行要求。 [华为 UiTest](https://developer.huawei.com/consumer/en/doc/harmonyos-guides/uitest-guidelines/) · [Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM) · [dsh-hos-scrcpy](https://github.com/ns-zzj/dsh-hos-scrcpy) |

如果首发就要求在普通零售机上自主完成任意 App 的操作，交付门槛是拿到适用的系统通道并在真机验收。现阶段可以先交付已验证范围内的观察、页面跳转和结构化业务操作。开发者模式下的远端驱动单独标识。

## 对照 dsh-Go

参考本地 `dsh-Go@8f7dac9`。它在启动时用 bundle patch 注册官方 MCP 客户端，stdio relay 连接原生桥。桥优先使用抽象 Unix socket，按需回落到 loopback TCP。每次引擎启动更新端点凭据。原生 `PhoneCore` 和 `PhoneTasks` 管理串行执行、任务归属、审批、超时和停止。Android 的无障碍服务负责读树和动作，动作绑定本次观察产生的屏幕 ID，执行后回读。安全模式不挂载 Phone 工具。 [PhoneGuest](https://github.com/ccch1mneyyy/dsh-Go/blob/8f7dac94b0c81b7bd26e907770dc0e9ab28d3dfb/app/android/app/src/main/kotlin/io/github/ccch1mneyyy/dsh_app/phone/PhoneGuest.kt) · [Android 工具和执行层](https://github.com/ccch1mneyyy/dsh-Go/tree/8f7dac94b0c81b7bd26e907770dc0e9ab28d3dfb/app/android/app/src/main/kotlin/io/github/ccch1mneyyy/dsh_app/phone)

Mobile Harness 复用这一分层。鸿蒙上的 DSH 已由原生 Node 启动，已锁定的运行时归档也包含 `dsh-mcp-client@0.2.2-rc.1` 及其工具适配代码。手机能力可以走原生应用侧的本机 IPC，PRoot 继续提供命令行兼容。Android 的无障碍实现和 Shizuku／ADB 后台驱动留给对应平台。

| 层 | 拟放置 | 职责 |
| --- | --- | --- |
| DSH 工具 | `packages/plugins/phone-use/`、`packages/bundles/mobile/` | 复用 DSH 工具和 bundle 机制，按执行端报告的能力挂载工具，传递取消。正常 profile 显式启用。 [DSH MCP 工具适配](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/mcp/mcp-client/README.zh.md) |
| 鸿蒙应用和执行器 | `apps/harmonyos/entry/src/main/ets/capabilities/phone/` | 持有系统权限、用户批准、目标绑定、串行队列、系统操作和原生停止入口。只有需要 C API 时才增加 `runtime/harmonyos/native/` 接口。 |
| Host 到执行器 | 应用私有 Unix socket | 优先验证 ArkTS `LocalSocketServer` 到 Node `net`，用同一契约覆盖同进程启动与未来独立 Host。端点和凭据随启动代次更新，Native UI 授权独立于 Web Cookie。 [HarmonyOS 本机 Socket](https://developer.huawei.com/consumer/en/doc/harmonyos-references/js-apis-socket/) |
| 调试和后续平台 | 各自的执行端 | HDC 测试后端运行在开发电脑。未来 Android 或获准的鸿蒙 GUI 后端复用同一套工具语义和任务约束。 |

首版契约只需要能力查询、观察、执行、停止。调用关联任务与当前 Host 代次。动作绑定目标、观察 ID 和具体批准，执行前重新核对锁屏、授权和目标。设备同时只接受一个任务。前台目标意外切换、撤权、用户停止或 Host 断开时，撤销该任务执行权和待处理审批。动作可能已到达系统时返回结果待核实，重新观察后再决定下一步。屏幕内容视为外部数据。图片发给模型需要明确授权，日志仅记动作类型、目标及结果。

私有 socket 和 Host 分进程分别提供连接与故障隔离。同一个 App UID 下的 Host 和第三方插件仍共享权限域。对高权限执行端，发布前要明确系统授权与插件之间的隔离，以及用户在目标 App 前台时的可用停止入口。

## 初始化和实测

已建 `codex/phone-use`。探针使用独立包名 `org.mobileharness.phoneuseprobe`，查询自己的无障碍扩展状态，执行用户主动触发的前台截图，并通过固定的 `Want` 打开系统设置。截图仅报告字节数，随后释放像素对象。

```sh
tests/probes/harmonyos-phone-use/build.sh
```

默认产出模拟器用 `.build/stage/harmonyos-phone-use-probe/entry/build/default/outputs/default/entry-default-unsigned.hap`。真机在 DevEco Studio 给独立包名配置调试签名，再将签名配置保存到暂存工程之外，并通过 `PHONE_USE_PROBE_SIGNING_PROFILE` 指定该配置构建。签名包名为 `entry-default-signed.hap`。 [DevEco 自动签名](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-signing-auto/)

用 `hdc -t <target> install -r <hap>` 安装，再用 `hdc -t <target> shell aa start -b org.mobileharness.phoneuseprobe -a EntryAbility` 启动。点 **Check screen capture** 测系统授权，再点 **Open Settings test page** 测前台拉起。用 `hdc -t <target> shell hilog -x -T PhoneUseProbe` 回读探针日志，用 `hdc -t <target> shell aa dump -a` 核对目标 App 前台状态。

| 环境 | 本次结果 |
| --- | --- |
| DevEco Phone 模拟器，API 26，7.0.0.107 | 构建、安装和启动通过。公开查询返回 `installed=true, enabled=false, caps=retrieve,gesture`。前台截图返回 11,784,960 像素字节。探针原生拉起系统设置，系统报告设置页处于前台。 |
| Mate 60，API 26，7.0.0.111 | 独立普通调试签名 HAP 构建、安装和启动通过。无障碍扩展已枚举，处于未启用状态。系统授权后探针前台截图返回 13,074,432 像素字节。原生拉起系统设置后，系统报告设置页前台、探针后台。回到探针后，用 HDC 强停并确认进程退出。 [真机证据](../evidence/mate60-phone-use-probe.json) |

在 macOS 上用同版本 DSH `0.2.2-rc.1` 和脚本模型回放真机 `801`。DSH 发起 `mcp__phone_probe__tap`，MCP 测试夹具返回 `PHONE_TOUCH_UNSUPPORTED`，模型下一轮输入收到该错误。此项验证覆盖 DSH 工具调用与错误回传，手机端实时桥接和动作执行待验。

下一步验证 ArkTS 私有 Socket 到 DSH 的能力查询与取消，同时验证拒绝、撤权和后台截图边界。通用跨 App GUI 仍需按华为伙伴流程核实接入范围和验证条件。产品的原生停止入口单独验收。
