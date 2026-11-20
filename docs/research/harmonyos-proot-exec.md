# PRoot `exec` 语义（0.4.69 真机实测）

问题：**现在的 PRoot 支持任意 `exec` 执行命令吗？**

结论：**支持"任意 shell 命令 + 已打包签名可执行文件/脚本"的 `exec`，但不支持任意新二进制文件的 `exec`。**

## 机制

当前 HAP 内的命令执行路径是：DSH Host → 原生 addon `dsh-shell`（`launch`/`launchPiped`）→ `libpoc.so` 的 `harmony_spawn_piped` → 应用进程内嵌的 PRoot（`libproot_core.so` + `libproot_preloader.so`）。

PRoot 启动时把随包签名的 native 库（`libguest_*.so`）通过 `-b` 绑定到 guest 路径（`runtime/harmonyos/native/poc.c` 的 `packaged[]` 与 `guest-tools.inc`）：

- `/bin/sh`、`/bin/bash`、`/bin/node`、`/bin/busybox`（含一批 applet：ls/cat/cp/grep/sed/find/tar/...）
- `/usr/bin/python3`（3.12）、`/usr/bin/git`、`/usr/bin/gh`、`/usr/bin/curl`、`/usr/bin/sqlite3`、`/bin/rg`
- DSH 原生依赖（sharp/vips/koffi/landlock 等）

rootfs 里的同名占位文件本身不能执行（鸿蒙代码签名策略），真正执行的是被绑定到 guest 路径的签名库；`HARMONY_PRELOAD` 加载器负责 mmap 这些签名文件。因此：

- `exec <已绑定命令>` 可用；
- 由已绑定解释器（`/bin/sh`、`/bin/bash`、`/usr/bin/python3`、`/bin/node`）运行的脚本可用；
- 把已签名文件复制到工作区再执行、或放入任意新 ELF，都会被加载器拒绝。

## 真机证据（Mate 60，0.4.69）

命令经真实会话的 `bash` 工具执行（`danger-full-access`），原始输出见 [mate60-proot-exec-0.4.69.json](../evidence/mate60-proot-exec-0.4.69.json)。

| 用例 | 结果 |
| --- | --- |
| `exec /bin/sh -c 'echo EXEC_SH_OK'` | 通过，exit 0 |
| `exec /bin/bash -c 'echo EXEC_BASH_OK'` | 通过，exit 0 |
| `exec /bin/node -e 'console.log("EXEC_NODE_OK")'` | 通过，exit 0 |
| `exec /usr/bin/python3 -c 'print("EXEC_PY_OK")'` | 通过，exit 0 |
| `exec /usr/bin/git --version` | 通过，exit 0 |
| `#!/bin/sh` 脚本 `exec ./proot-exec.sh` | 通过，exit 0 |
| `exec /bin/xxd`（未打包 applet） | exit 127，`No such file or directory` |
| 复制 `/bin/busybox` 到工作区后 `exec ./proot-bx` | exit 182，`HARMONY_PRELOAD loader file mmap failed` |
| 复制 `/bin/node` 到工作区后 `exec ./proot-node` | exit 182，同上 |
| 伪造 ELF（仅 magic）`exec ./proot-fake` | exit 126，`Exec format error` / `No error information` |

## 实践含义

- **能做的**：在 bash 工具/子进程里跑任意 shell 组合、管道、脚本；使用上面列出的命令（`git`、`gh`、`curl`、`python3`、`node`、`rg` 等）；纯 Python/Node 脚本由已绑定解释器执行。
- **不能做的**：运行运行时下载/复制进来的任意 ELF（例如从网上下载的静态二进制、`pip`/`npm` 附带的原生可执行文件、自己编译的工具）。这类二进制需要在构建期加入打包签名清单（`packaged[]`/`guest-tools.inc`）并重新打包 HAP，无法靠 PRoot 绕过鸿蒙的代码签名检查。
- 受限的 native 动态库同理受签名/绑定约束；这不是 PRoot 的 ptrace 实现问题，而是鸿蒙加载器策略。

## 复现

```sh
python3 tests/smoke/mate60-proot-exec.py --target <usb-serial> --output out.json
```

脚本会新建临时 workspace/session，提示模型调用一次 `bash` 工具执行固定探针命令，并把原始输出与退出码写入证据 JSON；不会修改 profile。

## 能不能绕过？运行时 native 代码的边界

针对"运行时复制/下载的任意 ELF"继续做了三类绕过尝试（见 [native 绕过评估证据](../evidence/mate60-native-bypass-0.4.69.json)）：

| 尝试 | 结果 |
| --- | --- |
| 复制一个已绑定的 `.so` 到工作区后 `ctypes.CDLL` | `OSError: Error loading shared library ./copied-libstdc++.so: Permission denied` |
| 直接 `dlopen` 已绑定的 guest 路径 `/usr/lib/libstdc++.so.6` | 成功（说明限制在文件/映射来源，不在 ctypes） |
| 把 `/bin/busybox` 字节写入 `memfd`，用 libc `fexecve` 执行 | 失败：`proot error: execveat() with non-AT_FDCWD fd is not currently supported`（当前 PRoot 实现不支持 execveat/memfd 执行） |
| `os.execve('/proc/self/fd/<n>')` | guest 内没有 `/proc`，直接 `FileNotFoundError` |
| 复制 `/bin/busybox` 或 `/bin/node` 到工作区后 `exec` | exit 182，`HARMONY_PRELOAD loader file mmap failed` |

据此，当前**没有可用的运行时绕过路径**；限制来自两层：PRoot 的 preload 加载器只映射随包签名的绑定文件，以及 HarmonyOS 对应用数据中可执行映射的限制（连 `dlopen` 复制出来的 `.so` 都是 `Permission denied`）。

理论上可研究的方向（均未验证，且不一定能通过内核策略）：

1. **扩展 PRoot/加载器**：实现 `execveat`/memfd 支持并让 `HARMONY_PRELOAD` 映射任意 ELF，最后仍要过内核的 W^X/签名检查；
2. **构建期打包**：把需要的工具加入签名 overlay（`packaged[]`/`guest-tools.inc`）后重新打包 HAP——这是当前 sh/node/python3/git/gh/curl/rg/sqlite3 的来源，也是唯一已验证可行的扩展方式；
3. **解释器/WASM 路径**：纯 Python（pip 25.0.1 可用）、Node JS、以及未来的 WASI 引擎可以运行"逻辑代码"，但都不能替代原生进程 `exec`。

因此执行能力不是"被砍到不能用"，而是从"任意 Linux 二进制"收敛为"**随包签名工具箱 + 解释器运行时**"：常用 Agent 命令（shell、git、gh、curl、python、node、rg、tar 等）都在；静态下载的二进制、自编译工具、带原生扩展的第三方包无法运行。

## 不用提前打包的部分：运行时获取纯语言工具

原生二进制受签名限制，但"工具"不止原生二进制。真机实测（见 [运行时工具证据](../evidence/mate60-runtime-tool-probe-0.4.69.json)）：

- guest 内自带 `python3.12` + **pip 25.0.1**，网络可达 PyPI（`https://pypi.org/simple/...` 返回 200）。
- 基础 Python 环境被标记为 externally-managed（PEP 668），`pip install --user` 会被拒绝并提示改用 venv 或 `--target`。
- 用 `python3 -m pip install --no-cache-dir --target ./pylibs pyfiglet` **实际下载安装成功**（1.8 MB），再 `PYTHONPATH=./pylibs python3 -m pyfiglet MH` 正常输出。
- `node -e` 纯 JS 运行时正常（Node 24.14.1）。

也就是说：**纯 Python 包、纯 JS 代码、bash/Python/Node 脚本都不需要重新打包 HAP**，可以在运行时从 PyPI/npm 等来源获取并运行；只有"原生可执行文件/原生扩展库"才需要构建期签名打包。带编译扩展的 Python wheel / 带预编译二进制的 npm 包预期仍会命中同样的 `dlopen Permission denied`（尚未逐个验证）。

## 工具链扩展的维护方式

新增原生工具不是手工搬整个工具链，而是声明式清单 + 重新构建：

1. `docs/guest-tools-lock.json` 锁定 Alpine aarch64 APK 的 URL 与 SHA-256；
2. `runtime/harmonyos/packaging/package-shell-tools.py` 从 APK 里取出选定 ELF（`BINS` 列表）打包成签名 `libguest_cli_*.so`、生成 `guest-tools.inc` 绑定与 `shell-tools-layer.zip` 数据层；
3. `./build.sh --package` 重新产出 signed HAP，`hdc install -r` 覆盖安装（本机实测约 36 秒）。

所以"要提前打包"的范围 = **实际需要的原生工具清单**，不是整套工具链；纯语言工具和脚本可以运行时解决。

## 关键突破：匿名可执行内存可用，可以自研内存加载器

之前判断"没有绕过"只在**文件级** exec 上成立；进一步用 Python ctypes 直接调 musl `mmap`/`mprotect`（真机）得到：

| 测试 | 结果 |
| --- | --- |
| 匿名 `mmap(PROT_READ|WRITE|EXEC)` | ✅ OK |
| 匿名 `mmap(PROT_READ|EXEC)` | ✅ OK |
| `mprotect(RW → RX)` | ✅ OK |
| 映射**签名 HAP 内**文件为可执行（`/bin/busybox`） | ✅ OK |
| 映射工作区里的**未签名**副本为可执行 | ❌ EPERM |
| 映射 `memfd` 为可执行 | ❌ EPERM |
| 手写 ARM64 机器码页（`mov x0,#42; ret`）经 CFUNCTYPE 执行 | ✅ 返回 42 |

即：平台禁止的是**未签名文件的可执行映射**，但**匿名可执行内存完全可用**。因此 signed native helper 可以实现用户态 ELF 加载器：读取任意 ELF 字节 → 匿名 RW 映射 → 重定位 → `mprotect(RX)` → 跳转执行。对**静态 ELF**（大量 Go/Rust CLI 工具都是静态构建）可以完全绕过文件签名限制；动态 ELF 需要 signed musl 解释器/库配合或更多加载器工作。Node V8 的 JIT 也依赖匿名 RWX（已确认可用），"jitless" 可能是构建选择而非平台强制。

这为"全面对齐 PC"提供了可行技术路线：**in-memory loader + 静态工具运行时下载**，而不必把所有原生工具都打进 HAP。

> 注意：这是有意绕过平台代码签名边界的做法，适合自用开发者 harness，不适合应用市场分发构建。
