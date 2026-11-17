# 鸿蒙通用 PTC 文件授权探针

API 26 ARM64 Phone 模拟器支持 seccomp 用户态通知和 `openat2`。Landlock 返回 `ENOSYS`。独立 HAP 测试了宿主为已经受限的子进程解析和打开指定工作区文件，再把授予的文件描述符交给子进程。所有数据是 HAP 在自身应用目录创建并清理的临时夹具。 [设备证据](../evidence/emulator-ptc-files-2026-11-17.json)

| 测试 | 只读 | 工作区写 |
| --- | --- | --- |
| 读取工作区内夹具 | 读取内容匹配 | 读取内容匹配 |
| 在工作区创建文件 | `EACCES`，宿主确认文件未创建 | 创建并写入，宿主回读匹配 |
| 相对路径指向工作区外 | `EXDEV` | `EXDEV` |
| 绝对路径指向工作区外 | `EACCES` | `EACCES` |
| worker 直接调用 `openat2` | `EPERM` | `EPERM`，过滤前已存在的线程同样被拒绝 |

宿主复制一次受限进程请求的路径，只操作该副本。解析以预打开的工作区目录为根，使用 `RESOLVE_BENEATH` 等标志。原始 `openat` 请求只收到已授权描述符或错误。内核实测拒绝原子 `ADDFD_FLAG_SEND`，而 `ADDFD` 后单独回应成功。流程出现协议错误时，探针关闭通知通道并回收 worker。 [seccomp 内核文档](https://docs.kernel.org/userspace-api/seccomp_filter.html) · [openat2 手册](https://man7.org/linux/man-pages/man2/openat2.2.html)

## Node 24.14.1 文件请求

同一文件代理接入了独立鸿蒙 Node worker。Node 启动 libuv 工作线程后安装 seccomp，验证 `fs.readFileSync`、由 TypeScript 擦除后运行的 `fs.promises.readFile`、`fs.promises.readdir` 和 `fs.promises.writeFile`。两个模式中各有四个请求来自 libuv 线程。宿主确认只读模式未落盘，工作区写模式的文件内容与夹具一致。相对越界读取和直接 `openat2` 均被拒绝。 [Node 文件实测](../evidence/emulator-ptc-node-files-2026-11-17.json)

文件代理兼容 libc 为 Node 打开请求追加的 `O_LARGEFILE`。代理分别轮询通知通道和结果通道，避免假设 Node 只会发出与显式 API 次数相等的请求。正式通用 PTC 仍需接上 DSH 的执行协议，映射工作区及附加可写根，支持目录创建和改名等操作，并覆盖取消、超时和资源回收。Mate 60 离线。 [Node 解析探针](harmonyos-ptc-typescript.md)

## 复现

```sh
HARMONY_INPUTS_DIR=/absolute/path/to/harmonyos-inputs tests/probes/harmonyos-workflow-sandbox/build.sh
hdc -t <loopback-target> install -r .build/stage/harmonyos-workflow-sandbox/entry/build/default/outputs/default/entry-default-unsigned.hap
hdc -t <loopback-target> shell aa start -a EntryAbility -b org.mobileharness.workflowsandbox
hdc -t <loopback-target> shell hilog -x | rg PtcFilesProbe
```

按 TypeScript 探针文档准备 `HARMONY_AMARO_PROBE_DIR`，重建后由 `PtcNodeFiles` 日志验证 TypeScript 与 Node 文件操作的组合。 [生成步骤](harmonyos-ptc-typescript.md#复现)
