# 鸿蒙运行时研究索引

## 当前结论

首发路线采用 **鸿蒙原生 Node／DSH Host + 按需 PRoot 工具**。应用的交互、模型请求、会话和任务管理在本机原生进程中运行。PRoot 为部分需要 Linux 用户态环境的工具提供兼容路径，安全边界仍由鸿蒙应用沙箱和 DSH 权限规则提供。[现有架构](../architecture.md)

| 验证路线 | 观察结果与决策 |
| --- | --- |
| DSHM 参考实现 | 在 Mate 60 重签并启动，实测外部 Shell 执行失败。表面的「找不到 sh」同时涉及路径解析与应用权限。保留为平台差异对照 |
| 鸿蒙原生 Node | 24.14.1 已在 Phone 模拟器运行官方 DSH 并获得真实模型响应。后续真机原型完成会话、文件工具、插件和 Web 回归 |
| PRoot 承载完整 Host | 早期版本可运行，但在所测 Mate 60 上启动超过三分钟。seccomp 跟踪加速在该次真机验证回退兼容路径。后续将 Host 改回原生运行，PRoot 按需承载工具 |
| 原生 Host 与按需 PRoot | 0.4.24 真机覆盖安装后，强停重启到聊天页 10.4 秒。Bash 单次审批、管道、退出码、取消和后台作业已有真机证据 |
| 系统 PTY | 所测普通 HAP 在真机及 Phone 模拟器分配系统 PTY 返回权限拒绝。HDC 调试会话属于另一执行身份。系统交互 PTY 延期 |
| Workflow 进程限制 | Phone 模拟器支持在独立子进程启用 seccomp 过滤。RC.3 的 Workflow 包装器在 macOS Node `--jitless` 下可运行固定 JavaScript 试验。[结果与复现](harmonyos-workflow-sandbox.md) |
| Git 和附件 | 真机公网 GitHub 直连超时，经临时代理浅克隆并核验 README。签名库路径修复后真机接受有效 PNG 和 GIF，模型理解图片仍待测 |

0.4.23 模拟器从零数据到 ArkWeb 完成约 15.6 秒，强停重启约 6 秒。0.4.24 的真机 10.4 秒来自保留数据的强停重启。两组数据分别对应设备和启动条件。[模拟器证据](../evidence/emulator-core-0.4.23.json) · [真机证据](../evidence/mate60-core-0.4.23-0.4.24.json) · [回归矩阵](../workspace-validation.md)

## 历史资料

下面的文件保留当时的目标、约束、替代方案和失败。现行计划见[路线图](../roadmap.md)。原始测试日志、截图、签名材料及制品保存在本机。

| 主题 | 记录 |
| --- | --- |
| 初始任务与候选路线 | [原生 DSH PoC 任务书](../archive/harmonyos-native-dsh-poc-plan.md) · [运行时路线讨论](../archive/harmonyos-runtime-alternatives.md) |
| 原生 Node 和宿主环境 | [环境](../archive/harmonyos-poc/environment.md) · [API 兼容状态](../archive/harmonyos-poc/compatibility.md) · [原生 Node 与 DSH 模拟器](../archive/harmonyos-poc/native-node-emulator-dsh.md) · [早期测量](../archive/harmonyos-poc/metrics.csv) · [早期失败](../archive/harmonyos-poc/failure-notes.md) · [工作记录](../archive/harmonyos-poc/work-log.md) |
| DSHM、Shell 和 PTY | [DSHM 实机部署](../archive/harmonyos-poc/dshm-deployment.md) · [Shell 调研规格](../archive/harmonyos-poc/shell-breakthrough-research-plan.md) · [DevEco 与 Shell 执行边界](../archive/harmonyos-poc/shell-breakthrough-research.md) · [开源项目调查](../archive/harmonyos-poc/open-source-phone-shell-survey.md) · [系统 PTY](../archive/harmonyos-poc/harmony-system-pty-research.md) |
| PRoot 与启动对照 | [模拟器最小验证](../archive/harmonyos-poc/proot-emulator-validation.md) · [模拟器扩展验证](../archive/harmonyos-poc/proot-full-validation.md) · [Mate 60 实机](../archive/harmonyos-poc/proot-mate60-validation.md) · [启动优化](../archive/harmonyos-poc/proot-startup-optimization.md) · [seccomp 和重新进入](../archive/harmonyos-poc/proot-seccomp-reentry.md) · [原生 Web 启动对照](../archive/harmonyos-poc/native-web-under-60.md) |
| 早期应用制品 | [0.3.4 手机试用](../archive/harmonyos-poc/dsh-client-preview.md) · [0.4.1 全量 Web 配置](../archive/harmonyos-poc/dsh-full-phone.md) · [后续版本记录](../releases.md) |
