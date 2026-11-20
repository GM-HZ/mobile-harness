# PC 对齐能力差距评估（2026-11-20，动态 ELF 之后）

先说明当前事实：**动态 ELF 执行能力还没有落地**。目前打通的是**静态 ELF**（`/usr/bin/mh-exec` + `mh-install`，模拟器与 Mate 60 真机验证）。动态 ELF（PT_INTERP/共享库）的 loader 支持是本轮及后续工作，原理上可行（签名 musl 解释器可执行映射、已签名库可 dlopen），但尚未实现和验证。

以下按"**假设动态 ELF 也打通**"评估与完整 harness（PC 对齐）的距离。

## 能力矩阵

| 能力域 | PC 上的 DSH | 鸿蒙现状（有证据） | 动态 ELF 之后 | 差距性质 |
| --- | --- | --- | --- | --- |
| 核心 Agent / 工具 / MCP / 插件 / 工作流 | 完整 | 已迁移，gate 覆盖 | 不变 | ✅ 已成 |
| 语音、LiveShare、Forge、Office、账号、本地模型 | 完整 | 已验收（公开 Relay、真机语音待外部条件） | 不变 | ✅ 基本成 |
| 静态 CLI 工具 | 任意下载 | **已通**（mh-install + mh-exec） | 更强 | ✅ 已成 |
| 动态链接 CLI 工具 | 任意 | 未实现（本轮计划） | 大多数发行版 CLI 可跑（依赖已签名库） | ⚠️ 工程，1–2 轮 |
| 任意二进制"透明"执行（`./tool`） | 是 | 需显式 `mh-exec`/`mh-install`；PRoot loader 透明改造被 pinned 源码缺失阻塞 | 仍不能透明 | ⚠️ 工程（找 patched PRoot 树或换集成点） |
| 原生扩展 `.so` / Python wheel / `.node` | 任意 | `dlopen` 复制库 Permission denied；只能构建期签名绑定（如 sharp/vips/koffi） | 需要 dlopen shim 或构建期扩展机制 | 🔶 高难工程 |
| 语言工具链（gcc/clang/rust/go、make、cmake） | 任意 | 没有；且编译出的二进制需要签名/内存加载，依赖库需逐个可加载 | 编译器本身可作为动态 ELF 跑，但仍需库与构建期产物落地 | 🔶 可做但成本高 |
| 包管理器（apt/pacman/apk/npm/pip 原生部分） | 任意 | pip 纯 Python ✅；npm JS ✅；原生包 ❌（dlopen）；apk/dpkg 无 root，装进 rootfs 也无法执行未签名 ELF（动态 loader 后可部分可用） | 纯语言包可用，原生包仍需签名/loader 扩展 | 🔶 部分 |
| Node JIT | 有 | **默认 `--jitless`**（实测 V8 选项 `default: --jitless`），匿名可执行内存虽可用但当前 Node 构建默认关闭 | 需换 Node 构建/验证 `--no-jitless` | ⚠️ 可评估 |
| PTY / terminal / 交互式 shell | 完整 | guest 无 `/dev/ptmx`、`/dev/pts`，`openpty` 报 "out of pty devices" | **无解（设备节点层缺失）** | ❌ 平台边界，维持延期 |
| GUI 自动化 / cua / Phone Use / computer use | 完整 | 未实现，原定延期 | 与 ELF 无关 | ❌ 延期 |
| 容器/namespace/系统服务（systemd、docker、dbus、mount） | 完整 | 无 root、无内核 namespace/cgroups | 与 ELF 无关 | ❌ 平台边界 |
| 系统视图（完整 /proc、/sys、内核态） | 完整 | 未补造 | 与 ELF 无关 | ❌ 明确不补 |
| 多语言 LSP | 完整 | TS/Python 已验；其它语言需要原生 server 二进制 | 动态 ELF 可跑 server（依赖库满足时） | ⚠️ 工程，取决于语言 |
| 后台保活 / 网络切换 / 长时并发 | 完整 | 模拟器部分验证；真机长项待验 | 无关 | ⚠️ 待验 |
| Windows 专用工具 | 视平台 | 明确排除 | 无关 | ❌ 有意排除 |

## 结论：还剩多远

分三类：

1. **已完成（模拟器 + 真机）**：核心 harness、静态工具执行、语音/LiveShare/Forge/Office/账号/本地模型等。这部分基本与 PC 等价（平台差异外）。
2. **可达但有工程量（动态 ELF 之后 1–3 轮集中投入）**：
   - 动态 ELF loader（进行中）；
   - 透明 exec（找 patched PRoot 树或 Host 层方案）；
   - 原生扩展的签名/加载机制（dlopen shim 或构建期 overlay 扩展）；
   - Node JIT 重编译评估；
   - 可选：多语言 LSP / 语言工具链按需打包。
3. **平台硬边界（PC 对齐不可能或明确不做）**：
   - PTY/terminal（无 `/dev/ptmx`、`/dev/pts`）；
   - GUI/屏幕自动化（cua、Phone/Computer Use）；
   - 容器/namespace/systemd/dbus；
   - 完整 /proc、/sys、内核态视图；
   - Windows 专用工具。

用一句话概括：**动态 ELF 打通后，"命令执行与工具生态"的差距会从"只能跑随包工具"缩小到"能跑大多数发行版 CLI"；完整的 PC 对齐仍差 1 个高难工程项（原生 dlopen 扩展/签名机制）+ 若干可做项（透明执行、JIT、LSP/工具链按需打包），以及 4 个平台硬边界（PTY、GUI 自动化、容器/系统服务、系统视图）。**

按 DSH 日常使用（Agent、工具、MCP、插件、工作流、网络、文件、语音、LiveShare、多模型路由）估算：**已具备 ~85–90%**；剩余 10–15% 主要集中在上述工程项与平台边界。
