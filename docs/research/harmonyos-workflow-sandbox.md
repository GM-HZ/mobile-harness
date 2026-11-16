# 鸿蒙 DSH workflow 执行隔离

2026-11-17 验证了 RC.3（`38a6a5c`）的 Workflow JavaScript 可以在启用 seccomp 的独立鸿蒙 Node 进程中运行。采用独立探针 HAP，包含经过校验的发行包同款 Node 24.14.1。[鸿蒙 Node 试验记录](../evidence/emulator-workflow-node-2026-11-17.json) · [最小内核与 macOS 试验记录](../evidence/emulator-workflow-sandbox-2026-11-17.json)

| 环境 | 试验 | 实测 |
| --- | --- | --- |
| ARM64 Phone 模拟器，API 26 | 普通 HAP 的单线程子进程查询 Landlock ABI | `ENOSYS` |
| 同一模拟器 | 用 `PR_SET_NO_NEW_PRIVS` 安装 seccomp 过滤器 | 安装成功。过滤前可打开文件和创建套接字，过滤后 `openat`、`socket`、`execve` 均返回 `EPERM`，父进程收到预先建立的管道中的结果 |
| macOS，DevEco Node 24.14.1 `--jitless` | RC.3 的原始 JavaScript 包装器与上游生成的 guest 模块 | `stripTypeScriptTypes` 返回 `ERR_WEBASSEMBLY_NOT_SUPPORTED`。直接执行同一 JavaScript 时，Workflow 并行取得两个模拟子任务结果，发出进度并清理子任务 |
| ARM64 Phone 模拟器，API 26 | 鸿蒙 Node 24.14.1 `--jitless` 下执行 RC.3 Workflow | 子进程启用 seccomp 后才接收脚本。完成两个模拟子任务并清理。文件打开、读其他描述符、写 stderr 和创建套接字均返回 `EPERM` |
| 同一模拟器 | 父进程监督无限循环 fixture | 子进程进入 VM 后无返回。父进程在 1,513 ms 发送 `SIGKILL` 并回收，设定执行预算为 1,500 ms |
| 同一模拟器 | 原生进程管理器同时启动两个受限 Node worker | Unix 套接字经 `SCM_RIGHTS` 传给调用方。一个 worker 完成试验脚本，另一个无限循环 worker 在 1,514–1,516 ms 被终止。三次均回收两个 worker。[进程管理器试验记录](../evidence/emulator-workflow-broker-2026-11-17.json) |

上游 Node PTC 会在调度前擦除 TypeScript，即使 Workflow 自带的包装器已经是 JavaScript。Workflow guest 使用 `node:vm` 提供脚本 API，隔离依赖调用侧的进程和系统权限。Node 的 VM 超时依赖额外的 libuv 循环和线程，在该过滤策略下实测无法推进。探针改由父进程负责时限，正常脚本和无限循环分别用独立子进程验证。Mate 60 本轮 HDC 离线。[Node VM 文档](https://nodejs.org/api/vm.html) · [内核 seccomp 文档](https://docs.kernel.org/userspace-api/seccomp_filter.html)

## 0.4.29 正式包接入

DSH Host 在加载 Node 之前启动单线程进程管理器，按次启动 Workflow worker。已锁定的 RC.3 Workflow 模块仍负责验证脚本、分派实际子任务、记录进度和处理取消。鸿蒙适配只替换运行 Workflow guest 的部分。正式包沿用原有的通用 PTC 路径。

Worker 在加载受信任模块后安装 seccomp，随后通过一个 Unix 套接字交换 Workflow 回调。常规 libuv 套接字方案在首个 Host 回调后停滞，最终 worker 采用同步套接字轮询，宿主异步处理子任务，worker 在收到回调后继续推进 Node 的 Promise 队列。此路径依赖已锁定 Node 的 `process._tickCallback`，升级 Node 需要重跑完整 Workflow 验收。

同步 VM 切片的时限由宿主计时，开始等待子任务时解除这个计时器。用户取消或同步超时由进程管理器结束 worker 并确认回收。限制安装失败时不会向 worker 传送脚本或会话数据。安全模式关闭 Workflow worker。通用 PTC 的工作区文件授权仍需独立实现。 [正式包验收记录](../evidence/emulator-workflow-0.4.29.json)

## 复现

```sh
HARMONY_INPUTS_DIR=/absolute/path/to/harmonyos-inputs tests/probes/harmonyos-workflow-sandbox/build.sh
hdc -t <loopback-target> install -r .build/stage/harmonyos-workflow-sandbox/entry/build/default/outputs/default/entry-default-unsigned.hap
hdc -t <loopback-target> shell aa start -a EntryAbility -b org.mobileharness.workflowsandbox
hdc -t <loopback-target> shell hilog -x | rg 'WorkflowSandboxProbe|WorkflowNodeProbe'
/Applications/DevEco-Studio.app/Contents/tools/node/bin/node --jitless tests/probes/harmonyos-workflow-sandbox/workflow-jitless.mjs
```
