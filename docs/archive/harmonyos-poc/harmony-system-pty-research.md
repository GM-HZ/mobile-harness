# HarmonyOS 手机系统 PTY 调研

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

2026-11-07。目标是在零售版 Mate 60 上，由鸿蒙 HAP 为本机 Shell 或 DSH 提供真实的系统 PTY。范围包括直接分配、系统服务代分配，以及能实现相同终端交互的用户态方案。

## 真机与模拟器对照

| 执行环境 | 观察结果 |
| --- | --- |
| Mate 60 BRA-AL00，OpenHarmony 7.0.0.111，API 26，调试 HAP，UID 20020306 | 此前的签名探针中，`openpty()` 和直接打开 `/dev/ptmx` 都返回 `EACCES`。两轮管道交互正常，Shell 报告作业控制关闭。 |
| Phone 模拟器，OpenHarmony 7.0.0.105，API 26，调试 HAP | 此前同样在分配 PTY 时返回 `EACCES`。 |
| Mate 60，USB HDC 3.2.0f，非交互 `hdc shell <command>` | `sh` 域、UID 2000。读取打开 `/dev/ptmx` 被拒绝，`/dev/pts/ptmx` 返回路径不存在。 |
| 同机 `hdc shell` 交互会话 | `sh` 域、UID 2000。`tty` 和标准输入的 FD 都指向设备侧 `/dev/pts/0`。`sleep 10` 可被 Ctrl+C 提前打断，随后在 2.51 秒观测窗口内收到下一条命令输出。 |
| 同机 `hdc shell -b <调试包名>` | 工作目录变为调试包映射目录。UID、`sh` 域和真实 PTY 均与普通 HDC 交互会话一致。 |

本轮 HDC 对照日志（本机产物 `mate60-system-pty-hdc.log`） · [此前真机 HAP 记录](proot-mate60-validation.md#签名包内交付-elf-的实测结果) · [此前模拟器 HAP 记录](proot-full-validation.md#模拟器实测)

华为 NDK 文档把 PTY 接口和 `dev_ptmx`、`devpts`、`tty_device` 策略关联。OpenHarmony 的 HDC 源码由设备侧 daemon 先打开 `/dev/ptmx`，再启动 Shell，将 PTY 从端接到标准输入、输出和错误。真机进程列表也显示 daemon 运行于 `u:r:hdcd:s0`。HDC 路径证明真机系统支持 PTY。未取得这台零售设备实际命中的策略规则或对应 AVC 记录。 [华为 NDK 文档](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/guidance-on-ndk-libc-interfaces-affected-by-permissions/) · [HDC 源码](https://github.com/openharmony/developtools_hdc/blob/master/src/daemon/shell.cpp#L305-L373) · [HDC 设备路径](https://github.com/openharmony/developtools_hdc/blob/master/src/daemon/shell.h#L49)

## 可复用实现与适用范围

- **QTerminal OHOS**。仓库提交 `1342444d525418989a2fc9a5b7f77b9eeb6213c1` 宣称 `posix_openpt/forkpty/termios` 真机通过。README 未给出通过的具体机型、应用运行域及签名配置。标准 Qt 后端可用于对照，尚无 Mate 60 复现。 [QTerminal 仓库](https://gitcode.com/ohos-qt/qterminal)
- **Electerm 的 node-pty 补丁**。检查了发布包内的源码和说明。补丁依然依赖 `forkpty()` 成功，主要处理库链接、Shell 路径、拿到 PTY 后的读写，无法处理分配阶段的拒绝。项目当前主线将 `node-pty` 作为不需要的外部依赖处理。 [补丁发布](https://github.com/electerm/electerm-harmony/releases/tag/node-pty-ohos-v1) · [当前打包源码](https://github.com/electerm/electerm-harmony/blob/main/scripts/prepare-web.sh)
- **HiSH 和 iSH**。HiSH 的 PTY 来自其 Linux 客户机，iSH 在用户态实现 TTY。若沿现有 PRoot 在用户态复现，至少要处理终端属性、原始模式、窗口尺寸和信号、前台进程组以及跨 fork/exec 的 FD 行为。当前仅有管道交互实测。 [HiSH 实现](https://github.com/harmoninux/HiSH) · [iSH TTY 源码](https://github.com/ish-app/ish/blob/master/fs/tty.c)

## 结论与验收条件

普通 HAP 直接分配系统 PTY 在所测手机和模拟器上均失败。目前未查到零售鸿蒙手机向普通 HAP 提供 PTY 的公开权限或服务接口。若平台方能为目标机型提供授权，产品路径可以是授权应用直接分配，或由受信系统服务分配并提供经过鉴权的会话接口。跨域传 FD 还需单测 FD 使用权限、读写及 `ioctl`，也可以由系统服务持有 PTY 并代理终端流。现有 HDC 路径可作为真机调试和行为对照。

后续原生验证的第一个门槛是从实际 HAP 进程中拿到一对可读写的 PTY FD，记录 UID、域和分配方式。第二个门槛是 Shell 标准输入 `isatty(0)=1`、`/dev/tty` 可用、前台命令能被 Ctrl+C 中断、改窗大小能触发 `SIGWINCH`，最后验证 `vim` 和作业控制。HDC 本轮已验证 TTY 和 Ctrl+C，resize、全屏程序和系统服务向 HAP 授权仍未验证。
