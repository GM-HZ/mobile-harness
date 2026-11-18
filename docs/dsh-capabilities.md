# 鸿蒙 DSH 能力与验收边界

当前应用 0.4.58，运行时为鸿蒙原生 Node 24.14.1 和官方 npm DSH `0.2.2-rc.5`。锁文件固定 331 个 RC.5 组件，HAP 包含适用的 330 个，macOS 专用可选组件由平台条件排除。Linux 工具按需通过 Alpine／PRoot 执行。

Git 子模块固定官方 RC.5 标签提交 `9c2670d3bce5275e0d1610272958121af87787bb`，与 npm 精确版本配套。[官方发布说明](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.5)

## 当前验收

0.4.58 修复溢出恢复时当前用户输入进入摘要的情况。模拟器直连公网 DeepSeek Flash，实际收到 HTTP 400 后只压缩先前历史，在同一回合返回准确结果。原历史保持完整，重启后仍可续接。重复溢出、手动及阈值压缩一起通过回归。 [实测记录](evidence/emulator-live-overflow-0.4.58.json)

0.4.57 后续使用已有 HAP 完成默认公网语音准备、三份资源 SHA-256 校验、ArkWeb 合成录音与回填。两张本地生成的随机色块图经正式附件接口提交，真实 DeepSeek Flash 逐一正确识别颜色，重启后附件一致。 [补验记录](evidence/emulator-public-voice-vision-0.4.57.json)

0.4.57 已通过回环 Relay 验证独立查看者读取共享历史、真实 DeepSeek Flash 回复、Host 授权边界和即时撤销。同一模型驱动一个 Goal 完成三个文件检查点。两次重启后工作历史与 Goal 状态完整，旧修订恢复被拒，当前修订可以继续。公网 Relay、实际跨设备交互和长时压力仍待验。 [补验记录](evidence/emulator-live-reader-goals-0.4.57.json)

0.4.57 的 ArkWeb 页面使用真实 DeepSeek Flash 翻译，移除测试密钥后仍可重启查看保存的译文。PluginManager 经公网 npm 安装合成插件的直接、传递与可选依赖，并复用包内 `@deepseek-ai/dsh-tools`。模型在重启后实际调用插件工具，卸载后复核原 profile。 [补验记录](evidence/emulator-public-plugin-translation-0.4.57.json)

0.4.57 的官方 Forge 使用随包交付的 Alpine ARM64 GitHub CLI，经本机 TLS 夹具验证指定提交的文件读取和两页 GraphQL 提交列表。真实 DSH Host 消费两条受控的 Messages HTTP 400 溢出响应，均完成压缩、原回合重试并在重启后继续使用最近检查点。同包通过标准 PTC、LiveShare、启动与故障恢复回归。 [0.4.57 证据](evidence/emulator-forge-overflow-0.4.57.json)

同一 Forge 适配随后在隔离服务通过评审、邀请评审和重启后合并。评审 503 返回未知且未重发，旧头提交不能评审或合并。0.4.57 调试签名包通过 DevEco 离线验签，设备 UDID 与安装仍待确认。 [补验记录](evidence/emulator-forge-writes-signed-0.4.57.json)

0.4.54 完成 Creator 的生成、安装、计数按钮、撤销提示、重启后的移除及从保留副本恢复。实际 npm 插件下载被取消后，配置一致，随后重新安装、升级、失败回滚和卸载均成功。0.4.55 的 LiveShare 经私有回环 Relay 验证发布、增加会话、重连和停止。 [0.4.54 与 0.4.55 证据](evidence/emulator-creator-liveshare-0.4.55.json)

0.4.53 在模拟器通过空缓存下载、原生 ArkWeb 触屏启动录音、真实录音器采集的合成普通话、草稿回填、取消和停用回收。Git 插件通过本机仓库固定提交安装、拒绝浮动分支升级和重启保留。Creator 已生成并安装可操作页面，完整撤销和恢复仍待验。 [0.4.53 证据](evidence/emulator-creator-and-voice-0.4.53.json)

0.4.51 提供官方语音输入 bundle，默认关闭。标准 Speech Remote 使用校验后的 SenseVoice 与 Silero 数据，在鸿蒙原生 Node 专属 worker 内完成普通话转写。连续两次转写、坏音频拒绝和停用回收通过。ArkWeb 录音与草稿回填继续验收。 [0.4.51 证据](evidence/emulator-voice-input-0.4.51.json)

0.4.47 修复裸绝对目录安装。最小夹具和 Creator 生成包均通过正式 PluginManager 安装。Auto review 通过明确选择的会话只读工具、重启保持和停用，受控测试通过畸形审查、拒绝和取消阻止写入，LiveShare 通过默认关闭和本机 Owner 接口，Forge 通过 ArkWeb 面板和本地工作树恢复。Creator 页签、公开共享和托管平台仍待完整验收。 [0.4.47 证据](evidence/emulator-optional-batch-0.4.47.json)

0.4.46 提供默认关闭的官方个性化推荐。实际模型和 ArkWeb 通过内置插件启用、页面位置选择、暂不创建和决定持久化。Creator 已生成页面包，安装被系统拒绝创建符号链接，页面操作、撤销和恢复仍待验。 [0.4.46 证据](evidence/emulator-personalized-recommendations-0.4.46.json)

0.4.45 提供默认关闭的思考内容翻译。ArkWeb 展开合成会话、切换原译文、重启复用、失败重试和停用取消通过，原会话事件逐条不变。受控 Bing／Google 验证协议与凭据隔离，真实 DeepSeek Flash 验证付费 API Key 路径。公开 Bing 返回 400 并报告不支持当前客户端，Google 在设备探针中超时。[0.4.45 证据](evidence/emulator-cot-translation-0.4.45.json)

0.4.44 提供默认关闭的官方 Inspector。模拟器用快捷键打开 ArkWeb 的 DevTools，实际 ArkWeb 和 Host 均经同源鉴权代理完成 CDP 查询。匿名代理与直接 Worker 请求被拒，跨重启启用和停用释放端口通过。[0.4.44 证据](evidence/emulator-inspector-0.4.44.json)

0.4.42 确认升级前后的会话和配置摘要一致。实际 DeepSeek 模型的 `web_search` 返回来源链接，会话事件确认调用官方 Messages 搜索。电脑通过正式 WebRuntime 的 provider 接口补验 DeepSeek 账号路由、其他模型路由、显式选择和可用性回退。[0.4.42 证据](evidence/emulator-dsh-rc5-0.4.42.json)

0.4.41 提供默认关闭的官方插件市场。模拟器用自建索引及 npm 仓库验证真实安装、纯 JS 依赖、升级和重启、用已保存仓库来源回滚激活失败的候选、模型再次调用旧版本工具、卸载和移除来源。ArkWeb 的安装确认显示来源，取消后未下载归档。更新允许按官方结果重启生效。[0.4.41 证据](evidence/emulator-plugin-market-0.4.41.json)

0.4.39 通过正式上传入口导入合成 DeepSeek v3 档案，验证标题、历史、图片、文件卡片、坏档案、上传中断和真实模型续接。导入结果在关闭插件与重启后仍可读。[0.4.39 证据](evidence/emulator-chat-import-0.4.39.json)

0.4.38 通过官方插件管理接口启停跟随会话的标题与 DSH 徽标技能。真实模型生成与固定标题、原有标题服务恢复、技能加载、官方 PNG 字节、工作区 Markdown 均已核对。[0.4.38 证据](evidence/emulator-titles-badge-0.4.38.json)

0.4.37 通过官方插件管理接口启停随包扩展，并验证实际 Forge 工作树恢复、取消、重试与应用重启。LSP 开关及故障恢复回归同时通过。[0.4.37 证据](evidence/emulator-worktree-catalog-0.4.37.json)

[0.4.36 证据](evidence/emulator-inspection-editing-0.4.36.json)绑定原子不覆盖发布适配、真实 Cordis 查询、替代编辑及六组受影响回归，共九组检查通过。插件诊断 Inspector 单独测试失败：Worker 的 profile-resolution bootstrap 无法选择鸿蒙 require-builtin 绑定；不计入通过。测试与原配置已恢复；未把前版11／18组冒充本版重跑。

[0.4.35 证据](evidence/emulator-lsp-0.4.35.json)绑定官方 LSP、准确编译器工具链及八组必要回归，共11组检查通过；原失败和测试修正全部单列，不把此前18／10组冒充本版全部重跑。默认权限和鉴权保留，旧 RC.3 会话30事件保留，测试凭据及临时配置清理，恢复普通模式。

本轮以 API 26 ARM64 Phone 模拟器为准。[0.4.31 证据](evidence/emulator-dsh-rc4-0.4.31.json)是升级与默认 PTC 基线；[0.4.32 证据](evidence/emulator-office-0.4.32.json)绑定 Office、18 组回归、最终包安装及恢复入口，两次构建的摘要和包内一致性分开记录。[0.4.33 证据](evidence/emulator-http-standard-0.4.33.json)绑定 HTTP/1 修复与 10 组新增／针对性回归，不把旧版 18 组说成本版重新全部执行。历史真机结果不能代替这版的真机回归。

[0.4.34 证据](evidence/emulator-subprocess-worktree-0.4.34.json)绑定公共 subprocess、可选工作树和 pnpm 卸载修复的准确 HAP。五组最终通过记录逐项列出来源：四组使用同一测试提交，子进程组修复收尾后单独重跑；失败运行亦保留。前述 18／10 组不冒充本版重新全部执行。

| 能力 | 本轮状态 |
| --- | --- |
| 覆盖升级与会话持久化 | 保留 RC.3 会话，实际运行 RC.4，鉴权请求 200、匿名请求 401 |
| 模型与工具调用 | 实际 DeepSeek API Key 模型调用，测试凭据退出时清除 |
| 工作区文件工具 | 通用 PTC 内嵌工具及标准 write／edit／grep／glob／read 均通过 |
| 原子创建与替代编辑 | 0.4.36 修复 hard-link EACCES，真实 ctx.fs 的竞争发布、取消与清理通过；官方字符串编辑、临时启用的 apply_patch、多文件预检及部分提交报告、越界和只读拒绝通过，保留默认开关。见 [适配](research/harmonyos-file-publication.md) |
| Cordis 查询与诊断 Inspector | Cordis 查询 Host 与真实 ArkWeb 的 API 分类、分页、schema 和保留结果通过。0.4.44 的独立 Inspector 通过正式 DevTools 代理执行 Host 与 ArkWeb CDP 求值，端点访问控制与停用回收已验 |
| Bash、Git、Python、pip、venv | 默认无系统沙箱则拒绝；精确命令单次审批后，两套 pip target／venv、Git、Node fetch、curl、SQLite 和时区夹具通过 |
| 工作区依赖 | 0.4.61 通过官方工具读取 Alpine Python、Node、pnpm 和库路径，Office 技能使用随包 Python。13 个库的版本核对、离线文档读写、pnpm exec 与重启复用通过。 [实测证据](evidence/emulator-workspace-dependencies-0.4.61.json) |
| 通用 PTC | 普通包默认提供 TypeScript 擦除、工作区文件读写、目录操作、元数据与跨目录相对路径 |
| PTC 执行模式 | 默认模式、REPL、无持久化 Script、持久化 Script 均通过 |
| PTC 文件策略 | 只读、工作区写、附加目录及目录边界拒绝通过 |
| PTC 单次审批 | 工作区到完整 App 文件授权、只读到工作区授权；拒绝、批准一次、等待中取消、恢复原权限均通过。保留状态模式也通过 |
| PTC 取消和生命周期 | 协作取消、死循环强制回收、归档恢复、真正 AgentHandle 销毁、持久记录恢复均通过 |
| 工作目录与 fork 续接 | 独立 cwd、相对文件、fork 继承、list／send／wait 与消息续接通过；强停重开后同一子会话仍保留 token 和目录。新增事件与字节结果分别核对，见 [续接补验](evidence/emulator-agent-continuation-0.4.33.json) |
| 公共子进程与可选工作树 | 真正 Git／Node、流式管道、字面 argv、嵌套 Node、环境脱敏、输出限额／spill、实际取消和销毁通过；官方 create_worktree 默认拒绝、明确选择完整权限后创建，目录／分支／提交／文件独立性、重启续接、脏工作树保留和干净工作树归档清理通过 |
| 自动目标续跑 | 初始轮只创建目标；实际自动轮通过 read／write／get_goal／update_goal 完成任务，隐藏输入／输出均为精确43字节，目标已清理；非长期压力或系统唤醒保证 |
| Workflow／子代理 | 同步超时、两类运行中取消、后台结果投递通过。0.4.58 两条 Workflow 同时运行，各完成四个真实子任务，单条峰值并发为二，结果隔离和 helper 回收已验。 [并发证据](evidence/emulator-pi-ai-workflow-0.4.58.json) |
| 自定义模型提供者 | 0.4.58 经标准设置热添加 pi-ai 路由，在 DeepSeek 公网验证 Chat Completions 和 Responses 的模型发现、文件读取工具往返与重启续接。 [模型路由证据](evidence/emulator-pi-ai-workflow-0.4.58.json) |
| MCP | Node 和 Python stdio 的初始化、工具列表、真实模型调用、进程关闭；Streamable HTTP 工具调用通过 |
| 定时任务 | 0.4.58 长测在第 106 秒强停重启，保留旧会话与待执行任务。跨过一小时后第六次真实模型投递通过，两小时长测尚在运行。 [检查点](evidence/emulator-workspace-dependencies-0.4.61.json) |
| LiveShare | 0.4.60 在实际 ArkWeb 完成隔离 Relay 所有者授权和 PKCE，重启恢复分享。独立查看者通过真实模型回合、范围拒绝、撤销和停止。公网 Relay 及真实身份提供方待验。 [实测证据](evidence/emulator-liveshare-owner-0.4.60.json) |
| 思考内容翻译 | 0.4.59 通过应用私有 `HTTPS_PROXY` 访问 Bing 和 Google 的官方默认地址，真实译文和记录可跨重启回读。ArkWeb 的 DeepSeek Flash、切换原译文、拒绝后保留原文和停用取消均通过。模拟器直连仍有 Bing 400 和 Google 超时。 [公网与 ArkWeb 证据](evidence/emulator-translation-proxy-0.4.59.json) |
| 插件及恢复 | 标准 bundle 安装、注入真实崩溃、自动安全模式及旧会话回读通过；实际点击设置恢复入口、原生正常模式按钮后恢复通过 |
| 插件管理补验 | 本版经实际 API 安装、启用、禁用和卸载自建 bundle，pnpm remove 退出0；postinstall 没有执行。恢复测试安装前备份原配置，结束后回普通模式且 manifest／lock 摘要一致；任意插件升级与安装脚本仍不据此承诺 |
| 官方插件市场 | 受控索引发现、分页缓存、仓库安装与纯 JS 依赖、拒绝不兼容版本、升级后重启、激活失败后跨重启回滚、卸载和 ArkWeb 确认／取消已验。公共索引与 Git 来源升级另行验收 |
| 会话压缩 | 官方 /compact 的真实摘要、命令／日志来源、完整工具配对、精确事实回忆与重启恢复通过；真实输出后 HTTP取消、忙碌拒绝、流故障及重试通过。完整standard临时预设的低阈值自动压力通过；原配置恢复。见 [补验证据](evidence/emulator-compaction-0.4.35.json)，非默认满容量或真实远端overflow压力保证 |
| LSP | 官方三插件与真实 TypeScript server；四种语义查询、精确位置／标准库、UTF-16、新内容、无结果、越界源拒绝、复用与进程组崩溃重建通过。自带 bundle 启停及重启保留通过，真实语义响应暂扣场景中的取消、provider 销毁及重试通过，非所有语言服务器保证。见 [实现](research/harmonyos-lsp.md) |
| Office | Office skill、DOCX／PPTX PDF、页面附件、Excel 公式重算、缓存、损坏文档拒绝和实际取消已通过；原生 worker 正常操作约 2–3 秒。销毁、超时、故障后新请求恢复及所有 helper 回收均已验证。见[实现与证据](research/harmonyos-native-office.md) |
| 目标、待办、团队任务与交付 | todo、内置 dsh-doc、present、目标创建／暂停／旧 revision 拒绝，以及团队依赖、认领、完成通过；目标和任务强停后保留，测试目标已清除、团队模式恢复关闭 |
| 提问、计划与插件发现 | 实际 Remote Events 的回答、取消、同会话继续，计划拒绝保持 active／批准退出，以及绑定本次工具的单次插件列表审批均通过。此项不等于 ArkWeb 视觉布局完整验收 |
| 网页工具 | HTTP/1、分块、HTML→Markdown、同源跳转、跨源目标拒绝、URL 校验、限额、实际取消及后续抓取、公网 HTTPS 和 DeepSeek 搜索通过。保留原 Undici 代理机制；电脑的原生／jitless 代理对照通过，见 [HTTP 实现](research/harmonyos-http.md) |
| 可选 Ralph 与会话搜索 | 临时标准 bundle 启用后，两轮不同 fresh 子代理、无父会话 seed、41字节文件结果、实际子请求中取消与 helper 回收均通过；归档会话重启后五个查询工具、跨工作区空搜索与拒绝读取通过。原 manifest／lock 字节恢复，见 [可选能力补验](evidence/emulator-optional-iteration-0.4.33.json) |
| 图片、Skills、插件纯 JS 依赖等 | 保留上游机制和既有适配，本轮未把所有可选插件逐一实测；图片与插件历史记录见[版本记录](releases.md) |

## 平台限制与未验项

- **Bash 隔离**：PRoot 不提供内核隔离。普通 Bash 继续拒绝没有系统沙箱的默认执行，仅经具体审批扩大权限。不能把它称为已实现 bwrap／Landlock。
- **PTC 范围**：独立进程和 seccomp 文件代理向上游报告 `partial` enforcement。它不是任意 Node／Linux API 执行环境；网络与子进程能力应调用 Host 暴露的工具。符号链接／硬链接攻击及并发移动父目录的完整压力回归尚未完成。
- **JIT／WASM**：主 Host 保持 jitless，Office 使用独立进程执行官方 WASM，PTC 使用同版本 Amaro 的 JS 产物处理 TypeScript。0.4.57 已在模拟器的 Alpine 子进程中验证默认设置下无 WASM，显式启用后可执行 WASM、TypeScript 文件并用 Node 自带的 fetch 取得 HTTP 200。真机 JIT 能力待复验。
- **系统工具**：共享库和 ELF 需匹配 ABI 和鸿蒙加载条件。pip 已验证纯 Python 包和公网 CPython 3.12 ARM64 musllinux `xxhash`。0.4.57 经 DSH 工具把实际 npm ARM64 musl addon 交给 Alpine Node 执行，主 Host 能加载 HAP 内置语音 addon，测试中的外部鸿蒙 addon 返回 `ERR_DLOPEN_FAILED`。其他 wheel、addon、APK 和安装脚本需按具体包验收。 [Node 补验](evidence/emulator-node-extensions-0.4.57.json) · [Python 补验](evidence/emulator-account-python-wheel-0.4.57.json)
- **系统视图与终端**：没有补造完整 `/proc`、`/sys` 或内核 namespace。系统 PTY、全屏交互终端和 Phone Use 沿用此前明确的暂缓范围。
- **浏览器与账号**：ArkWeb 用于应用界面。0.4.57 已从页面打开官方登录并返回聊天，回环账号服务验证 PKCE 交换、授权记录恢复及登出撤销。真实账号授权和 DeepSeek 之外的供应商端点待验。 [账号补验](evidence/emulator-account-python-wheel-0.4.57.json)
- **后台**：模拟器后台约 81 秒实测三次定时投递和真实模型回复，返回前台准确回忆原消息。系统终止后的唤醒、真机保活与跨进程状态待验证。 [前后台证据](evidence/emulator-context-background-0.4.57.json)
- **剩余能力清点**：Ralph、会话搜索、工作树、真实公网溢出恢复和两次受控重复溢出通过。多小时长任务压力与剩余可选 bundle 待验。LSP 当前验收为 TypeScript。Forge 的工作树与隔离服务链路已验，公网账号及托管仓库操作待验。公共 subprocess provider 支持标准输入输出，进程范围沿用上游 fallback 的观测限制。 [剩余清单](work/2026-11-18-remaining-capabilities.md)
- **设备**：Mate 60 当前没有在线 HDC 连接；本版真机表现、后台保活、长时间高并发与网络切换仍待验证。

随包保留官方 DSH 运行时和扩展体系。能力补齐范围以表中实测与限制为准，尚未达到桌面全功能等价。
