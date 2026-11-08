# Mobile Harness 的插件、Host 与恢复体系

2026-11-08，提案待评审。此方案与[工程结构](2026-11-08-repository-structure.md)共同定义边界。基线是 0.4.24 鸿蒙原型。

## 一套 DSH 运行体系，两个控制入口

```text
原生 App Shell
  ├─ 启动、连接、授权提示、恢复页、诊断与紧急停止
  └─ Supervisor → 选择启动配置 / 监测 Host / 回滚插件激活
                       ↓ 受控启动和本机连接
             DSH Host → DSH Web 或原生业务 UI 客户端
                 ├─ DSH 会话、工作区、Agent Loop、Skills
                 ├─ DSH bundle/profile 与原生插件管理
                 └─ Phone Use 等工具 → 设备能力接口 → 系统执行适配
```

**DSH 是统一的 Agent 与插件宿主。** 会话、工具调用、Skills、插件配置和 bundle/profile 归 DSH 管理。保留其插件管理 API、界面、版本兼容检查与安装流程。Mobile Harness 持有设备授权、Host 生命周期和出故障后的恢复入口。只保留一套插件配置语义，Supervisor 记录最后一次健康的配置、待激活变更和必要的故障信息。

| 边界 | 谁负责 | 故障时用户可做什么 |
| --- | --- | --- |
| 原生 App Shell | ArkUI 首屏、独立恢复页、Supervisor 客户端。首屏在 Host 启动前就能渲染。正常对话可沿用 DSH Web | 查看状态和精简诊断，启动安全模式、重试、回退或停用插件，保留原有数据 |
| DSH Host | DSH Web/API、Agent Loop、会话、工具和官方插件生命周期。优先复用已有 SDK、bundle 和 profile 入口 | 断连时显示最后已知状态。Host 恢复后重连已有会话，从持久化状态确认运行结果 |
| 设备能力层 | 提供平台允许的屏幕观察、动作、取消等能力，管理权限和资源生命周期 | 权限缺失、取消、进程中断时报告确定状态。敏感动作结果不明时暂停并等待复核 |

连接通道复用已验证的本机 Web 鉴权。启动与恢复走独立的小型控制接口，接口只包含状态、启动模式、重启、故障信息和必要的回滚动作。Host 就绪后才接受新连接，每次启动使用独立标识与连接凭据，旧连接和旧审批失效。运行中的命令与会话恢复仍由 DSH 处理。原生页只保留运行状态和有限的脱敏诊断，避免直接修改会话数据。

## 插件从源码到设备的完整路径

1. **引入源码**。DSH 自带插件跟随 DSH gitlink。独立仓库维护的插件按仓库加 submodule，同一仓库里的多个插件共享一个 gitlink。Mobile Harness 自己维护的插件可先留在 `packages/plugins/`，独立发布时再拆仓。构建清单声明选中包、平台和许可证，沿用插件原有 DSH 兼容信息。
2. **组成安装包**。生成选中插件的生产依赖及原生资源。由 `packages/bundles/` 用 DSH bundle/profile 表达基础组、随包可选组和各平台组合。随包携带、默认启用、用户授权分别决定。Phone Use 在设备能力与授权验证前保持关闭。
3. **保留运行期扩展**。用户在已就绪的 DSH 里仍可以安装、配置、启用或移除兼容插件。已确认官方管理器支持安装时传 `enabled: false`，也支持不启用 HMR 的 profile 在重启后应用配置。移动端首轮采用先安装并校验、再确认激活的流程。安装脚本沿用 DSH 的单独批准。 [DSH 插件管理器说明](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/boot/plugin-manager/README.zh.md)
4. **验证并激活**。保留健康 profile 的恢复点，将新插件版本和激活配置记作候选。在任何插件代码加载前写入持久化启动标记。DSH 使用候选 profile 启动，核心服务和候选能力通过就绪检查后，才确认该版本可用。失败时恢复上一次健康配置，并停用候选插件或候选批次。DSH Web、Agent 工具与原生恢复页使用同一激活规则。先核对上游扩展点能否承接，缺口按锁定版本记录最小适配。

## 崩溃、卡死与回滚

启动状态至少区分 `starting`、`ready`、`degraded`、`failed` 和 `safe`。用启动代次关联日志、状态与退出事件，串行处理重启和配置写入。重启前确认旧 Host 已退出，避免两个进程同时写会话或使用同一设备执行能力。

| 情况 | 处理 |
| --- | --- |
| 单次工具报错、超时或用户取消 | 在调用边界返回可见错误。释放设备占用，保持其他会话与插件可用 |
| 可定位插件加载失败 | 标记对应版本失败，停用该插件后恢复。保留已安装的包和用户配置，供修复后重新启用 |
| Host 崩溃或失去响应，原因未确定 | 根据启动标记退回已知健康配置。仍失败则用内置安全 profile，仅装配受验的基础能力。诊断只标记可疑批次 |
| 系统清理或 App 整体退出 | 下次打开先显示原生入口。上次候选缺少就绪确认时回到健康配置。连续启动失败时进入安全模式。退出原因无法确认时保留未知状态 |
| 外部动作是否成功不明 | 中断旧任务执行权。恢复后先确认动作结果，状态不明时保留待核实状态，避免重复发送、提交或付款 |

安全 profile 与正常 profile 的插件激活选择分开。它复用原有 DSH 数据根和会话，启动前跳过用户及可选插件的加载，首先验证不会 import 已隔离插件。恢复动作使用原子写入和上一次健康配置，保留会话、工作区、凭据和插件配置。重置运行时和删除用户数据是两个不同动作。连续失败有次数上限，停止自动重启，留在恢复页。dsh-go 的原生控制器和独立恢复界面可供参考，尤其是恢复写入需要与引擎启动串行。 [dsh-go 恢复控制](https://github.com/ccch1mneyyy/dsh-Go/blob/3a91fab9e80d2a92be071a74b8b208214d7e6277/app/android/app/src/main/kotlin/io/github/ccch1mneyyy/dsh_app/runtime/RuntimeRecoveryGate.kt) · [dsh-go 安全模式页面](https://github.com/ccch1mneyyy/dsh-Go/tree/3a91fab9e80d2a92be071a74b8b208214d7e6277/app/lib/ui/safe_mode)

**进程隔离和工作区沙箱分别验收。** DSH 官方说明已安装的 Host 插件代码可在宿主进程运行。将 UI 与 Host 分进程可以隔离 Host 崩溃。同一个应用权限域仍需独立的能力授权和边界。对原生依赖、长任务和有副作用的设备工具，优先将实际执行放到可取消、可观察的受控执行单元。缺少隔离或系统授权的能力保持不可用。 [DSH 插件管理器安全边界](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/boot/plugin-manager/README.zh.md)

## Phone Use 作为第一个完整能力接入

dsh-go 将 Phone Use 做成 Android 原生执行、权限和安全检查，再通过桥接向工具端暴露观察与动作。借鉴其分层。Mobile Harness 的 DSH 插件负责注册工具、描述和输入校验，调用平台执行端口。鸿蒙、安卓各自实现端口并报告能力范围。 [dsh-go Phone Use 源码](https://github.com/ccch1mneyyy/dsh-Go/tree/3a91fab9e80d2a92be071a74b8b208214d7e6277/app/android/app/src/main/kotlin/io/github/ccch1mneyyy/dsh_app/phone)

- 第一条真机链路选可逆的授权操作。查询能力和权限，观察目标，执行一次动作，回读结果。先验证目标进程、公开接口与权限，再决定可暴露的操作范围。
- 执行端按任务、设备和当前目标串行使用屏幕与输入。目标变化、锁屏、权限撤回、超时或取消时停止，审批绑定实际操作和任务版本。
- UI 有独立的停止入口。设备执行端在 Host 断连或授权失效时主动停下。截图和系统操作依平台实际权限开放。浏览器操作与跨 App 原生操作分别验证。

## 鸿蒙 Phone 上的进程验证

0.4.24 由 ArkTS 调用 N-API，用线程在同一应用进程加载 `libnode.so`。现有 PRoot 工具子进程能执行部分命令，仍需另行证明可以承载完整、可管理的原生 DSH Host。 [当前 Node 启动代码](../../runtime/harmonyos/native/nativehost.c) · [0.4.24 真机证据](../evidence/mate60-core-0.4.23-0.4.24.json)

鸿蒙公开文档将 Native Child Process 以及 UIAbility 的静态、动态和模块独立进程限定在 Tablet、PC 或 2-in-1。AppServiceExtensionAbility 当前仅支持 2-in-1，并要求相应 ACL。SDK 有声明只能证明可编译。普通签名 Phone 的单包独立 Host 路线仍是待验证门槛。 [Native 子进程接口](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/js-apis-app-ability-childprocessmanager/) · [独立进程指南](https://developer.huawei.com/consumer/en/doc/harmonyos-guides/isolation-process-development-guideline/) · [后台服务限制](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/app-service-extension-ability/)

1. 先用独立测试 HAP 在 Phone 模拟器和 Mate 60 验证可用的系统入口与设备能力。再用最小宿主验证本机握手、两个实际 PID、可控退出和强停、Host 退出后 UI 保持可操作及重新连接。现有 HAP 内子进程路线只有在完整生命周期和兼容性测试通过后才列为候选。未经验证的多线程 `fork` 后启动 Node 仅供实验评估。
2. 同步落地原生恢复页和下次启动保护。这一层可在当前同进程原型先验证。原生恢复页先写入下一次启动选择，再按平台可用入口重启应用。当前 Node 桥只接受一次启动，崩溃恢复以重新打开应用为验收。**验收记录分别标注「重开可恢复」和「Host 崩溃当场 UI 仍可用」。**
3. 若普通 Phone 上的单包隔离不可行，保留明确的产品决策点。评估单独本机 Host 应用与独立 UI 之间的启动、鉴权、数据和安装体验，或将同进程方案限定为预览。远端 Host 可作为后续独立运行模式。完整本机隔离按真机结果验收。

## 交付顺序与准入

| 里程碑 | 必须实测 |
| --- | --- |
| A. 原生恢复入口与安全启动 | Host 启动前 UI 可进入。放入加载即失败的测试插件，重开进入安全 profile，能停用或回退，旧会话数据保持可用 |
| B. 鸿蒙进程边界 | 真机记录 UI 和 Host 的两个 PID。主动杀掉 Host 或注入卡死，UI 当场仍可操作，可重启并回到原会话。Host 和工具没有孤儿进程或重复占用 |
| C. 插件管线 | 同时集成 DSH 原生插件、一个固定 submodule 插件和一个运行期安装的插件。覆盖安装、禁用、启用、版本不兼容、激活失败、回滚和再次恢复 |
| D. 首个 Phone Use 能力 | 在获授权的真实手机上完成观察、执行、回读；锁屏、权限撤回、Host 中断和停止按钮实测生效。用签名 HAP、设备型号、API 与权限记录证据 |

源码来源追溯和干净检出构建仍是主线，可以和 A/B 的独立探针并行。正式引入多套可选插件和高风险能力前，先通过适用的恢复与隔离验收。
