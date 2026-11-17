# Mobile Harness 架构

## 鸿蒙原型

```text
ArkUI / ArkWeb
  ↕ 应用内回环，凭据换取本机会话
HAP 内的鸿蒙 Node.js / DSH Host
  ├─ 会话、工作区、文件工具、Skills 和插件
  ├─ 按权限与审批调用的命令桥 → PRoot → 随包命令行工具
  ├─ PTC / Workflow → 原生监督进程 → 受限的鸿蒙 Node worker
  └─ 模型请求 → 模型服务
```

| 边界 | 现有实现 |
| --- | --- |
| 宿主 | ArkTS 管理启动和界面，N-API 桥在 HAP 中加载鸿蒙 Node.js 24.14.1，运行固定版本 DSH 0.2.2-rc.4 |
| Web | DSH Web 仅绑定本机回环。应用完成令牌交换后把会话 Cookie 配置到 ArkWeb。真机匿名请求 401，鉴权请求 200 |
| 执行 | 本机文件工具与工作区规则复用 DSH。部分 Linux 用户态工具由 PRoot 按需运行，普通 Bash 在没有可用系统沙箱时按默认权限拒绝，可对具体命令单次批准 |
| PTC | 0.4.31 普通包包含 TypeScript 擦除、REPL／Script、工具回调与独立 worker；文件代理通过 seccomp 按目录授权。上游报告 partial enforcement，不等同完整 Linux 沙箱或任意 Node 系统 API。恢复模式不启用此后端 |
| 数据 | 会话、工具依赖、配置及默认工作区位于应用私有数据。覆盖安装保留数据；强停重启时复用已展开资源 |
| 安全边界 | 系统边界由鸿蒙 App 沙箱提供。PRoot 提供工具兼容与路径映射。工作区外写入已验证拒绝；应用私有根内已有文件的读取仍遵循 DSH 策略 |

入口见 [ArkTS 启动与生命周期](../apps/harmonyos/entry/src/main/ets/runtime/DshEngine.ets)、[原生 Node／工具桥](../runtime/harmonyos/native/poc.c) 和 [DSH Web 装配](../packages/dsh-host/dsh-native-web.cjs)。[真机与模拟器实测边界](workspace-validation.md)

### 工具和依赖管理

鸿蒙的 Alpine 包、共享库、项目依赖和 DSH 插件分别由其运行环境管理。见[鸿蒙工具与依赖管理](harmonyos-package-management.md)。

## 跨设备设计方向

| 层 | 规划职责 |
| --- | --- |
| Personal Agent | 用户交互、记忆、偏好、目标和主动服务 |
| Harness Core | 任务计划、会话、任务状态与恢复、执行位置选择、权限、审批、结果核验 |
| Execution Runtime | 鸿蒙本机、电脑、云端和后续安卓的执行适配。浏览器、App、系统工具、API、MCP、Skills 由所在执行环境提供 |
| Model Routing | 按能力、速度、成本与隐私选择本地或云端模型。模型选择与任务执行位置独立 |

远端第一条链路规划为手机创建任务、已配对设备执行、手机审批或取消、结果回传。优先定义任务标识、版本、执行目标、状态和结果契约。批准应绑定具体任务版本、设备与操作。重连应恢复已有任务；外部副作用结果不明时先核对执行结果，再决定是否重试。设备能力与授权需要分别验证。

跨设备任务协议、设备配对、云端执行与 Android 适配均为规划。[阶段验收](roadmap.md)
