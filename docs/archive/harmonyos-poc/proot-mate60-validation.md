# PRoot 在 Mate 60 上的实机验证

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

2026-11-07。Mate 60 BRA-AL00，OpenHarmony 7.0.0.111，API 26，AArch64。通过 USB HDC 安装和拉起独立实验 HAP。复用此前探针的调试包名与签名。执行进程为应用 UID 20020306，域为 `debug_hap`。

## 原模拟器方案在真机上的边界

- 使用此前构建的完整签名 HAP `cdc211d04f9940575ac6bcda740ce86bc8fefce5e19db809f91ddf5cf3e050ec`。安装成功，PRoot 和预加载 loader 都进入，但首次映射 App 私有目录内的 ELF 时失败。即使外层 PRoot 返回 0，Shell 和 Node 的成功标记都未出现。 安装日志（本机产物 `../.build/proot-validation/full/mate60-install.log`） · 启动日志（本机产物 `../.build/proot-validation/full/mate60-shell.log`）
- 真实应用身份能创建被跟踪子进程。`PTRACE_TRACEME`、`GETREGSET`、`SETOPTIONS` 和系统调用捕获均通过。 系统调用对照（本机产物 `../.build/proot-validation/full/mate60-trace.log`）
- 直接映射对照中，App 文件目录的 BusyBox 请求 RX 返回 13，签名 HAP 的本地库目录内同源 BusyBox 文件请求 RX 成功，匿名内存改为 RX 返回 22。此结果只覆盖所测的映射请求。 映射对照（本机产物 `../.build/proot-validation/full/mate60-proot-map.log`）

## 签名包内交付 ELF 的实测结果

把 BusyBox、musl 和 Node 依赖随 HAP 签名放置，PRoot 将 Alpine 路径绑定到这些包内文件。验证 HAP SHA-256 为 `16046b281f9aa927498bc749a1b6053cbb04426d551516cef97aa40e900639c7`。

| 验收项 | 实测结果 |
| --- | --- |
| Alpine 3.22.8 Shell | 通过。读到发行版和 AArch64 信息，运行外部 BusyBox 命令、管道和退出码 37 检查，在映射根目录写入 `/marker`，再从 HAP 存储回读。 |
| 交互文本 Shell | 通过两轮。通过管道收到第一条命令的结果后，再发送第二条，两次均有独立输出标记。 |
| 系统 PTY | 失败。`openpty` 和直接打开 `/dev/ptmx` 都返回 13。Shell 进入管道交互，窗口尺寸及作业控制未通过。 |
| Linux Node.js 24.14.1 | 首轮失败。主 ELF 和 musl 已进入，动态加载 `libgcc_s.so.1` 返回 `Permission denied`。默认与 `--jitless` 均未执行到 JS。 |

签名 HAP（本机产物 `../.build/proot-validation/full/phone-packaged-signed.hap`） · Shell 实测日志（本机产物 `../.build/proot-validation/full/mate60-packaged-shell.log`） · PTY 和管道日志（本机产物 `../.build/proot-validation/full/mate60-proot-embedded-packaged-pty.log`） · Node 依赖加载日志（本机产物 `../.build/proot-validation/full/mate60-proot-embedded-packaged-node.log`）

PRoot 路径日志确认 `libgcc_s.so.1` 最终已指向签名包内的 `libguest_gcc.so`。按 ELF 虚拟加载跨度填充文件并重新签名后，原版 musl 仍返回同样的错误。 路径对照（本机产物 `../.build/proot-validation/full/mate60-node-diag.log`） · 填充制品测试（本机产物 `../.build/proot-validation/full/mate60-padded-proot-embedded-packaged-node-jitless.log`）

## 真机 Linux Node 启动修复

对 musl 1.2.5 的动态装载路径改为先预留虚拟地址空间，再按每个 `PT_LOAD` 的权限映射。以填充过的签名包内依赖为基线，单独切换这个 musl 构建后，Linux Node `--jitless` 成功进入 JS。默认模式到达 V8 初始化后触发断言并以信号 5 终止。改动及构建输入保存在 `.build/proot-validation/full/musl-1.2.5`。 [上游 musl 动态装载源码](https://git.musl-libc.org/cgit/musl/tree/ldso/dynlink.c?h=v1.2.5)

随后在 PRoot 子进程交接时复制参数和环境字符串，解决更换 musl 后外部 BusyBox 子命令的参数丢失。HAP `4db1b48ad9be290268f507677c3238faafe143cfdf1e8abad3482241e25e6210` 上，完整 Shell 测试重新通过。Linux Node 24.14.1 `--jitless` 实测通过文件读写改名删除、SHA-256、Worker、HTTP、`sh` 及 GNU Bash 5.2.37。复用已锁定 DSHM `fetch` 兼容层后，回环 `fetch` 通过。WebAssembly 在 `--jitless` 下仍不可用。

修复制品（本机产物 `../.build/proot-validation/full/phone-runtime-signed.hap`） · Shell 复测（本机产物 `../.build/proot-validation/full/mate60-runtime-proot-embedded-packaged.log`） · Node 与 fetch 矩阵（本机产物 `../.build/proot-validation/full/mate60-runtime-proot-embedded-packaged-node-jitless-shim.log`） · 默认 Node 模式崩溃（本机产物 `../.build/proot-validation/full/mate60-musl-proot-embedded-packaged-node.log`）

## DSH 启动过程

官方 DSH 0.2.2-rc.1 的 Web 启动已进入 `runCli`，初次失败于 `node-addon-require-builtin-linux-arm64-musl` 原生绑定无法加载。后续把该绑定、DSH `system.node`、Koffi musl 和 `libstdc++` 放进签名 HAP，已成功装机。新制品 `f3dda953d6c0696fcd16e2bb426f136a2f2e1b17fa169bcd0c1d4f597832ac95` 首次拉起时设备锁屏，`aa start` 返回 10106102。 首次 DSH 启动日志（本机产物 `../.build/proot-validation/full/mate60-runtime-proot-embedded-packaged-dsh-jitless-shim.log`） · 新版签名 HAP（本机产物 `../.build/proot-validation/full/phone-dsh-bindings-signed.hap`）

解锁后同一制品的 DSH Web HTTP 验收通过。服务绑定真机回环地址，未鉴权请求返回 401，启动令牌兑换 Cookie 返回 303，已鉴权首页和页面引用的入口 JavaScript 均返回 200。该次从探针进入到完成 HTTP 自检约 55 秒，未做性能基准或浏览器渲染验证。 真机 Web 日志（本机产物 `../.build/proot-validation/full/mate60-dsh-bindings-web.log`）

同一制品的 Headless 加会话发布兼容层，`renameat2(RENAME_NOREPLACE)` 的防覆盖和正常写入检查通过。DSH 接收了本机模拟模型流式响应，返回 `DSH_FIXTURE_OK` 并退出 0，实测新会话文件为 11396 字节。默认 `workspace-write` 下，DSH 找不到可用的沙箱后端，拒绝执行 Bash。模型回合与工具执行分别验收，实际模型 API 未测试。 真机 Headless 日志（本机产物 `../.build/proot-validation/full/mate60-dsh-headless.log`）

在独立 HAP 内另用 DSH 的 `danger-full-access` 模式测试本机模拟模型发出的固定 `printf` 命令。DSH 到达工具调用，但返回 `spawn bash ENOENT`，模型回合随后结束并写入 11182 字节的会话文件。该对照只覆盖固定命令。Linux Node 测试中用绝对路径调用 `/bin/bash` 已通过，两者分别记录。 固定命令对照（本机产物 `../.build/proot-validation/full/mate60-dsh-command.log`）

本轮兼容改动分别保存为 musl 逐段映射补丁（本机产物 `../.build/proot-validation/full/musl-per-segment-mapping.patch`） 与 PRoot 参数复制补丁（本机产物 `../.build/proot-validation/full/proot-copy-exec-arguments.patch`）。

## 手机 PoC 当前验收范围

按用户确认，本阶段暂缓系统 PTY、全屏终端和依赖 PTY 的持久交互 Shell。保留官方 DSH 的批量命令工具，通过受控子进程运行 Bash，回收 stdout、stderr 和退出码。DSH 的 `ctx.subprocess` 将普通命令与 `spawnTerminal` 分开，可通过现有服务接口适配鸿蒙。 [DSH 子进程接口](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/subprocess.md)

下一阶段的真机验收使用实际 HAP 和真实模型。用户从手机对话发起任务，DSH 在批准的工作区执行 Bash、回读生成的文件并在对话中返回结果。另验证越界写入被拒、长命令可取消且子进程退出、关闭重开后会话可继续。目前的成功证据覆盖 Shell 单独启动、Web HTTP 服务及模拟模型流式回合。DSH 工具执行、工作区约束和真实模型仍待验收。
