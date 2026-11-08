# 鸿蒙 DSH Web 六十秒启动验证

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

目标为 Mate 60 已解包进程冷启动至官方 Web 聊天可用不超过 60 秒。基线为 0.4.4 的约 220 秒。对照官方桌面直接运行 Host、先加载已打包页面的方式。用已验证的鸿蒙原生 Node 24.14.1 启动完整官方 0.2.2-rc.1 Web profile，继续使用 ArkWeb，保留 PRoot 做独立命令执行。先在独立的试验数据目录验收，不迁移原聊天、账号或工作区数据。签名测试包默认仍走现有 PRoot，调试标记选择原生验证路径。

## 桌面与鸿蒙的差异

固定版本的官方 Desktop 使用 Electron RunAsNode 直接启动 Host，直接读取随包的生产依赖，并在 Host 准备期间加载随包的 Web 入口。Desktop profile 使用运行时解析，启动时不执行 pnpm。鸿蒙 0.4.4 让 DSH 全量 Web profile 和 Bash 都在 PRoot 中运行，零售 Mate 60 上没有启用 PRoot 追踪加速。0.4.6 让官方 Web Host 在鸿蒙应用内的原生 Node 上运行，固定 Bash 探针仍在单独 PRoot 子进程。网页启动约加载 5,004 个模块，保留官方 Web profile 和此前终端、遥测配置。 [官方 Desktop 架构](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/apps/desktop/README.md#application-overview)

## 测试结果

| 0.4.6 | Mate 60 已解包冷启动 | 独立 Phone 模拟器全新安装后的首次启动 |
| --- | ---: | ---: |
| 应用准备开始至回环鉴权就绪 | 7.448 s | 12.487 s |
| 应用准备开始至 ArkWeb 聊天页 | 10.210 s | 15.361 s |
| Node 和 DSH 归档解包 | 跳过 | 8.755 s |
| PRoot Bash 固定命令并回读同一工作区文件 | 207 ms | 222 ms |

Mate 60 上 Node 入口至 DSH 打印 Web 地址 6.372 秒，记录 5,004 次模块加载，累计读取 459 ms。本机鉴权跳转 303，已鉴权首页 200。ArkWeb 确认标题和回环，布局确认发送按钮与工作区选择。Home 重进后应用 PID 相同。上一次 0.4.5 试验在 Mate 60 的 Node 入口至 HTTP 验收为 14.206 秒，固定命令探针因 PRoot 的 waitpid 收到 EINTR 后退出。0.4.6 的 PRoot 在该错误上重试，修复后的 Bash 成功执行管道并写文件，从应用同一目录回读成功。先前 0.4.4 的 Mate 60 样本约 219.8 秒才显示页面。

本轮真机使用保留归档、独立账号和会话目录的标记模式。未做真机全新解包、旧历史迁移、Web 真模型对话、聊天工具自动调用 PRoot 或工作区隔离验收。Bash 在应用固定探针中执行，采用已打包的 Bash。制品同时保留旧 PRoot 启动路径，未激活原生标记时使用旧路径。

[计时数据](../../evidence/native-web-comparison-0.4.6.json) · Mate 60 页面（本机产物 `../dsh-client-preview/.build/native-web-bench/evidence/mate60-ui-0.4.6.log`） · Mate 60 Bash（本机产物 `../dsh-client-preview/.build/native-web-bench/evidence/mate60-shell-0.4.6.log`） · 全新模拟器（本机产物 `../dsh-client-preview/.build/native-web-bench/evidence/emulator-fresh-ui-0.4.6.log`） · 签名试验包（本机产物 `../dsh-client-preview/releases/DSH-Phone-Native-Web-0.4.6-Mate60-Bench.hap`）
