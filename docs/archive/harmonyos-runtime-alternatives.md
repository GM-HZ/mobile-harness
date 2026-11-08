> 早期方案讨论原文。架构推断、性能数据和平台兼容判断按历史资料保存，部分主张未经本项目验证。当前决策和实测以[研究索引](../research/harmonyos-runtime.md)为准。

针对你的目标（在鸿蒙手机上部署 Claude Code / DeepSeek Harness，且避开 QEMU 的高损耗），现有方案可以按 **Node.js 运行时的落地方式** 和 **隔离边界** 分成几条线。以下是调研清单，每条都附了原理、代表项目、开销、前置条件和已知坑点。

---

### 方案一：原生 Node.js 嵌入 HAP（应用进程内运行，`--jitless`）

**原理**：把裁剪后的 Node.js 运行时和 DSH 核心树直接打进鸿蒙的 HAP 包，在 **应用进程内** 启动一个本地 Host（监听 `127.0.0.1`），UI 层通过 ArkUI 或 WebView 连接这个本地 Host。不是虚拟机，不是 proot，Node 直接跑在鸿蒙的沙箱里。

**代表项目**：
- **HDSH**（`hnmrxz/deepseek-harness-desktop-HarmonyOS`）：HAP 内自带 Node 运行时（自建、`jitless`）和 DSH 核心，支持手机/平板/折叠屏/2in1。
- **DSHM**（`sol5766/dshm`）：同样把 DSH 运行本体装进 HAP，Node 随包分发，构建期自签名。
- **`dsh-harmonyos-pc`**（`QinpanWan`）：更偏工程化的一套适配方案，包含启动补丁、`node_modules` 补丁脚本，专门处理鸿蒙文件系统“不支持硬链接、`chmod` 被拒”等问题。

**性能开销**：**极低**。没有虚拟化、没有指令翻译，CPU 效率接近原生。代价是 JS 执行走 `--jitless` 解释模式，纯 JS 逻辑会慢一些，但远好于 QEMU 的全模拟开销。

**隔离性**：**较弱**。隔离边界来自鸿蒙的 **应用沙箱**，而不是 Linux 的 namespace/cgroup。DSH 的 Host 和应用在同一进程内，安全语义简化，但不提供 Linux 容器级的进程/文件系统隔离。

**前置条件 / 已知硬约束**：
- **必须 `--jitless`**：鸿蒙拒绝 JIT 的 `PROT_EXEC`，不加 `--jitless` 会直接崩溃；而 `--jitless` **连带禁用 WebAssembly**，导致依赖 WASM 的 `undici` fetch 失效，需要项目方通过模块名解析钩子 + 全局 `fetch` 垫片来绕过。
- **原生 `.node` / ELF 模块加载受限**：`node-pty`、`Koffi`、原生 ELF 在鸿蒙设备上直接加载不了，`dsh-harmonyos-pc` 的做法是打启动补丁 **禁用依赖原生二进制的插件行**。
- **文件系统坑**：不支持硬链接、`chmod 600` 被拒、挂载点只读句柄打不开，需要补丁脚本绕开。
- **包体较大**：DSHM 的 HAP 约 **300 MiB**，因为要把 Node 运行时和原生库全部随包分发。

**适合谁**：**最贴合你部署 DSH 的目标**。如果你能接受 `--jitless` 的性能折损和“没有 Linux 容器级隔离”，这是开销最低、改动最直接的一条路。建议优先去 HDSH 和 DSHM 的仓库看 Release 和 README，确认是否已适配你的手机型号。

---

### 方案二：proot / chroot 用户态隔离（Termux + proot-distro / Termony）

**原理**：用 **ptrace 系统调用拦截** 在用户态“伪造”一个 chroot 根目录，不需要 root，也不启动完整 Linux 内核。你在里面得到一个 Ubuntu/Debian/Alpine 的 rootfs 视图，Node.js 可以装在 proot 外层或内层。它 **不是 QEMU 那种指令级模拟**，开销主要来自 ptrace 拦截，而不是 CPU 指令翻译。

**代表项目 / 路径**：
- **Termux + proot-distro**：在鸿蒙上通过 Termux 安装 `proot-distro`，再 `proot-distro install ubuntu-24.04`，在 Ubuntu rootfs 里装 Node.js 和 Claude Code。Android 上已有成熟先例（Termux + proot-Debian 跑 Claude Code）。
- **proroot**：搜索结果中多次提到用 `--no-ptrace` 启动 proroot 容器，目标是降低 proot 的 ptrace 开销。
- **Termony**（`TermonyHQ/Termony`）：面向鸿蒙的 Termux 兼容层，其 `qemu-vroot-aarch64` 被描述为“用户态 QEMU 模仿 proot 行为”，但项目仍在进行中。

**性能开销**：**中等偏低**。内存常驻方面，参考数据：华为 MatePad Pro 上 Ubuntu 21.04 容器 **内存常驻约 120 MB**，启动 Xfce4 桌面后总占用约 800 MB。ptrace 开销对命令行 Agent 通常可以接受，但 **不会像原生 HAP 那样“几乎零开销”**。

**隔离性**：**比原生 HAP 强**。proot 提供了文件系统命名空间映射和“准 root”视图，进程看到的 `/` 是一个临时根目录，不触碰宿主系统分区。但它 **不是真正的内核级容器**：cgroup、完整的 namespace 隔离、systemd 都不可用。

**前置条件 / 已知坑点**：
- **鸿蒙的应用子进程限制**：proot 可能触发子进程限制，官方建议用 `--no-ptrace` 启动 proroot，或在“开发人员选项”中开启 **USB 调试 + 应用调试** 来临时放宽限制。
- **Docker 不可用**：实测 `pkg install docker` 会报 `cgroups v1 not available`，proot 内也无法启动 systemd/cgroup 依赖的服务。
- **Node.js 版本和原生模块**：在 proot 内安装 Node.js 通常可行，但 `node-pty` 等原生模块仍然可能遇到鸿蒙 `dlopen` / `seccomp` 限制，需要实测。

**适合谁**：如果你 **需要 Linux 命令行隔离边界**（让 Agent 的 shell 操作不直接暴露在鸿蒙应用沙箱里），并且能接受比原生 HAP 更高的开销和更多的手动配置，这条线值得优先调研。可以直接参考 Android 上 Termux + proot 跑 Claude Code 的步骤，迁移到鸿蒙的 Termux 环境。

---

### 方案三：QEMU 全模拟（HiSH 等）——作为“对照基线”，不建议作为目标

**原理**：在鸿蒙上跑一个 **完整的 ARM64 Linux 内核** + Alpine/Ubuntu rootfs，QEMU 负责模拟硬件和指令执行。

**代表项目**：**HiSH**（`harmoninux/HiSH`），支持手机/平板/2in1，默认 Alpine，可导入 Ubuntu 24.04 / Debian 12。

**性能开销**：**高**。手机端 **不支持 JIT**，只能用 QEMU TCI 解释器，性能远低于 JIT 版本；开发者版 JIT 相比解释执行可提升 **5–6 倍甚至更高**，但手机用不上。参考数据：分配 4 核 + 6GB RAM 时，Geekbench 5 得分约为 **原生鸿蒙的 65%**；这还是在较理想配置下的全模拟开销。

**隔离性**：**最强**。完整的 Linux 内核和 rootfs，真正的进程/网络/文件系统边界，可以跑 systemd 等完整栈。

**已知限制**：手机端 JIT 缺失是硬伤；应用市场版本因政策禁用 JIT，性能更差；自行签名安装可以保留 JIT，但仅限于 Pad/2in1，手机仍不支持。

**定位**：可以作为 **兼容性兜底** 或对照基线，但你的判断是对的——它不适合作为 DSH/Claude Code 的日常运行环境。

---

### 方案四：容器 / Docker——在鸿蒙 NEXT 上原生不可行

**结论**：**当前不可行**。鸿蒙 NEXT 使用自研微内核，**不提供 Linux 的 cgroups、namespace、OverlayFS** 等容器依赖的内核特性。Docker daemon 会直接报错 `cgroups v1 not available`。已有 `docker-moby-harmony` 项目在记录适配方案，但尚未改变“原生 Docker 跑不起来”的现状。

**对你的意义**：如果你原本希望“用 Docker 隔离 DSH/Claude Code”，这条路在手机上暂时走不通，只能退回到 **proot** 或 **原生 HAP** 两条线。

---

### 方案五：AidLux（兼容层方案，但版本兼容性是硬伤）

**原理**：通过 **共享 Linux 内核** 的方式融合 Android/HarmonyOS 与 Linux，性能损耗较小，不需要完整虚拟机。

**致命限制**：AidLux 官方标注支持 **HarmonyOS 4 及以下**，**不兼容 HarmonyOS NEXT**。在鸿蒙 5.0 上已有用户反馈初始化失败。如果你的设备是纯血鸿蒙 NEXT，这条线基本可以暂时排除；如果是 HarmonyOS 4.x，可以作为一个低开销的候选，但需要实测。

---

### 对比速览

| 方案 | 核心机制 | 性能开销 | 隔离强度 | 部署 DSH/Claude 可行性 | 主要障碍 |
|---|---|---|---|---|---|
| **原生 HAP 内嵌 Node** | 应用进程内 `--jitless` | **极低**（JS 解释执行） | 应用沙箱（弱） | **最高**，已有多个 DSH 项目 | `--jitless` 禁 WASM；原生模块加载受限 |
| **proot / chroot** | 用户态 ptrace 拦截 | **中等**（ptrace 开销） | 准 Linux 文件系统隔离（中） | **较高**，需手动装 Node | 子进程限制；无 cgroup/systemd |
| **QEMU 全模拟（HiSH）** | 完整指令模拟 | **高**（手机无 JIT） | 完整 Linux 内核（强） | 兼容兜底 | 手机 JIT 缺失，性能损耗大 |
| **Docker** | 内核 cgroups/namespace | — | 内核级（强） | **不可行** | 鸿蒙微内核不提供 Linux 容器特性 |
| **AidLux** | 共享内核融合 | 低 | 中等 | 视鸿蒙版本 | 不兼容 HarmonyOS NEXT |

---

### 给你的调研优先级建议

**第一优先：方案一（原生 HAP）**。直接去 **HDSH** 和 **DSHM** 的 GitHub Releases 看是否有适配你机型的 HAP，或者看 `dsh-harmonyos-pc` 的补丁脚本能否复用。这条线最贴合“部署 DSH”的目标，开销也最低，主要需要确认 `--jitless` 下 DSH 的核心功能（尤其是网络请求和工具调用）是否可用。

**第二优先：方案二（proot）**。如果你坚持要一个 **Linux 隔离边界**，去调研鸿蒙上 **Termux + proot-distro** 的实际可行性，重点确认两件事：你的设备能否绕过子进程限制（`--no-ptrace` 或调试模式），以及 proot 内安装 Node.js 和运行 DSH 时是否触发 `dlopen`/`seccomp` 拦截。Android 上的 Claude Code + proot 步骤可以作为迁移参考。

**方案三（HiSH）和方案四（Docker）** 可以作为“已知边界”记录下来，不必投入主要精力；**方案五（AidLux）** 只在你的设备是 HarmonyOS 4.x 时才值得看一眼。
