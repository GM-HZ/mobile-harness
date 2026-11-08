# Mobile Harness

*The execution harness for Mobile AGI.*

Mobile Harness 是面向手机的原生 Agent 执行工程。手机接收用户意图，Harness 负责调度工具、管理会话与权限，并保存任务进度和结果。首期运行在鸿蒙手机，随后加入云端执行和远端控制，再兼容安卓。长期目标是让同一个个人 Agent 在设备切换后继续跟进任务。

## 当前基线

鸿蒙原型固定使用 Node.js 24.14.1 和 DSH 0.2.2-rc.1。DSH Host 随 HAP 在手机上原生运行，部分命令行工具由 PRoot 按需执行。Mate 60 已完成 0.4.23 至 0.4.24 的覆盖安装回归。0.4.24 在保留数据的情况下强停重启，10.4 秒进入聊天页。云模型调用已验证，云端任务执行、远端控制与安卓属于后续阶段。

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
