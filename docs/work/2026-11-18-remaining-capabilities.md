# DSH 剩余工作清点

截至0.4.36，按官方RC.4锁定源码与本工程证据统计，计数不表示桌面功能完成百分比，也不表示前版测试都在新版重跑。

- 28类工具包：23类已有实际调用证据，覆盖深度不同；5类为当前不适用／暂缓项（pwsh、pwsh-persistent、bash-persistent、terminal、workspace-dependencies）。
- 16个官方可选bundle：3个有限场景通过（session-search、ralph、tool-worktree）；2个按既有范围暂缓（cua、terminal）；11个尚未通过，其中Inspector已复现错误，10个尚未完成独立端到端验收。
- 另有6组补充验收；与11个bundle合计17个工作项。这是工作包计数，不是17个尚未实现的核心工具。

## 11个可选bundle

| 工作项 | 当前状态 |
| --- | --- |
| Inspector | Worker中require-builtin鸿蒙绑定缺失；Node本身Inspector已独立返回42，完整CDP未验 |
| personalized-recommendations | 未完成端到端验收 |
| badge-skill | 未完成端到端验收 |
| session-titles | 未完成端到端验收 |
| voice-input | 未完成音频／提供者实际验收 |
| cot-translation | 未完成端到端验收 |
| auto-review | 未完成实际审批策略与生命周期验收 |
| liveshare | 未完成；涉及远端共享，沿用路线图阶段区分 |
| plugin-market | 未完成实际发现／安装／升级验收 |
| forge | Git／工作树工具已通，Forge UI／托管平台联动未全验 |
| deepseek-chat-import | 未完成真实导入／失败与恢复验收 |

## 6组补充验收

1. 工作树：缺失目录恢复与专门取消；创建、持久化、重启和归档已测。
2. 长会话／长任务：真实API context overflow、重复压缩及长目标压力；手动、取消、持久恢复和降低阈值的自动压缩已测。
3. PTC边界压力：符号链接、硬链接与并发移动父目录；不因此将现有partial enforcement改称内核沙箱。
4. 插件扩展兼容：实际升级／失败回滚、依赖和安装脚本边界；既有安装、启停、卸载、崩溃恢复不能代替任意插件兼容。
5. 账号／提供者：完整官方登录授权流程、图片模型内容及其他提供者按可用凭据验收；真实DeepSeek API Key调用已测。
6. 最新真机交付回归：准确签名HAP，主流程、长运行、前后台、网络切换与性能；Mate60当前不在线，不能沿用旧版证据冒充通过。

不计入上述17项：系统PTY、Phone／Computer Use、Windows专用工具、desktop-only workspace-dependencies；也不将所有语言服务器／原生wheel／任意WASM与原生addon组合扩成无限验收。

DSH已升级官方最新RC.4；0.4.36生产改动、九组必要检查和证据已推送至既有分支。当前优先处理Inspector、工作树补验、长会话压力；其余逐项保留明确通过／失败／阶段边界。

[能力矩阵](../dsh-capabilities.md) · [官方包级清点](../research/dsh-rc4-capability-inventory.md)
