# Mobile Harness

*The execution harness for Mobile AGI.*

Mobile Harness 是面向手机的原生 Agent 执行工程。手机接收用户意图，Harness 负责调度工具、管理会话与权限，并保存任务进度和结果。首期运行在鸿蒙手机，随后加入云端执行和远端控制，再兼容安卓。长期目标是让同一个个人 Agent 在设备切换后继续跟进任务。

## 当前基线

鸿蒙原型固定使用 Node.js 24.14.1 和官方 npm DSH 0.2.2-rc.4，源码子模块同步锁定官方 RC.4 标签。DSH Host 原生运行，Linux 命令行工具由 Alpine／PRoot 按需执行。普通包默认带通用 PTC；Office 与 HTTP/1 适配沿用已有实现。

0.4.38 增加官方「跟随会话的标题」和「DSH 徽标技能」的插件管理入口。模拟器已验证真实模型根据多轮消息生成标题、手动固定及重启，以及实际徽标技能和包内资源。此前 Forge 工作树、Ralph、会话搜索及独立工作树的入口继续保留。[能力矩阵](docs/dsh-capabilities.md) · [本轮证据](docs/evidence/emulator-titles-badge-0.4.38.json)

## 文档

| 内容 | 入口 |
| --- | --- |
| 为什么从手机出发，长期要做成什么 | [项目愿景](docs/vision.md) |
| 鸿蒙首发、云端执行、远端控制和安卓的阶段验收 | [路线图](docs/roadmap.md) |
| 当前运行方式和未来跨设备边界 | [架构](docs/architecture.md) |
| DevEco 配置、本地构建和设备选择 | [构建与验证](docs/development.md) |
| 鸿蒙调研结论、替代方案及历史原件 | [研究索引](docs/research/harmonyos-runtime.md) |
| 签名包、实测范围及失败记录 | [版本记录](docs/releases.md) · [回归矩阵](docs/workspace-validation.md) · [证据目录](docs/evidence/) |

`apps/harmonyos/` 是 DevEco 源工程，`packages/dsh-host/` 和 `packages/bundles/` 持有 DSH 装配，`runtime/harmonyos/` 持有平台代码，`vendor/repos/` 记录上游子模块。构建在 `.build/stage/` 生成可打开的 DevEco 工程。
