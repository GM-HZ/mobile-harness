# Mobile Harness 架构

## 鸿蒙原型

```text
ArkUI / ArkWeb
  ↕ 应用内回环，凭据换取本机会话
HAP 内的鸿蒙 Node.js / DSH Host
  ├─ 会话、工作区、文件工具、Skills 和插件
  ├─ 按权限与审批调用的命令桥 → PRoot → 随包命令行工具
  └─ 模型请求 → 模型服务
```

| 边界 | 现有实现 |
| --- | --- |
| 宿主 | ArkTS 管理启动和界面，N-API 桥在 HAP 中加载鸿蒙 Node.js 24.14.1，运行固定版本 DSH 0.2.2-rc.1 |
| Web | DSH Web 仅绑定本机回环。应用完成令牌交换后把会话 Cookie 配置到 ArkWeb。真机匿名请求 401，鉴权请求 200 |
| 执行 | 本机文件工具与工作区规则复用 DSH。部分 Linux 用户态工具由 PRoot 按需运行，普通 Bash 在没有可用系统沙箱时按默认权限拒绝，可对具体命令单次批准 |
| 数据 | 会话、工具依赖、配置及默认工作区位于应用私有数据。覆盖安装保留数据；强停重启时复用已展开资源 |
| 安全边界 | 系统边界由鸿蒙 App 沙箱提供。PRoot 提供工具兼容与路径映射。工作区外写入已验证拒绝；应用私有根内已有文件的读取仍遵循 DSH 策略 |

入口见 [ArkTS 启动与生命周期](../apps/harmonyos/entry/src/main/ets/runtime/DshEngine.ets)、[原生 Node／工具桥](../runtime/harmonyos/native/poc.c) 和 [DSH Web 装配](../packages/dsh-host/dsh-native-web.cjs)。[真机与模拟器实测边界](workspace-validation.md)

### Linux 命令行兼容范围

手机端默认保留 Alpine 3.22 ARM64 工具集。它通过 PRoot 提供 Bash、BusyBox 和选定的 Git／Python 依赖。DSH Host 和 Phone Use 的系统调用走鸿蒙原生层。新增本机 CLI 需要验证 ARM64、musl 和鸿蒙的可执行文件加载约束。Ubuntu 的 `apt` 安装脚本、GNU 工具专有选项、仅提供 glibc 的二进制或 `manylinux` wheel 都需要单独适配。可优先选择 Alpine 包、纯 Python 或 `musllinux` wheel。依赖 Ubuntu 用户态的任务由后续远端 Linux 执行器承接。PRoot 更换 rootfs 后仍使用鸿蒙宿主内核与应用权限。 [锁定的 Alpine 包](guest-tools-lock.json) · [Mate 60 加载验证](archive/harmonyos-poc/proot-mate60-validation.md) · [Python 平台标签](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/) · [PRoot 手册](https://github.com/proot-me/proot/blob/master/doc/proot/manual.rst)

## Android

Android 复用固定版本 dsh-Go 的 Flutter 客户端、Kotlin 宿主和 DSH 工具桥。DSH 在 Android 应用私有 Ubuntu 用户态中运行，由 PRoot 提供文件系统映射。用户授权后，DSH 通过 MCP 连接本机 Phone Use 执行器，由 Android 无障碍服务读取界面和执行动作。应用包名、运行时输入校验和构建入口由 Mobile Harness 管理。 [Android 构建与验证](android.md)

## 跨设备设计方向

| 层 | 规划职责 |
| --- | --- |
| Personal Agent | 用户交互、记忆、偏好、目标和主动服务 |
| Harness Core | 任务计划、会话、任务状态与恢复、执行位置选择、权限、审批、结果核验 |
| Execution Runtime | 鸿蒙本机、安卓本机、电脑和云端的执行适配。浏览器、App、系统工具、API、MCP、Skills 由所在执行环境提供 |
| Model Routing | 按能力、速度、成本与隐私选择本地或云端模型。模型选择与任务执行位置独立 |

远端第一条链路规划为手机创建任务、已配对设备执行、手机审批或取消、结果回传。优先定义任务标识、版本、执行目标、状态和结果契约。批准应绑定具体任务版本、设备与操作。重连应恢复已有任务；外部副作用结果不明时先核对执行结果，再决定是否重试。设备能力与授权需要分别验证。

Android 客户端已通过 SSH 连接独立的 DSH 宿主，并在重启后恢复该宿主的会话。跨设备任务交接、设备配对和云端执行仍在规划中。[阶段验收](roadmap.md)
