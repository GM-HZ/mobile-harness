# DSHM 现成包部署

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

- 用户要求：先部署 DSHM 看效果，自编译 Node 流程继续。
- 官方发行：DSHM v1.1.0，端侧核心 0.2.1-alpha.1+dshm.6，包名 com.dshm.dshclient。
- 原包：`DSHM-1.1.0-core0.2.1-alpha.1+dshm.6-arm64-signed.hap`，321372379 bytes，SHA-256 `c20fbb4e33ca7aec7a1dd3b7474863a5a7aaa2e86836b712a37e021e6148d452`，与 GitHub Release 元数据一致。使用用户下载并移入本独立目录的完整文件；早先未完成下载不用于安装。
- Phone 模拟器：原包安装成功，EntryAbility 启动。首次出现本地令牌 401，重试未恢复；明确停止并重启该应用后主界面正常展示（工作区、模型选择和输入区）。截图 `.build/dshm-release/Screenshot_2026-11-06T234528.png`。未配置模型凭据、未发送模型请求，不能宣称端到端任务通过。
- Mate 60：HDC 安装失败，输出 code 9568423，签名 profile 未包含本机 UDID。HDC 自身退出 0 不等于安装成功。
- 已准备 dshm-signing 工程，用户已接受原包权限并授权重签。其 SignHap 前置钩子校验原包 SHA 并把签名输入替换为原包；准备构建通过，替换后的输入 SHA 已确认与原包一致。实际新签名未完成，重签后仍需逐个 ZIP payload 校验和真实安装/启动。
- 原包声明 11 项权限，包括网络、后台、用户文件、全盘访问、自定义沙箱、外部原生代码及麦克风。已明确告知用户，未在未答复前申请新 profile 权限。
- 自编译流程：Node 24.14.1 当前转为本机 LLVM 20 编译器 + DevEco OHOS sysroot/目标库；修正了 intrinsic 头文件路径冲突，对实际失败 Highway 源做语法检查退出 0，已重新启动整体构建。完整构建和目标设备验证尚未通过，当前日志 `.build/harmony-node/build-node24-clang20-resource.log`。

## 2026-11-07 签名进展

- Mate 60 已重新连接；本轮 HDC 同时列出 USB 真机与 TCP 模拟器。
- 用户截图的直接错误是自动签名包名为空。已在 DevEco 中填入 `com.dshm.dshclient` 并重试，成功生成本地 p12/p7b/cer；没有读取或展示密码。
- 但点击保存触发 DevEco 内部异常，根 `build-profile.json5` 未写入签名配置。CLI 本轮 assembleHap 退出 0，但日志明确 `No signingConfigs profile`，因此不是重签成功，不能安装作验收。
- 重新导入和新建干净签名目录后，IDE 日志明确 `java.nio.file.FileSystemException: .../Downloads/harmony-dsh-poc/dshm-device-signing: Operation not permitted`，同时报告 project model is null。已请用户在 macOS“文件与文件夹”允许 DevEco 读取下载目录；尚未修改此系统权限。
- 本地生成 profile 的只读摘要：bundle 正确，debug 类型，2 个调试设备，allowed-acls 为空。原包高级权限是否被该 profile 接受尚未验证；不能据此承诺真机安装成功，也不移除原包权限规避失败。
- 签名工程原 `.idea` 已备份到 `.build/dshm-release/idea-backup-*`；另有不含密钥的干净导入目录 `dshm-device-signing/`。原版 HAP 未修改。
- 下一步：目录权限放开后重新载入签名工程、保存自动签名配置，执行签名，逐 ZIP payload 比对原包后再真机安装和启动。

### 下载权限恢复后的实际结果

- 用户确认后检查发现 DevEco 的录屏权限已开启、下载目录开关仍关闭；依据本轮目录授权开启 Downloads，并使用系统“退出并重新打开”使其生效。之后项目树、bundle 名及模块正常加载。
- IDE 根据原包 manifest 提示 5 项受限 ACL，按用户此前“接受原包权限，继续重签”的明确授权继续；新 Profile 已包含这 5 项权限。早先空 ACL profile 已不用于本次签名。
- `assembleHap` 本轮退出 0，日志 `.build/dshm-release/resign-with-profile.log`，已生成真实签名制品。
- 制品 `.build/dshm-release/DSHM-1.1.0-Mate60-debug-resigned.hap`：321372036 bytes，SHA-256 `c3ce7ce834ac5708c3346dd4d403b3d4f223839bdeaddd1d7a90d259b69a9755`。114 个 ZIP member 名称及每项解压 payload SHA-256 全部与官方原包一致，没有安装 stub。
- 首次安装尝试输出 `[Fail][E001005] Device not found or connected`，HDC 进程仍退出 0；随后 list targets 显示 Mate 60 USB Offline。已请用户解锁并重新连接，尚未真机安装/启动成功。

### Mate 60 部署成功

- 用户恢复 USB 后 HDC 显示 Connected。安装同一重签制品，日志 `.build/dshm-release/phone-resigned-install-connected.log` 明确 `install bundle successfully`（命令退出 0）。
- `aa start -a EntryAbility -b com.dshm.dshclient` 返回 `start ability successfully`，随后 pidof 返回实际进程。
- 真机截图 `.build/dshm-release/phone-dshm-screen.jpeg` 显示 DSHM 主页面、工作区 `com.dshm.dshclient`、输入框和模型选择，无错误遮罩。已向用户展示并保持手机前台。
- 未配置模型凭据、未发模型请求，未验证对话、工具任务及后台存活。应用启动和 UI 展示成功不等于整份原生 DSH 任务书验收完成。

### Mate 60 终端失败（本次实测，非模拟器推断）

- 用户报告终端“找不到 sh”。手机解锁后已读取实际 DSHM Host 日志及 host-ready 诊断；原始诊断只保存为本机 0600 文件，不输出其中 token。
- 日志：`spawn <files>/bin/busybox EACCES`；`exec 探测：python3.12=缺，git=缺，git-core/git=缺，git-remote-http=缺，rg=denied，ash=denied，bash=denied，git-ls-remote=缺`。
- host-ready：实际 Node v24.2.0，koffi/sharp/node-pty 本体可加载；sandbox-dlopen false（Error loading shared library），pty-spawn false（forkpty(3) failed）。因此“Node/界面启动”与“PTY/外部命令可用”必须分开。
- HDC 只读 stat 确认 `/system/bin/sh`、`/bin/sh` 实际存在，0755、`sh_exec` 标签；`/usr/bin/zsh` 对 HDC stat 返回 Permission denied，不能当作不存在。这些 shell 用户的读数不代表应用自己的 exec 权限。
- 对精确安装包的只读检查：subprocess-local.resolveExecutable() 对 stat/access(X_OK) 的任何失败统一 catch，最终抛 executable-not-found；terminal controller 的默认环境 shell 未解析会直接拒绝，故 UI 的“找不到 sh”可能实为不可执行。包内 ondevice profile 的 terminal-bash 配置 `/usr/bin/zsh` 带有 2in1 来源说明，但 sidebar terminal controller 的 shell discovery 另读环境默认 shell；修改那一行并不能据此断言修复侧栏终端。
- 上游手机适配 Issue #2 也记录 busybox EACCES、ash/bash/rg denied，且明确区分 Phone 与 2in1：https://github.com/sol5766/dshm/issues/2 。这只是既有佐证，本次结论以 Mate 60 实际日志为准，不推断所有系统版本或设备都如此。
- 结论：当前这份 DSHM 在 Mate 60 的终端/PTY/外部 Shell 不可用，Python/git 工具链也尚未解包到位。此前展示成功仅指应用和主界面；不得报告终端或完整 Agent 工具链通过。
- 当前未修改 HAP payload、系统策略、终端配置或用户数据。下一步在独立 PoC 中单列 P4 应用身份下的 stat/access/spawn/PTY 矩阵，再确定可复用的进程内工具适配；不能将 HDC shell 的执行成功当作应用权限，也不能把重新编译 Node 视为 Shell 问题已解决。
- 无敏感字段的证据摘要：`.build/dshm-release/phone-terminal-evidence.json`；原始日志的 SHA 在摘要内。

### 详细调研追加：权限与普通 App 对照

- 设备权限服务只读查询确认 CUSTOM_SANDBOX 已授予；ALLOW_EXTERNAL_NATIVE_CODE 在本 Mate 60 上没有权限定义。Profile 声明不能当作运行时拥有对应 PC 能力。摘要 `.build/dshm-release/phone-permission-summary.json`。
- 独立、仅 INTERNET 的普通 PoC 中，Node 24.14.1 实际 ready/done；system sh EACCES、ptmx EACCES，但无 Shell toybox echo 直接 spawn 成功。这不改变 DSHM 通用终端失败结论，也不能概括为任意外部命令都被禁。详见 shell-breakthrough-research.md。
