# DSH 剩余工作清点

截至 0.4.41，按当前随包 RC.4 锁定源码与本工程的实际调用证据统计。各版验收见各自制品记录。

- 28类工具包：23类已有实际调用证据，覆盖深度不同；5类为当前不适用／暂缓项（pwsh、pwsh-persistent、bash-persistent、terminal、workspace-dependencies）。
- 16 个官方可选 bundle 中，7 个完成当前验收（session-search、ralph、tool-worktree、badge-skill、session-titles、deepseek-chat-import、plugin-market），2 个暂缓（cua、terminal），7 个待完成。Inspector 已复现绑定缺失，Forge 已通过本地工作树场景。
- 7 个可选 bundle、5 组补充验收及 RC.5 升级合计 13 个工作项。官方源码标签和 npm `next` 均已发布 RC.5。

## 7 个待完成的可选 bundle

| 工作项 | 当前状态 |
| --- | --- |
| Inspector | Worker中require-builtin鸿蒙绑定缺失；Node本身Inspector已独立返回42，完整CDP未验 |
| personalized-recommendations | 未完成端到端验收 |
| voice-input | 未完成音频／提供者实际验收 |
| cot-translation | 未完成端到端验收 |
| auto-review | 未完成实际审批策略与生命周期验收 |
| liveshare | 未完成；涉及远端共享，沿用路线图阶段区分 |
| forge | 本地工作树正式接口已验证恢复、取消、重试和重启。Forge UI 和托管平台联动待验 |

## 5 组补充验收

1. 长会话与长任务包括真实 API context overflow、重复压缩及长目标压力。手动、取消、持久恢复和降低阈值的自动压缩已测。
2. PTC 边界压力包括符号链接、硬链接与并发移动父目录。现有执行限制为 partial。
3. 插件扩展兼容还需验证 Git 来源升级、在途取消、其他依赖组合及公共索引。npm 仓库纯 JS 依赖、升级、失败回滚、卸载和禁止安装脚本已有实测。
4. 账号与提供者还需验证完整官方登录授权、图片模型内容及其他提供者。真实 DeepSeek API Key 调用已测。
5. 最新真机交付仍需验证签名 HAP、主流程、长运行、前后台、网络切换与性能。Mate 60 当前不在线。

系统 PTY、Phone／Computer Use、Windows 专用工具和 desktop-only workspace-dependencies 按既有范围单列。语言服务器、原生 wheel、WASM 与原生 addon 组合按具体需要验收。

0.4.41 通过插件市场、LSP 开关与恢复回归。RC.5 升级单独锁定官方源码及 npm 生产依赖，并验证原权限、既有会话与新搜索路由。[0.4.41 证据](../evidence/emulator-plugin-market-0.4.41.json) · [官方 RC.5 发布](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.5)

[能力矩阵](../dsh-capabilities.md) · [官方包级清点](../research/dsh-rc4-capability-inventory.md)
