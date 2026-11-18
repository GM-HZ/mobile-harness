# DSH 剩余工作清点

截至 0.4.57，按本工程的实际调用证据统计。工具包与可选包清单从 RC.4 建立，RC.5 的升级对照和测试见制品记录。

- 28类工具包：23类已有实际调用证据，覆盖深度不同；5类为当前不适用／暂缓项（pwsh、pwsh-persistent、bash-persistent、terminal、workspace-dependencies）。
- 16 个官方可选 bundle 中，10 个完成当前验收（session-search、ralph、tool-worktree、badge-skill、session-titles、deepseek-chat-import、plugin-market、inspector、auto-review、personalized-recommendations），2 个暂缓（cua、terminal），4 个待完成。Forge 已通过本地工作树场景。
- 4 个可选 bundle 和 5 组补充验收合计 9 个工作项。官方 RC.5 升级已在 0.4.42 验证。

## 4 个待完成的可选 bundle

| 工作项 | 当前状态 |
| --- | --- |
| voice-input | 0.4.57 已从空缓存经默认公网来源选择下载三个锁定文件，并完成 ArkWeb 合成录音、草稿回填、取消和 worker 回收。显式公网镜像也通过 SHA-256 和转写，Hugging Face 主站在本模拟器上连接被拒。真机麦克风授权和采集待验 |
| cot-translation | 正式 ArkWeb 界面、受控 Bing／Google、真实 DeepSeek Flash、重启复用和停用取消已验。0.4.54 复验两个公开匿名端点均失败 |
| liveshare | 0.4.55 通过回环 Relay 发布、增加来源会话、Host 重启重连、撤销和停用回收。公网 Relay、真实账户授权及跨设备查看者仍待验 |
| forge | 本地工作树正式接口已验证恢复、取消、重试和重启。0.4.47 已验 ArkWeb 面板。0.4.57 通过包内 gh 读取本机 TLS 夹具的文件与分页提交。公网账号和评审、合并等写入待验 |

## 5 组补充验收

1. 长会话已通过受控 Messages HTTP 400 的两次自动压缩、重试及重启恢复。真实公网模型的上下文上限和长目标压力仍待实测。
2. PTC 边界压力包括符号链接、硬链接与并发移动父目录。0.4.57 已复验基础文件授权、越界拒绝、目录操作和取消回收。执行限制继续报告 partial。
3. 插件扩展兼容已通过本机 Git 来源的固定提交安装和升级，浮动分支被拒。0.4.54 已通过 npm 下载在途取消及恢复。其他依赖组合及公共索引仍待验。npm 仓库纯 JS 依赖、升级、失败回滚、卸载和禁止安装脚本已有实测。
4. 账号与提供者已验证真实 DeepSeek Flash 识别会话附带的两张随机图片，重启后附件可回读。完整官方登录授权与其他提供者待验。
5. 最新真机交付仍需验证签名 HAP、主流程、长运行、前后台、网络切换与性能。Mate 60 当前不在线。

系统 PTY、Phone／Computer Use、Windows 专用工具和 desktop-only workspace-dependencies 按既有范围单列。语言服务器、原生 wheel、WASM 与原生 addon 组合按具体需要验收。

0.4.41 通过插件市场、LSP 开关与恢复回归。0.4.42 升级 RC.5，覆盖安装后验证原权限、旧会话、实际搜索路由及受影响能力。[0.4.41 证据](../evidence/emulator-plugin-market-0.4.41.json) · [0.4.42 证据](../evidence/emulator-dsh-rc5-0.4.42.json)

0.4.44 通过 Inspector 的真实 Host 和 ArkWeb 诊断。官方 bundle 默认关闭，关闭时回收 Worker。[0.4.44 证据](../evidence/emulator-inspector-0.4.44.json)

0.4.45 通过翻译界面、真实 Flash、Inspector 和恢复。公开匿名端点的失败仍计入剩余项。[0.4.45 证据](../evidence/emulator-cot-translation-0.4.45.json)

[能力矩阵](../dsh-capabilities.md) · [官方包级清点](../research/dsh-rc4-capability-inventory.md)

0.4.47 通过本地目录包装、Auto review 基础链路、LiveShare 本机管理、Forge UI、Inspector 及恢复，保留两次 Creator 的具体结果。 [0.4.47 证据](../evidence/emulator-optional-batch-0.4.47.json)

0.4.51 通过语音提供者及 HAP 升级审计，录音前端与 Creator 路径未收尾，待办仍为 10 项。 [0.4.51 证据](../evidence/emulator-voice-input-0.4.51.json)

0.4.53 的实际测试覆盖语音冷准备、ArkWeb 录音和 Git 升级。Creator 已通过生成、安装和计数器操作，撤销、恢复和独立的启动崩溃仍待验。 [本轮证据](../evidence/emulator-creator-and-voice-0.4.53.json)

0.4.54 已完整验收个性化推荐和 Creator。实测从页面生成、安装和操作，经过撤销、重启移除，再原样恢复。撤销、恢复均未启动新模型回合。五次连续普通重启均加载 ArkWeb。 [本轮证据](../evidence/emulator-creator-liveshare-0.4.55.json)

0.4.57 实测 Forge GitHub 读取与长会话溢出恢复。两项使用回环夹具，待公网验收，因此剩余总数保持 9。 [本轮证据](../evidence/emulator-forge-overflow-0.4.57.json)

0.4.57 补验公网语音准备和真实图片识别，计入原语音与账号两项的部分完成。 [本轮证据](../evidence/emulator-public-voice-vision-0.4.57.json)
