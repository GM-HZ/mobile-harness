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
