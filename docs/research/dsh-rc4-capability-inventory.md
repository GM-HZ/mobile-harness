# RC.4 能力清点与剩余验收

2026-11-18。清点依据是锁定的官方 RC.4 源码工具目录、Web standard／PTC preset、官方可选 bundle 清单和本工程的 npm 锁文件。源码位置与运行配置分别核对；包存在不能视为启用，更不能视为实际执行通过。

工具目录列出 28 个工具包，上游默认 npm DSH 层包含其中 27 个；0.4.35 由本工程补充 LSP 三插件，工具包现均随包，但不自动开启平台不适用项。它们包含 Windows 专用、其他 preset、桌面专用与可选终端，不能全部自动开启。下面是验收状态，不是兼容性保证。

| 工具包（@deepseek-ai/dsh-tool-） | 随包 | 当前结论 |
| --- | --- | --- |
| ask-user | 是 | 实际回答、等待中取消、同会话继续已验；计划拒绝与批准亦通过 |
| executor-ptc | 是 | 通用 PTC 与模式／审批／生命周期已验；见 0.4.31、0.4.32 和本轮回归 |
| bash | 是 | 默认拒绝与精确命令审批、工具链及取消既有证据；PRoot 不提供内核隔离 |
| office | 是 | 三个工具、附件、公式、缓存、异常、取消与生命周期已验 |
| present | 是 | 真实工具及持久交付事件已验，测试文件随后按夹具清理 |
| pwsh | 是 | Windows 选择项；鸿蒙未启用，不承诺 PowerShell |
| cordis | 是 | 0.4.36 真实模型查询 Host 四类和 ArkWeb 五类 provider，准确 schema、分页、完整 retention、拒绝与重启通过；与独立诊断 Inspector 区分，后者 Worker 鸿蒙绑定错误仍待修复 |
| bash-persistent | 是 | 可选终端能力；系统 PTY 暂缓，未承诺完整持久终端 |
| pwsh-persistent | 是 | Windows／可选终端，不在鸿蒙验收范围 |
| str-replace-editor | 是 | 0.4.36 修复原子创建后，创建／查看／替换／歧义／插入／删除及工作区、只读拒绝通过；仍由 preset 选择 |
| fs | 是 | read／write／edit 既有回归；临时开启 apply_patch 的创建／移动／删除、预检零修改、部分提交报告和权限通过，正式默认开关不变 |
| fs-search | 是 | glob／grep 及范围检查既有回归 |
| terminal | 是 | 可选系统 PTY 终端；按先前要求暂缓 |
| goal | 是 | 创建、暂停、旧 revision 拒绝及重启后恢复已验；自动一轮真实读写与完成通过，长期压力仍待验 |
| schedule | 是 | 持久任务强停重开后投递和实际模型回复已验；非系统唤醒 |
| lsp | 是 | 0.4.35 装配真实 TS server，四种语义、UTF-16／物理路径／新内容、越界拒绝、复用与崩溃重建通过；bundle 跨重启启停和实际服务器取消／销毁通过，见 [LSP 实现](harmonyos-lsp.md) |
| ralph | 是 | 默认关闭；实际两轮 fresh-child、无父 seed、字节结果、子请求取消与 helper 回收通过 |
| skill | 是 | 内置 dsh-doc／Office 已验；自定义 Skill 有历史证据 |
| session-query | 是 | 默认关闭；归档持久会话重启索引、五个查询工具与跨工作区拒绝通过 |
| subagent | 是 | Workflow spawn 的真实并行子任务已验；fork 继承、消息续接、独立 cwd 与同一子会话跨重启继续通过 |
| subagent-control | 是 | 运行中取消／子任务取消有证据；list／send／wait 与消息续接已实际调用并通过 |
| jobs | 是 | Workflow 后台投递本轮通过；Bash job 输出与取消有历史证据 |
| agent-team | 是 | 依赖、认领、完成、ready 更新及重启持久化已验 |
| todo | 是 | 精确全量 todo/write 快照已验 |
| working-directory | 是 | 切目录、相对文件、子任务 cwd 独立性与重启后继续均通过 |
| workflow | 是 | 真实并行、同步超时、实际同步片段取消、子任务取消与后台投递已验 |
| workspace-dependencies | 是 | 0.4.61 通过官方工具查询 Alpine 应用内 Python、Node、pnpm 与库路径。Office 技能和本地脚本经过模拟器验证 |
| web | 是 | 实际 HTTP/1、HTTPS、搜索、跳转、限额与取消通过；代理有电脑双运行时对照 |

官方还提供 16 个默认关闭的可选 bundle，以及 Claude Code／Codex 两个按需安装入口。Phone／Computer Use、系统 PTY 的既有暂缓要求保持；任意外部 CLI、其他供应商账号、语音提供者或桌面插件不能凭组件存在宣称鸿蒙兼容。

已补验 [工作目录、fork 与自动目标](../evidence/emulator-agent-continuation-0.4.33.json)。[Ralph 与会话搜索的限定场景](../evidence/emulator-optional-iteration-0.4.33.json)亦已通过。[0.4.34](../evidence/emulator-subprocess-worktree-0.4.34.json)补齐公共子进程、官方 create_worktree、重启续接和归档清理，实际插件启停／卸载及崩溃恢复也通过；0.4.37 已通过 Forge 本地工作树的恢复、取消、重试和重启。0.4.35 进一步补齐限定的 TypeScript LSP；[0.4.35 压缩补验](../evidence/emulator-compaction-0.4.35.json)进一步通过真实手动摘要、持久恢复、HTTP取消／忙碌／流故障重试及完整standard临时预设的自动压力场景；默认满容量和真实API overflow不据此承诺。继续Inspector、替代编辑入口和其他适用可选能力。每一项先复现、优先使用上游插件／provider seam，验证实际结果、取消与生命周期；不通过关闭能力或移除断言假称补齐。

[当前能力矩阵](../dsh-capabilities.md) · [0.4.33 证据](../evidence/emulator-http-standard-0.4.33.json) · [官方 RC.4 源码](https://github.com/deepseek-ai/deepseek-harness/tree/3f321d32bfe382212a8ed8785c1d47a5a300aa23)

本清单表示“全部能力”目标仍在进行；0.4.34 是此前交付节点；0.4.35 的 LSP 验证和必要回归另行记录。
