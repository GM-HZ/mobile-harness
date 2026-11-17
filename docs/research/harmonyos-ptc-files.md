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

文件代理兼容 libc 为 Node 打开请求追加的 `O_LARGEFILE`。代理分别轮询通知通道和结果通道，避免假设 Node 只会发出与显式 API 次数相等的请求。 [Node 解析探针](harmonyos-ptc-typescript.md)

## RC.3 执行协议

探针校验 RC.3 发布包内 `dsh-ptc-runtime-node/lib/process.js` 的版本与摘要，只替换最后的进程入口。上游 evaluator、控制通道协议、日志和绑定编解码均按原样运行。固定 Host 夹具通过独立 Unix 套接字发送程序并回复工具请求。模拟器两次验证了工作区异步读取、日志、工具结果 `42`、等待工具期间的 `revoke`、以及进入死循环后强制终止并回收 worker。 [协议实测](../evidence/emulator-ptc-protocol-2026-11-17.json)

正式通用 PTC 仍需由实际 DSH Host 启动 worker，将会话的工作区和附加可写根传给文件代理。目录修改、持久执行模式和真实模型入口仍待验证，Mate 60 离线。

## 复现

```sh
HARMONY_INPUTS_DIR=/absolute/path/to/harmonyos-inputs tests/probes/harmonyos-workflow-sandbox/build.sh
hdc -t <loopback-target> install -r .build/stage/harmonyos-workflow-sandbox/entry/build/default/outputs/default/entry-default-unsigned.hap
hdc -t <loopback-target> shell aa start -a EntryAbility -b org.mobileharness.workflowsandbox
hdc -t <loopback-target> shell hilog -x | rg PtcFilesProbe
```

按 TypeScript 探针文档准备 `HARMONY_AMARO_PROBE_DIR`，重建后由 `PtcNodeFiles` 日志验证 TypeScript 与 Node 文件操作的组合。 [生成步骤](harmonyos-ptc-typescript.md#复现)

执行正常构建的 `--prepare-only` 后，从暂存的 DSH layer 提取 RC.3 bootstrap。构建探针时加上 `HARMONY_PTC_BOOTSTRAP`，检查 `PtcWireProbe` 日志。

```sh
mkdir -p .build/ptc-wire
unzip -p .build/stage/harmonyos/entry/src/main/resources/rawfile/dsh-layer.zip \
  dsh/node_modules/@deepseek-ai/dsh-ptc-runtime-node/lib/process.js > .build/ptc-wire/process.js
HARMONY_PTC_BOOTSTRAP="$PWD/.build/ptc-wire/process.js" \
  HARMONY_INPUTS_DIR=/absolute/path/to/harmonyos-inputs \
  tests/probes/harmonyos-workflow-sandbox/build.sh
```
