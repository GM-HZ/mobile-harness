# 鸿蒙 DSH 能力与验收边界

当前应用 0.4.32，运行时为鸿蒙原生 Node 24.14.1 和官方 npm DSH `0.2.2-rc.4`。328 个直接安装的 DSH 包均固定为 RC.4，生产依赖由锁文件装配。Linux 工具仍按需进入 Alpine／PRoot，Host 不运行于 PRoot。

官方现已发布 RC.4 源码标签，Git 子模块固定 `3f321d32bfe382212a8ed8785c1d47a5a300aa23`，与 npm 精确版本配套。0.4.31 最初升级时的公开源码延迟保留在历史证据中。发布包前端内嵌的短提交是构建标识，源码 pin 使用官方发布标签的完整提交。

## 当前验收

本轮以 API 26 ARM64 Phone 模拟器为准。[0.4.31 证据](evidence/emulator-dsh-rc4-0.4.31.json)是升级与默认 PTC 基线；[0.4.32 证据](evidence/emulator-office-0.4.32.json)绑定本次 Office、18 组回归、最终包安装及恢复入口。两次构建的准确摘要与包内文件一致性分开记录。历史真机结果不能代替这版的真机回归。

| 能力 | 本轮状态 |
| --- | --- |
| 覆盖升级与会话持久化 | 保留 RC.3 会话，实际运行 RC.4，鉴权请求 200、匿名请求 401 |
| 模型与工具调用 | 实际 DeepSeek API Key 模型调用，测试凭据退出时清除 |
| 工作区文件工具 | 通用 PTC 内嵌工具及标准 write／edit／grep／glob／read 均通过 |
| Bash、Git、Python、pip、venv | 默认无系统沙箱则拒绝；精确命令单次审批后，两套 pip target／venv、Git、Node fetch、curl、SQLite 和时区夹具通过 |
| 通用 PTC | 普通包默认提供 TypeScript 擦除、工作区文件读写、目录操作、元数据与跨目录相对路径 |
| PTC 执行模式 | 默认模式、REPL、无持久化 Script、持久化 Script 均通过 |
| PTC 文件策略 | 只读、工作区写、附加目录及目录边界拒绝通过 |
| PTC 单次审批 | 工作区到完整 App 文件授权、只读到工作区授权；拒绝、批准一次、等待中取消、恢复原权限均通过。保留状态模式也通过 |
| PTC 取消和生命周期 | 协作取消、死循环强制回收、归档恢复、真正 AgentHandle 销毁、持久记录恢复均通过 |
| Workflow／子代理 | 两个真实并行子任务、同步超时、运行中取消、活跃子任务取消、后台结果投递通过 |
| MCP | Node 和 Python stdio 的初始化、工具列表、真实模型调用、进程关闭；Streamable HTTP 工具调用通过 |
| 定时任务 | 持久化后强停重开，任务到期投递并由模型回复通过 |
| 插件及恢复 | 标准 bundle 安装、注入真实崩溃、自动安全模式及旧会话回读通过；实际点击设置恢复入口、原生正常模式按钮后恢复通过 |
| Office | Office skill、DOCX／PPTX PDF、页面附件、Excel 公式重算、缓存、损坏文档拒绝和实际取消已通过；原生 worker 正常操作约 2–3 秒。销毁、超时、故障后新请求恢复及所有 helper 回收均已验证。见[实现与证据](research/harmonyos-native-office.md) |
| 目标、待办、团队任务与交付 | 额外测试已实际调用 todo、内置 dsh-doc、present、目标创建／暂停／旧 revision 拒绝，以及团队依赖、认领、完成；目标和任务强停后保留。整组测试仍在网页项失败，不称整组通过 |
| 网页工具 | 公网 HTTPS 抓取成功；本机 HTTP/1 抓取返回 fetch failed，继续调查。RC.4 的匿名 HTTP 提供者允许内网与本机，不能将该错误当成网络隔离 |
| 图片、Skills、插件纯 JS 依赖等 | 保留上游机制和既有适配，本轮未把所有可选插件逐一实测；图片与插件历史记录见[版本记录](releases.md) |

## 平台限制与未验项

- **Bash 隔离**：PRoot 不提供内核隔离。普通 Bash 继续拒绝没有系统沙箱的默认执行，仅经具体审批扩大权限。不能把它称为已实现 bwrap／Landlock。
- **PTC 范围**：独立进程和 seccomp 文件代理向上游报告 `partial` enforcement。它不是任意 Node／Linux API 执行环境；网络与子进程能力应调用 Host 暴露的工具。符号链接／硬链接攻击及并发移动父目录的完整压力回归尚未完成。
- **JIT／WASM**：主 Host 保持 jitless；Office 另用已探测可用的独立原生 Node 执行官方 WASM。TypeScript 在 PTC 中由同版本 Amaro 的 JS 产物处理；这不等于任意 shell 的 `node file.ts` 或所有 WASM 包已经支持。
- **系统工具**：共享库和 ELF 仍需匹配 ABI 和鸿蒙加载条件。pip 已支持纯 Python 包；任意原生 wheel、任意 APK 下载后直接执行、任意 npm 原生 addon／安装脚本不能据此宣称兼容。
- **系统视图与终端**：没有补造完整 `/proc`、`/sys` 或内核 namespace。系统 PTY、全屏交互终端和 Phone Use 沿用此前明确的暂缓范围。
- **浏览器与账号**：没有随包 Chromium／Playwright；手机 ArkWeb 不等于可供 Agent 使用的浏览器。完整官方账号授权、每一种模型提供者和每个实验插件尚未逐一回归。
- **后台**：定时任务跨 App 重启已测，不代表 App 被系统终止时仍会唤醒执行。运行中 Bash 的 OS 进程、PTC 的内存变量不能据此承诺跨进程存活。
- **设备**：Mate 60 当前没有在线 HDC 连接；本版真机表现、后台保活、长时间高并发与网络切换仍待验证。

随包保留官方 DSH 运行时和扩展体系。能力补齐范围以表中实测与限制为准，尚未达到桌面全功能等价。
