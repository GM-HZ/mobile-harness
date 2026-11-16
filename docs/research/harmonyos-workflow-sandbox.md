# 鸿蒙 DSH workflow 执行隔离

2026-11-17 验证了 RC.3（`38a6a5c`）的 Workflow JavaScript 可以在启用 seccomp 的独立鸿蒙 Node 进程中运行。采用独立探针 HAP，包含经过校验的发行包同款 Node 24.14.1。[鸿蒙 Node 试验记录](../evidence/emulator-workflow-node-2026-11-17.json) · [最小内核与 macOS 试验记录](../evidence/emulator-workflow-sandbox-2026-11-17.json)

| 环境 | 试验 | 实测 |
| --- | --- | --- |
| ARM64 Phone 模拟器，API 26 | 普通 HAP 的单线程子进程查询 Landlock ABI | `ENOSYS` |
| 同一模拟器 | 用 `PR_SET_NO_NEW_PRIVS` 安装 seccomp 过滤器 | 安装成功。过滤前可打开文件和创建套接字，过滤后 `openat`、`socket`、`execve` 均返回 `EPERM`，父进程收到预先建立的管道中的结果 |
| macOS，DevEco Node 24.14.1 `--jitless` | RC.3 的原始 JavaScript 包装器与上游生成的 guest 模块 | `stripTypeScriptTypes` 返回 `ERR_WEBASSEMBLY_NOT_SUPPORTED`。直接执行同一 JavaScript 时，Workflow 并行取得两个模拟子任务结果，发出进度并清理子任务 |
| ARM64 Phone 模拟器，API 26 | 鸿蒙 Node 24.14.1 `--jitless` 下执行 RC.3 Workflow | 子进程启用 seccomp 后才接收脚本。完成两个模拟子任务并清理。文件打开、读其他描述符、写 stderr 和创建套接字均返回 `EPERM` |
| 同一模拟器 | 父进程监督无限循环 fixture | 子进程进入 VM 后无返回。父进程在 1,513 ms 发送 `SIGKILL` 并回收，设定执行预算为 1,500 ms |

上游 Node PTC 会在调度前擦除 TypeScript，即使 Workflow 自带的包装器已经是 JavaScript。Workflow guest 使用 `node:vm` 提供脚本 API，隔离依赖调用侧的进程和系统权限。Node 的 VM 超时依赖额外的 libuv 循环和线程，在该过滤策略下实测无法推进。探针改由父进程负责时限，正常脚本和无限循环分别用独立子进程验证。Mate 60 本轮 HDC 离线。[Node VM 文档](https://nodejs.org/api/vm.html) · [内核 seccomp 文档](https://docs.kernel.org/userspace-api/seccomp_filter.html)

产品接入还需要沿用 RC.3 的结构化回调协议，将子任务交给实际 DSH Host 调度，绑定取消、超时、插件卸载和子任务回收。探针的执行预算覆盖整个固定脚本。产品需区分 VM 的同步执行预算与异步等待子任务的时间，安装限制失败时拒绝执行。通用 PTC 的工作区文件授权需要另行验证，因为按系统调用和文件描述符过滤无法表达工作区路径规则。

## 复现

```sh
HARMONY_INPUTS_DIR=/absolute/path/to/harmonyos-inputs tests/probes/harmonyos-workflow-sandbox/build.sh
hdc -t <loopback-target> install -r .build/stage/harmonyos-workflow-sandbox/entry/build/default/outputs/default/entry-default-unsigned.hap
hdc -t <loopback-target> shell aa start -a EntryAbility -b org.mobileharness.workflowsandbox
hdc -t <loopback-target> shell hilog -x | rg 'WorkflowSandboxProbe|WorkflowNodeProbe'
/Applications/DevEco-Studio.app/Contents/tools/node/bin/node --jitless tests/probes/harmonyos-workflow-sandbox/workflow-jitless.mjs
```
