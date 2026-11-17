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

## 正式 Host 的实验接入

构建时设置 `HARMONY_PTC_AMARO_DIR` 可在普通应用的 DSH Host 中启用上游 `ProgramWorker`。鸿蒙适配器提供 TypeScript 擦除与进程启动。独立监督进程持有工作区目录描述符，并为 worker 处理文件请求。0.4.30 及以前的默认构建与恢复模式禁用该入口。0.4.31 将相同的解析器生成与摘要校验接入普通构建，默认提供 PTC；恢复模式继续禁用。

API 26 Phone 模拟器通过真实模型触发会话内的 `run_code`。实测 TypeScript、工作区读取、独占创建、覆盖、追加和嵌套 DSH 文件工具。工作区外读写均被拒绝，只读会话可读取夹具，其创建、覆盖、追加请求均被拒绝。宿主回读核对了文件内容。取消默认模式的会话后，宿主确认回收对应 worker。覆盖先打开目标并验证描述符对应单链接普通文件，再截断文件。模拟器的 HDC 应用上下文拒绝创建符号链接和硬链接，本轮未验证通过这两类链接发起的文件操作。 [正式 Host 实测](../evidence/emulator-ptc-host-2026-11-17.json) · [扩展工作区操作实测](../evidence/emulator-ptc-access-2026-11-17.json)

RC.3 的 REPL 和启用持久化的 Script 均在同一会话跨轮保留变量，另一会话的独立进程无法读取这些变量。未启用持久化的 Script 第二轮用新进程，变量随首轮结束释放。三种配置都通过官方 `ptc-runtime` profile 节点选择。 [构建与回归](../development.md#通用-ptc-实验回归)

两种持久模式都通过真实会话的取消回归。程序在撤销等待期内结束时，用户取消后的下一轮仍能读取原变量。程序进入同步死循环时，取消后约 3.1 秒完成回收，下一轮使用新进程，变量已清空。 [持久模式取消实测](../evidence/emulator-ptc-retained-cancel-2026-11-17.json)

工作区写模式还验证了 Node 的 `mkdir`、`rename`、`unlink` 和 `rmdir`。监督进程复制路径，以工作区根为界打开父目录，重命名的两个父目录分别校验。实际操作使用父目录描述符和单一文件名。模拟器通过跨子目录重命名、空目录移除和非空目录拒绝，也验证跨出、跨入工作区和移除根目录均被拒绝。只读会话中同样的修改请求均被拒绝。 [目录操作实测](../evidence/emulator-ptc-directory-2026-11-17.json)

Node 的 `stat` 和 `lstat` 通过监督进程读取已授权描述符的元数据。工作区写模式验证了文件类型和大小、缺失路径的 `ENOENT`、递归 `mkdir`、`readdir` 和 `rm`。临时目录的创建和删除由宿主回读核对，工作区外元数据、递归列目录和递归删除均被拦截。只读会话能查询元数据，写操作仍被拒绝。 [元数据与递归操作实测](../evidence/emulator-ptc-metadata-2026-11-17.json)

PTC 可以在工作区子目录启动，也可通过 `process.chdir` 切换到同一工作区的其他目录。监督进程校验目标目录并将目录描述符交给 worker，由 worker 执行 `fchdir`。之后的相对文件请求按当前目录解析，工作区根继续来自会话的文件策略。实际会话先调用 DSH 的 `working_directory`，下一轮程序在所选子目录读取了夹具，向工作区外切换目录被拒绝。 [工作目录实测](../evidence/emulator-ptc-cwd-2026-11-17.json)

真实会话通过 `workspace/archiveSession` 归档再恢复后，两种持久模式均继续读取原变量，宿主确认原 worker 保留。这与上游归档语义一致。真正的 Agent 销毁由创建者持有的 `AgentHandle.dispose` 管理，归档 API 保留该 Agent。 [归档恢复实测](../evidence/emulator-ptc-archive-2026-11-18.json)

标准 bundle 测试插件通过上游 Agent SDK 持有独立 `AgentHandle`。在 REPL 和持久化 Script 两种模式中，真实模型先创建持久 PTC 状态，再由另一个会话调用插件销毁该 Agent。空闲进程约 40 毫秒回收，同步死循环约 3 秒回收，Agent 和实时会话均从注册表移除。随后通过普通 Session API 从原记录恢复，两种情况都启动了新 worker，旧变量已清空。测试退出时恢复原 profile、锁文件和启动模式。 [Agent 销毁与恢复实测](../evidence/emulator-ptc-lifecycle-2026-11-18.json)

文件代理还接收 DSH `additionalWritableRoots`。每个进程启动时校验并打开主工作区及最多 16 个附加物理目录。路径匹配按完整目录边界选择最长授权根，文件操作继续以预打开的描述符解析。模拟器实际会话验证了三个附加目录中的读写、跨授权根重命名、重叠根、递归文件操作和工作目录切换。同名前缀的未授权相邻目录被拒绝。只读模式忽略附加可写授权，并验证附加目录中没有新文件。 [附加目录实测](../evidence/emulator-ptc-roots-2026-11-18.json)

相对文件路径也可跨越两个授权根。代理根据规范化后的目标选择授权根，同时通过内核校验原始父路径，再从预打开的授权目录解析目标。真实会话验证了跨根的相对读取、写入、元数据查询和重命名。`missing/../file` 返回 `ENOENT`，`file/../file` 和 `file/.` 返回 `ENOTDIR`，未授权相邻目录仍被拒绝。模拟器未提供可创建符号链接的夹具，本轮未验证符号链接操作。 [相对路径实测](../evidence/emulator-ptc-relative-2026-11-18.json) · [内核路径解析说明](https://docs.kernel.org/filesystems/path-lookup.html)

宿主并发移动父目录仍需验证。Mate 60 在本轮离线。

## 单次扩大授权

鸿蒙适配器接收上游审批流程批准的 `danger-full-access` 文件策略。该调用以当前 App 文件系统命名空间的根目录为文件授权根，并允许跨越 App 数据绑定挂载。普通工作区根继续使用原有的禁止跨挂载解析规则。执行后端仍报告 `partial`，Node 系统调用使用同一文件代理的支持范围。

真实模型会话通过既有 Remote Event 流请求审批。模拟器验证了只读到工作区写、工作区写到完整文件授权两级变化。审批前没有新 worker 启动，拒绝或取消均不执行程序，批准后只执行一次并回收 worker，后续调用恢复原权限。REPL 的原变量在批准前后均可读取，单次扩大授权使用独立程序环境。普通文件操作及附加目录回归也通过。 [单次审批实测](../evidence/emulator-ptc-approval-2026-11-18.json)

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
