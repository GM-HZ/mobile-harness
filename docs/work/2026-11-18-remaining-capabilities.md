# DSH 剩余工作清点

截至 0.4.37，按官方 RC.4 锁定源码与本工程的实际调用证据统计。各版验收见各自制品记录。

- 28类工具包：23类已有实际调用证据，覆盖深度不同；5类为当前不适用／暂缓项（pwsh、pwsh-persistent、bash-persistent、terminal、workspace-dependencies）。
- 16个官方可选bundle：3个有限场景通过（session-search、ralph、tool-worktree）；2个按既有范围暂缓（cua、terminal）；11个尚未通过，其中Inspector已复现错误，10个尚未完成独立端到端验收。
- 另有 5 组补充验收，与 11 个可选 bundle 合计 16 个工作项。0.4.37 已完成工作树恢复、取消、重试和重启续接的专项验收。

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
| forge | 本地工作树正式接口已验证恢复、取消、重试和重启。Forge UI 和托管平台联动待验 |
| deepseek-chat-import | 未完成真实导入／失败与恢复验收 |

## 5 组补充验收

1. 长会话与长任务包括真实 API context overflow、重复压缩及长目标压力。手动、取消、持久恢复和降低阈值的自动压缩已测。
2. PTC 边界压力包括符号链接、硬链接与并发移动父目录。现有执行限制为 partial。
3. 插件扩展兼容还需验证升级、失败回滚、依赖和安装脚本边界。安装、启停、卸载和崩溃恢复已有证据。
4. 账号与提供者还需验证完整官方登录授权、图片模型内容及其他提供者。真实 DeepSeek API Key 调用已测。
5. 最新真机交付仍需验证签名 HAP、主流程、长运行、前后台、网络切换与性能。Mate 60 当前不在线。

不计入上述17项：系统PTY、Phone／Computer Use、Windows专用工具、desktop-only workspace-dependencies；也不将所有语言服务器／原生wheel／任意WASM与原生addon组合扩成无限验收。

DSH 保持官方最新 RC.4。0.4.37 已验证工作树恢复，并登记 Forge、Ralph、会话搜索及独立工作树的默认关闭入口。诊断 Inspector 和长会话压力仍在后续清单。[0.4.37 证据](../evidence/emulator-worktree-catalog-0.4.37.json)

[能力矩阵](../dsh-capabilities.md) · [官方包级清点](../research/dsh-rc4-capability-inventory.md)
