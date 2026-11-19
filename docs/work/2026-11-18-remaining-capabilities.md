# DSH 剩余工作清点

截至 0.4.68，按本工程的实际调用证据统计。工具包与可选包清单从 RC.4 建立，RC.5 的升级对照和测试见制品记录。

- 28 类工具包中 25 类已有实际调用证据。3 类为当前不适用或暂缓项（pwsh、pwsh-persistent、terminal）。
- 16 个官方可选 bundle 中，11 个完成当前验收（session-search、ralph、tool-worktree、badge-skill、session-titles、deepseek-chat-import、plugin-market、inspector、auto-review、personalized-recommendations、cot-translation），2 个暂缓（cua、terminal），3 个待完成。Forge 已通过本地工作树场景。
- 3 个可选 bundle 和 4 组补充验收合计 7 个工作项。官方 RC.5 升级已在 0.4.42 验证。

## 3 个待完成的可选 bundle

| 工作项 | 当前状态 |
| --- | --- |
| voice-input | 0.4.57 通过默认公网模型准备、合成录音与草稿回填。0.4.62 用 DSH 实际录音按钮触发模拟器系统授权，确认真实音轨和取消释放，权限已恢复。0.4.69 在同一制品复跑转写、ArkWeb 草稿与系统麦克风权限生命周期。真机采集和真人说话转写待验（物理设备麦克风与正式签名安装） |
| liveshare | 0.4.60 通过隔离 Relay 的 ArkWeb 登录、重启恢复、访客真实模型回合和撤销。0.4.64 将访客 PTC 绑定实际分享目录和链接档位，完成并存链接、可写、派生、拒绝扩大权限及回收测试。0.4.66 通过真实模型识别共享图片、访客读取和重启恢复。0.4.67 补齐访客文本与图片上传，实测会话范围拒绝、取消和真实模型处理。公网 Relay、真实身份提供方及公网跨设备部署待验：官方 Relay 服务端不随上游包或本仓库交付，ArkWeb 只接受 https 或回环 Relay，公网验收需外部部署环境；本机可做的是自建 Relay 的双模拟器跨设备与真实 OIDC 协议链路 |
| forge | 本地工作树和 ArkWeb 面板已验。0.4.62 用包内 gh 通过桌面认证代理读取 GM-HZ/omnix 公开 PR，隔离服务中的评审、邀请及合并通过复验。0.4.65 接入设备授权，通过 GitHub 公网设备码签发和取消，并在隔离服务验证设备登录、重启、读取及退出。真实账号授权和托管仓库写操作待验：需要用户在 github.com 完成一次设备码同意（设备端真实凭据）以及一个可写仓库的真实副作用授权 |

## 4 组补充验收

1. PTC 边界压力包括符号链接、硬链接与并发移动父目录。0.4.57 已复验基础文件授权、越界拒绝、目录操作和取消回收。执行限制继续报告 partial。0.4.69 对普通文件读取与 stat 补充单链接校验，与写路径一致；路径解析每次从预打开根描述符用 `RESOLVE_NO_SYMLINKS` 重新解析，并发移动父目录只会退化为 `ENOENT`／`ELOOP`。模拟器实测应用数据视图拒绝创建符号链接和硬链接，工作区无符号链接、普通文件链接数为 1，因此端到端链接压力场景仍缺夹具；脚本 `tests/smoke/emulator-ptc-link-fixture.py` 可在每次验收时复跑该前置条件。
2. 插件扩展兼容已通过固定 Git 提交、npm 下载中取消、升级、回滚与卸载。0.4.57 通过公网 npm 的 ESM、CommonJS、传递、可选依赖和包内 DSH peer。公网 ARM64 musl addon 已由 DSH 工具在 Alpine 子进程中加载。0.4.66 通过 DSH 配置的 HTTPS 代理加载公开社区索引，实测 6,112 条目、搜索、分页缓存和重启恢复。模拟器无代理直连超时。0.4.68 补验常见包自动选择 Alpine ARM64 musl addon、命令入口和 NumPy/OpenBLAS、orjson。外部鸿蒙 addon 在主 Host 加载失败的原因是鸿蒙动态链接器只允许从应用安装目录 `libs/arm64` 加载原生库，插件解包在应用数据目录的绝对路径 `dlopen` 被拒（与 jitless 和 N-API 版本无关）。宿主可加载随 HAP 打包的 addon；外部插件应提供 Alpine ARM64 musl addon 或纯 JavaScript。用户运行时安装鸿蒙 addon 到主 Host 属平台限制，不作为支持承诺。
3. 账号与提供者已验证真实 DeepSeek Flash 识别会话附带的两张随机图片，重启后附件可回读。0.4.57 已从 ArkWeb 打开 DeepSeek 官方登录页，隔离回环服务通过授权回调、重启保留与登出撤销。0.4.58 经标准设置添加 pi-ai 路由，使用 DeepSeek 公网通过 Chat Completions 和 Responses 两种协议的模型发现、工具往返与重启续接。0.4.69 经标准设置接入本机 Ollama，两种 OpenAI 兼容协议完成模型发现、流式请求、工具目录、图片附件和重启保持；本机 752M 模型不具备稳定工具调用与视觉问答能力，该轮只证明非 DeepSeek 端点的接入语义，工具和视觉语义仍由 DeepSeek 路由覆盖。真实账号授权仍待验。
4. 0.4.58 两小时模拟器后台长测已完成 7 次真实模型投递。第 106 秒强停后会话和四个未投递任务保留，回前台准确回忆，测试凭据已移除。Mate 60 当前离线，设备 UDID 匹配、覆盖安装、主流程、长运行、前后台、网络切换与性能仍待实测。 [两小时实测](../evidence/emulator-schedule-soak-0.4.58.json)

系统 PTY、Phone／Computer Use 和 Windows 专用工具按既有范围单列。语言服务器、原生 wheel、WASM 与原生 addon 组合按具体需要验收。

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

同一制品通过独立 LiveShare 查看者和三轮 Goal 跨重启续跑。Goal Gateway 对超轮次限制和旧修订均返回通用错误，状态保持一致，允许的修订可继续。 [本轮证据](../evidence/emulator-live-reader-goals-0.4.57.json)

同一制品通过真实 ArkWeb 翻译、公网 npm 插件依赖图、模型调用和卸载。Host 复用包内 DSH peer，上游 profile 保留 `autoInstallPeers: false`。 [本轮证据](../evidence/emulator-public-plugin-translation-0.4.57.json)

同一制品通过 Alpine N-API、WASM、TypeScript、原生 fetch 和公网 npm ARM64 musl addon。主 Host 保持 jitless，能加载 HAP 内的语音 addon，测试中的外部鸿蒙 addon 加载失败。真机 JIT 待复验。 [本轮证据](../evidence/emulator-node-extensions-0.4.57.json)

同一制品通过官方登录入口、回环账号交换及真实 PyPI ARM64 musllinux wheel。设备上的账号授权和其他原生 wheel 保留待验。 [本轮证据](../evidence/emulator-account-python-wheel-0.4.57.json)

Forge 经包内 gh 验证评审、邀请评审和跨重启合并，以及旧提交、403 拒绝和 503 未知结果。调试签名 HAP 通过离线验签，真机安装待验。 [本轮证据](../evidence/emulator-forge-writes-signed-0.4.57.json)

公网 DeepSeek Flash 实际返回上下文上限，模拟器以同一错误回放两次自动恢复。独立前后台回归在三次实际模型任务完成后核对同一个 Host 和完整历史。 [本轮证据](../evidence/emulator-context-background-0.4.57.json)

0.4.58 修复两次真实超限之间的摘要选区，端到端公网恢复约 19 秒。受控重复溢出、手动及阈值压缩和旧会话审计通过。 [本轮证据](../evidence/emulator-live-overflow-0.4.58.json)

同一制品通过两种 pi-ai 协议及两条并发 Workflow。八个子任务的结果分别回到所属会话，两个 Workflow helper 均已退出。 [本轮证据](../evidence/emulator-pi-ai-workflow-0.4.58.json)

独立模拟器通过 Bing、Google 公网代理链路和 ArkWeb 受控回归。同时启动两小时后台定时任务测试，首个检查点涵盖一次强停重启与四次成功投递。 [本轮证据](../evidence/emulator-translation-schedule-0.4.58.json)

0.4.59 修复了匿名翻译对 DSH 代理配置的应用。使用两个官方默认地址完成真实 CONNECT 和中文翻译，重启后完整回读两次译文。ArkWeb 的取消、失败保留原文和 DeepSeek Flash 复验通过。该模拟器的直接公网访问仍受环境限制。 [本轮证据](../evidence/emulator-translation-proxy-0.4.59.json)

0.4.60 通过原生 LiveShare 弹窗和隔离 Relay 的所有者登录。复验真实 DeepSeek 登录入口及回环账号生命周期。0.4.58 并行后台测试在 30 分钟检查点完成第五次投递。 [本轮证据](../evidence/emulator-liveshare-owner-0.4.60.json)

0.4.61 补齐工作区依赖工具和 13 个 Office Python 库。模型经正式工具找到路径后，批准的本地命令完成文件操作和 pnpm 执行。0.4.58 并行后台测试在一小时检查点完成第六次投递。 [本轮证据](../evidence/emulator-workspace-dependencies-0.4.61.json)

0.4.62 补齐 Minimal 预设的持久 Bash，支持跨轮目录、环境变量和函数、后台任务、退出码与两条会话隔离。默认权限下在启动前拒绝，已明确选择完整文件权限的会话可用。验证用户取消后回收进程、下轮重建、显式退出和配置恢复。 [本轮证据](../evidence/emulator-persistent-bash-0.4.62.json)

同一制品完成模拟器原生麦克风、真实 GitHub PR 只读及两小时 Workflow 首轮。包内 gh 在隔离服务的写操作复验通过。 [本轮证据](../evidence/emulator-voice-forge-workflow-0.4.62.json)

0.4.63 补齐 Python 源码和类型存根导航，修复了公共语言服务器运行时路径及原生 Host 启动计时。在独立模拟器全新安装和重启均加载 ArkWeb，复验 TypeScript 和安全恢复。 [本轮证据](../evidence/emulator-python-lsp-0.4.63.json)

0.4.64 修复 LiveShare 程序沿用宿主会话文件权限的问题。模拟器实测并存链接的档位权限、可写文件、只读派生与重放、程序要求扩大权限时的拒绝、worker 回收和主人执行。 [本轮证据](../evidence/emulator-liveshare-ptc-0.4.64.json)

0.4.65 增加 Forge 的原生 GitHub 账号入口。公网设备码与取消通过，隔离授权验证同一设备账号跨重启接续、Forge 文件读取和退出。 [本轮证据](../evidence/emulator-forge-account-0.4.65.json)

0.4.66 集中回归插件市场、翻译代理和 LiveShare 附件。 [本轮证据](../evidence/emulator-market-liveshare-0.4.66.json)

0.4.67 访客页面改用标准按会话授权的上传接口。验证真实模型处理上传附件，并复验主人图片通过旧接入读取和跨重启保持。 [本轮证据](../evidence/emulator-liveshare-guest-uploads-0.4.67.json)

0.4.58 通过 DSH 直连公网的完整溢出恢复。请求收到真实 HTTP 400 后，摘要只覆盖早前历史，原回合准确重试，重启后仍可回忆。两次受控重复溢出、普通阈值与手动压缩通过。同一 Goal 的三轮操作与重启通过。 0.4.62 的两小时 Workflow 通过全部 5 个检查点，完成 10 条主 Workflow、40 个子任务和 10 个 helper 回收。0.4.67 复验两条并发 Workflow。 [长测证据](../evidence/emulator-workflow-soak-0.4.62.json)

0.4.68 修复带命令入口的 npm 插件安装，验证公开 npm 原生依赖组合、PyPI 原生 wheel、插件启用与升级回滚。同一制品复验了公网插件索引、Forge 公共 PR 读取、PTC 附加目录、Node／Python MCP、LiveShare 访客附件和 ArkWeb 重启。 [本轮证据](../evidence/emulator-native-package-compat-0.4.68.json)

0.4.69 记录本轮收口：PTC 单链接读取加固与链接夹具前置条件（`tests/smoke/emulator-ptc-link-fixture.py`），崩溃恢复、语音转写、本机 Ollama 路由回归，证据见 [能力矩阵](../dsh-capabilities.md) 与 [本轮实测](../evidence/emulator-capability-parity-0.4.69.json)。仍未完成的三项（公网 Relay／真实身份提供方、真实 GitHub 账号授权与托管仓库写、真机麦克风与真人说话）均由外部条件阻塞，不是本仓库可独立闭环的代码项。
