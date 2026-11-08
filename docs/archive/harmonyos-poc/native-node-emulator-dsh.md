# 鸿蒙原生 Node 与官方 DSH 模拟器验证

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

2026-11-07，DevEco Phone 模拟器，HarmonyOS 7.0.0.107 / API 26，ARM64。独立调试包内的鸿蒙 Node 24.14.1 通过 N-API 桥加载。DSH 固定 0.2.2-rc.1，沿用原生 Node 探针和已有 DSH 依赖归档，测试时由 Node 直接加载 JS。使用固定来源的 DSHM fetch 垫片。API key 从本机配置经一次性回环请求传给探针，仅保留运行时变量，测试日志和制品均不写入密钥。

- **独立 Node 请求通过。** DeepSeek `deepseek-flash` 流式返回 HTTP 200、预期文本和结束标记。首段内容 938 ms，流式完成 1,026 ms。计时从发起 API 请求开始。结果（本机产物 `../.build/native-node-emulator/evidence/model-result.json`） · 制品校验（本机产物 `../.build/native-node-emulator/evidence/api-hap.sha256`）
- **官方 DSH Headless 通过。** 调用官方 CLI，原生 Node 从 DeepSeek Messages 接口收到 HTTP 200。CLI 最终事件 `completed`，回复命中预期文本，退出 0，持久化会话文件 9,907 字节。从调用 CLI 到本轮完成约 2,537 ms，包含模型请求，未计入 HAP 首次解包或启动页面。结果（本机产物 `../.build/native-dsh-host-emulator/evidence/dsh-headless-result.json`） · 运行日志（本机产物 `../.build/native-dsh-host-emulator/evidence/emulator-hilog.log`） · 制品校验（本机产物 `../.build/native-dsh-host-emulator/evidence/host-hap.sha256`）
- **会话兼容。** 未加适配时 DSH 对会话做硬链接被鸿蒙拒绝，得到 EACCES。加入此前 PoC 的 `renameat2(RENAME_NOREPLACE)` 回退，只处理该位置的 EACCES。模拟器先验证目标已存在时保留原文件，以及目标不存在时成功发布，随后实际会话触发回退一次。会话文件锁使用从官方 `flock.c` 编译的鸿蒙 N-API 扩展，Node 内部模块适配使用 `--expose-internals`。原始失败（本机产物 `../.build/native-dsh-host-emulator/evidence/dsh-headless-link-denied.json`） · 探针源码（本机产物 `../.build/native-dsh-host-emulator/js/native-host.cjs`）

两次初跑因探针在 CLI 挂载完成时提前结束，不计为模型回合。此次范围为模拟器上的单轮本机 DSH 对话和落盘。ArkWeb 页面、首次启动总耗时、工作区 Shell、旧会话续接和 Mate 60 的同构原生 DSH 仍待验证。

## 原生子进程与终端边界

后续用同一 Phone 模拟器、同版 Node 24.14.1 和独立 HAP 进程验证。直接启动系统 toybox 的 `echo`、`ls`、`cat` 退出 0。Node 将 toybox `cat` 和 `grep` 的输出输入接起来，两端均退出 0，返回预期行。测试文件位于应用私有目录。Node `shell: true`、`/system/bin/sh` 和 `/bin/sh` 均返回 EACCES，PATH 查找 `bash` 和直接调用 `/bin/bash` 均返回 ENOENT。应用打开 `/dev/ptmx` 返回 EACCES。无 Shell 的子进程工具可用，完整 DSH Bash 工具和交互终端尚未跑通。两个探针分别验证模型链路及应用身份下的子进程，命令探针未调用模型。

为腾出模拟器安装空间，卸载了上轮一次性 Headless 探针。原 HAP 和验证结果保留，模拟器前台为原生命令探针。两次安装因空间不足失败，释放空间生效后重试成功。命令结果（本机产物 `../.build/native-shell-emulator/evidence/native-shell-result.json`） · 制品校验（本机产物 `../.build/native-shell-emulator/evidence/shell-hap.sha256`） · 安装日志（本机产物 `../.build/native-shell-emulator/evidence/install-shell.log`）
