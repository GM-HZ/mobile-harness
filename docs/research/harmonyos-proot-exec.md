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

## 第一版内存加载器原型（0.4.69，模拟器已验证）

`tests/smoke/fixtures/inmemory-elf-loader.py` 是最小验证：内嵌一个 aarch64 `ET_EXEC`（`write(1, ...)` + `ret`），先写入工作区 `./probe.elf`（走真实文件读取路径），然后解析 program header → `mmap(PROT_READ|WRITE, MAP_PRIVATE|MAP_ANON|MAP_FIXED, vaddr=0x400000)` → 拷贝段 → `mprotect(PROT_READ|EXEC)` → 通过 ctypes 跳转到 entry。段代码用 `svc #0` 写 stdout，再 `ret` 回到加载器。

模拟器实测输出：

```
ELF_WRITTEN_TO_DISK 544
ELF_HEADER_OK entry=0x400100 phnum=1
SEGMENT_MAPPED 0x400000 size 4096 prot 5
ENTER_ENTRY 0x400100
IN-MEMORY-ELF-OK
RETURNED_FROM_ELF (no exit_group called)
INMEM_ELF_PROBE_DONE
```

证据：[emulator-inmemory-elf-loader-0.4.69.json](../evidence/emulator-inmemory-elf-loader-0.4.69.json)。复现：`python3 tests/smoke/mate60-proot-exec.py --target <target> --probe elf-loader --output out.json`（脚本会把 loader 通过 HDC 文件通道上传到工作区，再让真实会话的 `bash` 工具执行）。

## 下一步（实现 PC 对齐的执行能力）

1. **真实静态二进制**：补 argc/argv/envp/auxv 栈、`fork`+`waitpid`（避免被加载程序 `exit_group` 带走 Host），支持静态 PIE 的 `R_AARCH64_RELATIVE` 重定位；用运行时下载的静态 busybox/fd/ripgrep 验证。
2. **native 集成**：把加载器写成签名 native helper（NAPI/子进程入口），接入 bash/subprocess provider，做到"下载静态工具直接跑"。
3. **动态 ELF**：映射签名 musl 解释器/库（signed 文件可直接 mmap PROT_EXEC），按内核语义设置 auxv 后交给解释器重定位；逐步支持动态链接工具。
4. **dlopen 扩展**：原生扩展库（Python wheel/.node）需要给 `dlopen` 做同样的内存加载 shim，难度更高，先以构建期签名为准。

## 第二版：真实静态工具（模拟器已跑通）

`tests/smoke/fixtures/inmemory-elf-runner.py` 在原型基础上补齐了真实程序运行所需的部分：

- 解析全部 PT_LOAD（按页对齐，处理非页对齐 vaddr/offset 与 BSS）；
- 构建 argc/argv/envp/auxv 启动栈（`AT_PHDR/AT_PHNUM/AT_ENTRY/AT_PAGESZ/AT_RANDOM/AT_UID...`）；
- `fork()` 子进程 + 机器码 trampoline（`mov sp,x1; br x0`）进入 ELF entry，父进程 `waitpid`，因此被加载程序的 `exit_group`/崩溃不会影响 Host；
- 支持 `MH_ELF_ARGV0` 覆盖 argv[0]（busybox 需要）。

模拟器实测（Alpine `busybox-static 1.36.1-r31` aarch64，1,115,944 字节，ET_EXEC）：

```
# 宿主上传后运行
INMEM_BUSYBOX_OK
LOADED segments=2 base=0x0 entry=0x404400
CHILD_EXIT 0

# guest 内 curl 下载 -> gzip -> tar -> loader 运行
CURL_OK
GZIP_OK
TAR_OK
-rwxr-xr-x 1 mobile-harness 20020074 1115944 ./bbx/bin/busybox.static
DOWNLOADED_INMEM_OK
CHILD_EXIT 0
ELF_DOWNLOAD_PROBE_DONE
```

即"**运行时下载静态工具 → 直接执行**"在鸿蒙沙箱内已经打通（模拟器）。证据：[emulator-inmemory-static-tool-0.4.69.json](../evidence/emulator-inmemory-static-tool-0.4.69.json)。

复现：

```sh
python3 tests/smoke/mate60-proot-exec.py --target <target>   --probe elf-download --output out.json
```

接下来的工程化：native helper 集成、静态 PIE 重定位、动态 ELF、dlopen shim、JIT/PTY 重评。

## 自建开关（上架关闭 / 自编译可开）

按发布策略把内存 ELF 运行器做成**构建期开关**：

| 构建 | 命令 | 产物 |
| --- | --- | --- |
| 默认/上架 | `HARMONY_UNSIGNED=1 ./build.sh --package` | 不包含 `/usr/bin/mh-exec`；启动时若发现旧残留会删除；`dsh-self-build.json` 为 `signedExecBypass:false` |
| 自建 | `HARMONY_UNSIGNED=1 HARMONY_SELF_BUILD=1 ./build.sh --package` | 打包 `mh-exec.py`，启动时写入 `/usr/bin/mh-exec` 并设为可执行；`signedExecBypass:true` |

GitHub Actions 的 `Build HarmonyOS HAP` 通过 `workflow_dispatch` 输入 `self_build_bypass`（默认 false）控制。

模拟器验证：默认 HAP 覆盖安装后 `mh-exec` 为 **ABSENT**；自建 HAP 安装后为 `-rwxr-xr-x`，执行 `curl → gzip → tar → mh-exec ./busybox.static echo MH_EXEC_SWITCH_OK` 输出 `MH_EXEC_SWITCH_OK`、`CHILD_EXIT 0`。证据：[emulator-exec-bypass-switch-0.4.69.json](../evidence/emulator-exec-bypass-switch-0.4.69.json)。

安全边界：该开关有意绕过平台代码签名限制，仅适用于自用/自编译 harness；应用市场分发构建保持关闭。

## 透明执行的尝试与阻塞（2026-11-20）

目标：让 `./downloaded-tool args` 直接可用，不需要显式 `mh-exec`。思路是修改 PRoot 的 guest loader（`loader/loader.c`）的 `LOAD_ACTION_MMAP_FILE`：当未签名文件的 `mmap(PROT_EXEC)` 被拒绝时，回退到匿名 RW 映射 + 拷贝 + `mprotect`。补丁保存在 `runtime/harmonyos/native/guest-loader-selfbuild.c`。

结果：**当前不可行**。用 SDK clang 重新编译 vendored loader（无论是否打补丁）并仅在自建构建中替换 `libproot_preloader.so` 后，**所有** bash 命令都失败（包括签名 `/bin/bash` 的正常执行），而默认包正常。对比发现 pinned preloader 里有 `HARMONY_PRELOAD loader file mmap failed` 等字符串，这些不在 vendored loader 源码里；pinned preloader 大小 3264 bytes，vendored 编译产物 3040 bytes——说明 pinned loader 来自**另一份打过 OHOS 补丁的 PRoot 源码树**，vendored 树并非其构建来源。

因此透明回退需要：找回/重建那份 patched PRoot 源码树并在其 loader 上打补丁；或换集成点（PATH shim / Host 命令重写 / LD_PRELOAD 式拦截）。当前已回退，保留 `mh-exec` 显式命令与构建开关。证据：[emulator-loader-fallback-attempt-0.4.69.json](../evidence/emulator-loader-fallback-attempt-0.4.69.json)。

下一步优先做**用户态工具安装器**：`mh-install <name> <url> <member>` 把下载的静态工具装到私有目录并生成 `/usr/bin/<name>` shim（`#!/bin/sh` + `exec /usr/bin/mh-exec ...`），实现"下载后按名字直接用"，不依赖 loader 改造。

## 工具安装器 mh-install（自建包，已在真机验证）

`mh-install <name> <url> [member] [argv0]` 把下载的静态工具装到 `/usr/lib/mh-tools/<name>/tool`，并生成 `/usr/bin/<name>` shim，实现"下载后按名字直接跑"。

- 机制：curl 下载 → gzip+tar 解包（`member` 指定归档内路径，如 `bin/busybox.static`）→ 写 shim；
- **shim 必须是 Python 脚本**：外壳 shim（无论 `exec` 还是子进程方式）在 PRoot loader 管理的 `/bin/sh` 里嵌套执行 python3 后，退出时会 SIGSEGV（功能输出正常但退出码 139）；改成 `#!/usr/bin/python3` 的 shim、在同一解释器内执行 mh-exec 代码后，退出码为 0；
- 真机（Mate 60，自建签名包）实测：`mh-install busybox <apk-url> bin/busybox.static busybox` → `/usr/bin/busybox`；`busybox echo MH_INSTALL_RUN_OK` / `busybox uname -m` 均 exit 0。

证据：[mate60-mh-install-0.4.69.json](../evidence/mate60-mh-install-0.4.69.json)。

## Node JIT 与 PTY/terminal 重评（真机）

- **JIT**：内置 Node 的 V8 选项显示 `--jitless` 是默认值（`default: --jitless`），即使 `env -u NODE_OPTIONS node ...` 运行，默认仍是 jitless。虽然匿名可执行内存可用，但**当前打包的 Node 是 jitless 构建/配置**，需要换 Node 构建或找到可用的关闭开关才能恢复 JIT。
- **PTY/terminal**：guest 内 `/dev/ptmx`、`/dev/pts` 都不存在，`pty.openpty()` 报 `out of pty devices`；PTY 在设备节点层就不可用，纯用户态方案无法补，terminal/系统 PTY 维持延期。

证据：[mate60-runtime-eval-0.4.69.json](../evidence/mate60-runtime-eval-0.4.69.json)。
