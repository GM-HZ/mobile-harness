# PRoot 在鸿蒙 Phone 模拟器上的验证

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

后续的 Linux Node.js、交互终端、官方 DSH 和真机签名进度见 [扩展验证报告](proot-full-validation.md)。

## 后续修复已跑通 Alpine Shell

2026-11-07 12:04。独立 HAP `org.harmonypoc.prootpreload` 从默认入口启动，成功在同一 Phone 模拟器上执行 Alpine 3.22.8 的 `/bin/sh`。通过 BusyBox 外部命令、管道、子 Shell 退出码 37、映射根目录的文件写入和回读。HAP 侧随后在自己的 `filesDir/alpine/marker` 读取到了同一内容。Shell 报告 AArch64，UID/GID 20020077，与 HAP 的实际应用身份一致。

修复复用 PRoot 的 ELF 装载脚本。HAP 预先加载 loader 共享库，创建 PRoot 和被跟踪子进程。原 loader `execve` 被拒时，PRoot 为子进程准备 `argv`、`envp` 和辅助向量，交给已映射的 loader 运行。loader 用模拟器许可的文件映射载入 Alpine ELF 和 musl，继续用 `ptrace` 转换文件路径。HiSH 在 QEMU 里使用自己的 Linux 内核，当前实验的 Linux 用户态程序使用模拟器的鸿蒙内核。 [HiSH 项目说明](https://github.com/harmoninux/HiSH)

- 验证 HAP SHA-256 `4e816dacb62f4fbeab2a50da41305be20ba77caac2504d7a3ed1b2a9e136f058`。通过 HDC 安装后，使用 `aa start -b org.harmonypoc.prootpreload -a EntryAbility` 从默认入口执行。 验证 HAP（本机产物 `../.build/proot-validation/preload-verified-unsigned.hap`）
- 同一 PID 的日志包含 `GUEST_OK`、`3.22.8`、`aarch64`、`pipeline-ok`、`EXIT_37_OK`、`rootfs-write` 和 HAP 侧文件回读标记。结果为 `exit=0 signal=0 wait_errno=0`。 默认入口实测日志（本机产物 `../.build/proot-validation/preload-default-device.log`）
- 补丁基于下文固定的 Termux PRoot 和 Termony OHOS 补丁。在应用 Termony 补丁后运行 `git apply --check` 通过。复用已构建的 talloc 静态归档，编译共享库和独立 HAP。 PRoot 补丁（本机产物 `../.build/proot-validation/proot-preload.patch`） · HAP 启动代码（本机产物 `../.build/proot-validation/preload-probe/entry/src/main/cpp/poc.c`） · 构建与部署脚本（本机产物 `../.build/proot-validation/run-preload.sh`）

当前验证覆盖 AArch64 的小型 Alpine Shell 工作负载，使用同一应用的子进程和固定测试命令。预加载路径保留进程的部分既有内存和文件描述符，完整 `execve` 语义、任意 ELF、交互 PTY、Linux Node.js、DSH 和真机兼容性仍待验证。此前普通 PRoot 启动失败的记录如下。

## 普通 PRoot 启动基线

2026-11-07。验证附件方案二能否在普通 HAP 身份下启动 Linux Shell。采用 Termony 的鸿蒙 PRoot 移植和 Alpine ARM64 最小文件集，目标是先跑通 `/bin/sh` 并读取发行版标记、执行外部命令、在映射后的根目录写文件。实验独立于 DSHM 和现有 Node PoC。

**Linux Shell 未启动。** PRoot 能在 HAP 的子进程中运行，`ptrace` 能截获系统调用并改写执行路径。内核对改写后的 PRoot loader 执行请求返回 `EACCES`。这台模拟器上的普通调试 HAP 因此未达到进入 Linux Node.js 验证的前提。

## 环境和结果

DevEco Phone 模拟器 `127.0.0.1:5555`，OpenHarmony 7.0.0.105，API 26，AArch64。探针 `org.harmonypoc.prootprobe` 是无额外权限的独立调试 HAP。应用日志记录 UID 20020076、`debug_hap` 域。HDC 用来安装、拉起、读日志，另以 UID 2000 的 HDC Shell 做对照。

| 操作 | 实测结果 |
| --- | --- |
| HAP `fork` + 子进程 `PTRACE_TRACEME` | 通过。`GETREGSET`、`SETOPTIONS` 成功，`PTRACE_SYSCALL` 捕获到信号 133 |
| HAP 直接 `execve` 系统 `/system/bin/sh` | `EACCES`（13） |
| HAP 子进程对自己的空测试目录调用 `chroot` | `EPERM`（1） |
| HAP 直接执行随包放置的 PRoot CLI | `EACCES`（13），连 `--version` 也无法进入 |
| HAP 加载 PRoot `.so`，子进程调用入口并查询版本 | 成功输出 PRoot 5.1.0，退出码 0 |
| PRoot 默认配置和 `PROOT_NO_SECCOMP=1` | 都解析到了 Alpine 的 `/bin/sh` 和 `/lib/ld-musl-aarch64.so.1`，执行时报 `Permission denied` |
| 诊断构建记录 PRoot 改写后的 `execve` | 目标是 `/data/storage/el1/bundle/libs/arm64/libproot_loader.so`，改写返回 0，内核返回 `-13` |
| 模拟器 HDC Shell 对照 | PRoot CLI 能打印版本。Termony 原补丁忽略失败的 `PTRACE_TRACEME`，运行停在 SIGSTOP。保留错误检查后记录 `ptrace(TRACEME): Permission denied`，退出码 1 |

日志里的 PRoot 子进程退出码 0 与实际 `execve` 错误同时出现。独立的 `GUEST_OK` 输出、Alpine 版本输出和写文件检查均未达到，因此结果为失败。`PROOT_NO_SECCOMP=1` 仅让 PRoot 停用自己的 seccomp 加速，仍走 `ptrace`。

## 制品和复现依据

- PRoot 来源是 Termony `2fe84795201dbe14a586819f7de641db6b6c18b7` 构建配置指定的 Termux PRoot `60485d2646c1e09105099772da4a20deda8d020d`，应用其 OHOS 补丁，依赖 talloc 2.4.3。诊断版保留 `PTRACE_TRACEME` 失败检查，另加两处 `execve` 日志。 [Termony 移植目录](https://github.com/TermonyHQ/Termony/tree/2fe84795201dbe14a586819f7de641db6b6c18b7/build-hnp/proot)
- Alpine 3.22.8 aarch64 官方 minirootfs 的 SHA-256 校验通过。HAP 使用其中 BusyBox、musl 解释器与发行版标记。首次创建 `/bin/sh` 符号链接遇到 `EACCES`，最终测试用同一 BusyBox 二进制的普通文件副本。HDC 对照中的完整 tar 解包另有符号链接和时间戳告警，HAP 最终测试独立准备三个文件。 [Alpine 文件目录](https://dl-cdn.alpinelinux.org/alpine/v3.22/releases/aarch64/)
- 模拟器安装与启动成功。诊断 HAP SHA-256 `0e72e1671700656f45e8c2794d9a7234e3edb7fff9b122ef242271546c31a564`。最终执行参数是 `aa start -b org.harmonypoc.prootprobe -a EntryAbility --ps probeStage proot-embedded-trace`。 诊断 HAP（本机产物 `../.build/proot-validation/proot-diagnostic-probe-unsigned.hap`） · 设备日志（本机产物 `../.build/proot-validation/probe-proot-diagnostic-device.log`）
- 初始探针 HAP SHA-256 `b2c659db1634439ee51eaae404201f86ceec35efc26c0ff54a85e50ab6437197`。 系统调用日志（本机产物 `../.build/proot-validation/probe-device.log`） · 探针源码（本机产物 `../.build/proot-validation/probe/entry/src/main/cpp/poc.c`） · HDC 对照日志（本机产物 `../.build/proot-validation/hdc-proot-guarded.log`）

附件的 Termux + proot-distro 是 Android 路径。另一个项目 proroot 当前以 Android 为目标，仅提供二进制，公开参数表没有 `--no-ptrace`。两者的 Android 用例不提供当前鸿蒙镜像上的执行证据。 [Termux](https://github.com/termux/termux-app) · [proroot](https://github.com/coderredlab/proroot)

本轮覆盖调试 Phone 模拟器中的 PRoot 路径。Linux Node.js、Claude Code、DSH 和性能未进入测试，真机未测试。若后续找到同一 Phone 模拟器允许执行的 loader 交付方式，复测以实际 Shell 输出和文件写入为准。
