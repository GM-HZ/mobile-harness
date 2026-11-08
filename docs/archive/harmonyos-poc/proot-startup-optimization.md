# 鸿蒙 PRoot 启动优化

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

目标是缩短已解包后的进程冷启动。基线为 Mate 60 上的 0.4.1，PRoot 开始到服务就绪约 245 秒，随后约 3.6 秒显示聊天页。本轮保留现有运行时、DSH 版本和工作区权限。

先验证启动期间内置依赖目录的路径和包清单缓存，再通过同一制品比较缓存关闭和开启时的 CLI 就绪耗时。分别记录解包、服务和聊天页。只有同一设备、同一状态的结果才用于计算加速比。首次安装解包和后台常驻另计。

## 0.4.2 实测

使用独立 DevEco Phone 模拟器实例 Harmony_DSH_Boot_Bench，HarmonyOS 7.0.0.107 / API 26。原模拟器两次返回安装空间不足。测试版保留同一 DSH Web profile，将 Bash、ripgrep 和 Landlock 诊断改为按需运行。路径元数据和 UTF-8 包清单只在内置依赖树的启动阶段缓存，回环服务公布地址时恢复 Node 原有接口。符号链接交回原接口解析。已有的签名 Node 直接映射到 guest，解包目录中的重复 ELF 换成零字节挂载点。

| 场景 | 结果 |
| --- | --- |
| 全新安装，缓存开启 | Node 层 104 ms，DSH 层 9,348 ms，准备开始到 PRoot 启动 9,469 ms。DSH JS 入口到服务公布地址 14,712 ms。准备开始到 ArkWeb 显示 DeepSeek Harness 约 31.4 秒。 |
| 已解包，重启模拟器，缓存关闭 | DSH JS 入口到服务公布地址 21,293 ms。鉴权 303，已鉴权首页 200。 |
| 已解包，重启同一模拟器，缓存开启 | DSH JS 入口到服务公布地址 17,302 ms，单次对照缩短 3,991 ms，约 18.7%。鉴权 303，已鉴权首页 200。页面开始准备到回环会话就绪 20,512 ms，随后约 3.0 秒显示聊天。 |

同一 0.4.2 制品做两次已解包对照。两次都跳过启动自检，差异来自缓存开关及单次运行波动。第一次全新安装的解包计时为启动时的 hilog 读数，聊天页和 DSH 就绪日志保存在对应记录。单独的本地缓存回归覆盖符号链接、缺失路径、非目录、读取编码和恢复原接口。

签名 HAP 从 358,962,417 降至 311,996,985 字节，减少约 44.8 MiB。模拟器使用未签名包，逐个核对两个 HAP 共同的 ZIP 成员 CRC 和长度一致，签名包额外包含页面元数据。Mate 60 当时 HDC 离线，本轮签名包未装机。模拟器只核对了网页加载和本机鉴权，未发模型请求或重测真实对话中的 Bash。

全新安装（本机产物 `../dsh-client-preview/.build/emulator-0.4.2-first-start.log`） · 缓存关闭（本机产物 `../dsh-client-preview/.build/emulator-0.4.2-no-cache-guest.log`） · 缓存开启（本机产物 `../dsh-client-preview/.build/emulator-0.4.2-cache-guest.log`） · ArkWeb（本机产物 `../dsh-client-preview/.build/emulator-0.4.2-cache-ui.log`） · 签名制品（本机产物 `../dsh-client-preview/releases/DSH-Phone-Full-0.4.2-Mate60.hap`）

## Mate 60 覆盖安装与启动复测

2026-11-07 晚，Mate 60 BRA-AL00，HarmonyOS 7.0.0.111，USB HDC。校验签名 HAP SHA-256 后，从 0.4.1 覆盖安装到 0.4.2，设备回读 versionCode 9。HDC 传输加安装 15.871 秒。两层归档的已解包标记保留，本次是覆盖安装后的新进程启动。

| 阶段 | 0.4.1 | 0.4.2 |
| --- | ---: | ---: |
| PRoot 开始到本机鉴权就绪 | 245.073 秒 | 191.960 秒 |
| 鉴权就绪到 ArkWeb 显示聊天 | 3.559 秒 | 3.197 秒 |
| PRoot 开始到聊天页 | 248.632 秒 | 195.157 秒 |

同机单次对照，从 PRoot 开始到显示聊天少 53.475 秒，约 21.5%。差异包含启动缓存、按需自检及运行波动。0.4.2 从 guest JavaScript 入口到 DSH 公布服务地址 176.106 秒，缓存命中 5,608 次路径分段及 1,109 次包清单读取。服务公布地址后约 16 秒完成回环鉴权，随后 3.2 秒出现聊天页。本轮未重新解包、未发模型请求或 Bash 工具任务。

安装（本机产物 `../dsh-client-preview/.build/mate60-install-timing-0.4.2.json`） · 真机对照数据（本机产物 `../dsh-client-preview/.build/mate60-comparison-0.4.2.json`） · DSH 日志（本机产物 `../dsh-client-preview/.build/mate60-server-0.4.2.log`） · 界面日志（本机产物 `../dsh-client-preview/.build/mate60-arkweb-0.4.2.log`）
