# RC.4 能力清点与剩余验收

2026-11-18。清点依据是锁定的官方 RC.4 源码工具目录、Web standard／PTC preset、官方可选 bundle 清单和本工程的 npm 锁文件。源码位置与运行配置分别核对；包存在不能视为启用，更不能视为实际执行通过。

工具目录列出 28 个工具包，当前默认 npm DSH 层包含其中 27 个；LSP 不在默认安装中。它们包含 Windows 专用、其他 preset、桌面专用与可选终端，不能全部自动开启。下面是验收状态，不是兼容性保证。

| 工具包（@deepseek-ai/dsh-tool-） | 随包 | 当前结论 |
| --- | --- | --- |
| ask-user | 是 | 实际回答、等待中取消、同会话继续已验；计划拒绝与批准亦通过 |
| executor-ptc | 是 | 通用 PTC 与模式／审批／生命周期已验；见 0.4.31、0.4.32 和本轮回归 |
| bash | 是 | 默认拒绝与精确命令审批、工具链及取消既有证据；PRoot 不提供内核隔离 |
| office | 是 | 三个工具、附件、公式、缓存、异常、取消与生命周期已验 |
| present | 是 | 真实工具及持久交付事件已验，测试文件随后按夹具清理 |
| pwsh | 是 | Windows 选择项；鸿蒙未启用，不承诺 PowerShell |
| cordis | 是 | 可选 inspector 能力；未逐项端到端回归 |
| bash-persistent | 是 | 可选终端能力；系统 PTY 暂缓，未承诺完整持久终端 |
| pwsh-persistent | 是 | Windows／可选终端，不在鸿蒙验收范围 |
| str-replace-editor | 是 | 其他 preset 的编辑入口；当前标准使用 fs edit，未单测此替代入口 |
| fs | 是 | read／write／edit 既有完整工具链回归；apply_patch 仍遵循上游默认开关 |
| fs-search | 是 | glob／grep 及范围检查既有回归 |
| terminal | 是 | 可选系统 PTY 终端；按先前要求暂缓 |
| goal | 是 | 创建、暂停、旧 revision 拒绝及重启后恢复已验；自动续跑完成仍待验 |
| schedule | 是 | 持久任务强停重开后投递和实际模型回复已验；非系统唤醒 |
| lsp | 否 | 默认 npm DSH 未安装此工具及 provider；语言服务器路径待单独装配与验证 |
| ralph | 是 | 随包的可选 bundle 默认关闭；实际多轮 fresh-child 验收待完成 |
| skill | 是 | 内置 dsh-doc／Office 已验；自定义 Skill 有历史证据 |
| session-query | 是 | 随包可选 session-search；实际索引与查询待验 |
| subagent | 是 | Workflow spawn 的真实并行子任务已验；独立 fork、继承与后续控制待进一步验收 |
| subagent-control | 是 | 运行中取消／子任务取消有证据；list／send／wait 工具组合待补验 |
| jobs | 是 | Workflow 后台投递本轮通过；Bash job 输出与取消有历史证据 |
| agent-team | 是 | 依赖、认领、完成、ready 更新及重启持久化已验 |
| todo | 是 | 精确全量 todo/write 快照已验 |
| working-directory | 是 | 标准能力已装配；切目录与子任务 cwd 独立性待补验 |
| workflow | 是 | 真实并行、同步超时、实际同步片段取消、子任务取消与后台投递已验 |
| workspace-dependencies | 是 | 上游仅在 desktop＋DSH_PRIMARY_RUNTIME 时启用；当前 web profile 不启用 |
| web | 是 | 实际 HTTP/1、HTTPS、搜索、跳转、限额与取消通过；代理有电脑双运行时对照 |

官方还提供 16 个默认关闭的可选 bundle，以及 Claude Code／Codex 两个按需安装入口。Phone／Computer Use、系统 PTY 的既有暂缓要求保持；任意外部 CLI、其他供应商账号、语音提供者或桌面插件不能凭组件存在宣称鸿蒙兼容。

优先继续：工作目录和 fork／控制、自动目标续跑及压缩、Ralph 和会话搜索，随后验证工作树与 LSP 对 Host 子进程、路径和工具链的真实要求。每一项先复现、优先使用上游插件／provider seam，验证实际结果、取消与生命周期；不通过关闭能力或移除断言假称补齐。

[当前能力矩阵](../dsh-capabilities.md) · [0.4.33 证据](../evidence/emulator-http-standard-0.4.33.json) · [官方 RC.4 源码](https://github.com/deepseek-ai/deepseek-harness/tree/3f321d32bfe382212a8ed8785c1d47a5a300aa23)

本清单表示“全部能力”目标仍在进行；当前 0.4.33 是已验证的交付节点。
