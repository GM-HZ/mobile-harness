# DSH 手机试用 0.3.4

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

2026-11-07。独立 HarmonyOS HAP，使用同一个调试包名 `org.sayact.nodepoc` 和 Mate 60 对应的设备签名。应用启动官方 DSH 0.2.2-rc.1 的 Web profile，由 ArkWeb 通过手机回环地址打开聊天与会话。运行时沿用实测的 Linux ARM64 Node 24.14.1、`--jitless` 和 PRoot 兼容层。模型由用户在 DSH 中配置。

签名 HAP（本机产物 `../dsh-client-preview/releases/DSH-Phone-Preview-0.3.4-Mate60.hap`） · [构建入口](../../../build.sh) · [试用配置](../../../packages/bundles/mobile/dsh-client.patch.yml)

试用配置保留聊天、会话、模型设置和工作区选择。工作区可以填 `/workspace`。配置停用 Shell 工具预设、终端、文件浏览和插件设置入口、会话日志上传及产品遥测。会话兼容层仅在文件硬链接返回 `EACCES` 时使用已实测的 `RENAME_NOREPLACE` 路径。HAP 申请 INTERNET 和 GET_NETWORK_INFO，使用手机当前网络配置中的 DNS 服务器。

## 制品与验收

- DevEco Studio SDK 26 的 `assembleHap` 构建与签名成功。制品 337.7 MiB。签名包 SHA-256 为 `0d79843e04c6bc843a8c6ef049b52719977282e24c75eb489716405ded9efc09`。检查签名 HAP 的包名、版本、权限及配置内容均一致。 构建日志（本机产物 `../dsh-client-preview/.build/build-0.3.4.log`）
- Mate 60 的 HDC 安装和启动均成功。0.3.1 的服务鉴权和入口脚本在真机上通过，嵌入页出现白屏。0.3.2 的 App 内 HTTP 握手超时。0.3.3 复用前期通过真机验证的固定回环端口 19592，并让应用内 ArkWeb 对 HTTP 直连。应用优先预配置经原版 DSH 签发的 HttpOnly Cookie，握手多次超时时由 ArkWeb 使用原始启动链接。本机模拟服务验证了握手与回退。解锁后，0.3.3 真机本机 HTTP 鉴权返回 303 与 200，ArkWeb 完成 DSH 页面加载。用户点击登录后页面白屏，ArkWeb 记录主页面离开回环地址。 安装（本机产物 `../dsh-client-preview/.build/mate60-install-0.3.4.log`） · 启动（本机产物 `../dsh-client-preview/.build/mate60-start-0.3.4.log`） · 服务日志（本机产物 `../dsh-client-preview/.build/mate60-server-0.3.4.log`）
- Phone 模拟器的 0.3.1 未签名 HAP，SHA-256 为 `b1c6e651b3bfef5cb93b31f2bbac1fae523ab54bf06804bc9d865ba5604772ba`。清理早期探针可再生成的依赖文件后安装和启动成功。DSH 开始监听，ArkWeb 显示真实聊天页、工作区入口及添加 API Key 对话框。0.3.2 的模拟器安装遇到设备存储空间限制。 安装（本机产物 `../dsh-client-preview/.build/emulator-install-0.3.1-final.log`） · 服务（本机产物 `../dsh-client-preview/.build/emulator-server-0.3.1.log`） · 聊天页（本机产物 `../dsh-client-preview/.build/emulator-ui-0.3.1.log`）
- 已从 Mate 60 回读一轮完整的真实模型会话和压缩会话文件。重启后的会话续接仍待验证。

## 账号授权页

DSH Web 在用户点击时通过 `window.open` 创建授权页。0.3.4 使用 ArkWeb 多窗口回调绑定独立授权组件，保留主聊天页。授权页限制主导航到 DeepSeek HTTPS 地址及 DSH 的精确本机 OAuth 回调，用户可返回聊天；日志仅记录站点及错误码。构建、签名、安装、启动和允许地址校验通过。Mate 60 实测打开本机聊天页，点击「登录」后独立窗口进入并加载 `https://platform.deepseek.com`，顶部保留「返回聊天」。真实账号完成授权仍由用户操作。 真机 ArkWeb 日志（本机产物 `../dsh-client-preview/.build/mate60-arkweb-0.3.4.log`） [鸿蒙多窗口接口](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/web-open-in-new-window/) · [DSH 登录协议](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-settings-account/README.zh.md)

## 真机会话和目录

0.3.4 的 DSH Host 使用 PRoot 将 HAP 私有目录中的 Alpine 环境映射为进程所见的根目录。guest 的 `HOME` 为 `/root`，`DSH_HOME` 为 `/root/dsh-client`。DSH 浏览型选择器默认从 `HOME` 开始。设备的已登记工作区是 `/root` 与 `/root/test`。包已创建 `/workspace`，未登记为工作区。

北京时间 16:55 的 `/root/test` 会话读取当前目录后通过 `working_directory` 切换至 guest 的 `/`，两次调用成功，回合正常完成。会话记录为 `read-only`，这轮没有 Bash、sh 或 exec 工具调用。账号模型生成了会话标题。 真机执行摘要（本机产物 `../dsh-client-preview/.build/mate60-session-tools-0.3.4.json`）

## 进程内原生 Node

独立 `libnode.so` 制品基于 Node 24.14.1，Mate 60 签名探针实测 `process.platform=openharmony`、ARM64、JS ready/done、直接执行 toybox 的固定命令成功。应用进程内启动系统 sh 和打开 PTY 被拒。Phone 模拟器上，原生 Node 的文件、压缩、Worker 和 100 次回环 HTTP 通过。加 DSHM fetch shim 后，模拟器上的 POST、SSE、取消、DNS 和 HTTPS 通过。原生 Node 的 `--jitless` 模式下 WebAssembly 不可用。官方 DSH 在这条原生 Node 路径上的 Host 启动和对话还待验收。固定官方包的 `node-addon-system` 和 `node-addon-require-builtin` 没有 OpenHarmony ARM64 预编译项。

真机原生 Node 证据（本机产物 `../.build/harmony-node/phone-process-boundary-evidence.json`） · 模拟器 fetch 结果（本机产物 `../.build/harmony-node/emulator-node24-dshm-fetch-result.json`）
