# DSH 手机完整 Web 配置 0.4.1

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

2026-11-07。独立鸿蒙 PoC 使用官方 DeepSeek Harness 0.2.2-rc.1、Linux ARM64 Node 24.14.1 和 PRoot。延续原包的签名、应用标识和 DSH 数据目录，覆盖安装保留会话及登录。标准、Cordis 和 PTC 预设以及文件工具、搜索、Bash、插件设置恢复为官方 Web 配置。系统 PTY、依赖 PTY 的极简预设、会话日志上传和产品遥测仍停用。 [实际配置](../../../packages/bundles/mobile/dsh-client.patch.yml)

## 真机与制品

- Mate 60 已安装并启动版本 0.4.1。服务的令牌交换和已鉴权首页分别返回 303、200，ArkWeb 显示 DSH 聊天页面和已有会话。HAP 的 SHA-256 为 `18e53d12ae51da8fdae8a43c2dac353fc0b7d5458856e3288e6a60a3990a2c5c`。 签名 HAP（本机产物 `../dsh-client-preview/releases/DSH-Phone-Full-0.4.1-Mate60.hap`） · 构建（本机产物 `../dsh-client-preview/.build/build-0.4.1.log`） · 安装（本机产物 `../dsh-client-preview/.build/mate60-install-0.4.1.log`） · 真机聊天页（本机产物 `../dsh-client-preview/.build/mate60-ui-0.4.1.log`）
- Bash 用固定 `/bin/bash` 路径，PRoot 映射 `/dev/null`。同步启动与 DSH 风格的异步 detached pipe 启动均返回预期标记。签名 BusyBox 命令映射通过 Bash 的 `ls | grep` 管道，DSH 自带的签名 ripgrep 通过版本自检。 真机启动日志（本机产物 `../dsh-client-preview/.build/mate60-server-0.4.1.log`）
- 官方 Landlock launcher 已运行，退出 125，报告内核 ABI 不支持或未启用。保留官方 `workspace-write` 和已有会话权限。DSH 自带的逐命令升级审批仍由 DSH 决定。尚未验收从真实对话发起 Bash 的完整回合、默认工作区 Shell 隔离、长命令取消及各个恢复的插件功能。 [DSH 沙箱机制](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/sandbox.md)
