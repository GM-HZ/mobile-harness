# 鸿蒙 DSH workflow 执行隔离

2026-11-17 在 RC.3（`38a6a5c`）上分开验证了鸿蒙内核限制与上游 Workflow JavaScript。两项试验都没有修改发行包。制品校验值、目标、退出码和日志结果见[模拟器与 macOS 试验记录](../evidence/emulator-workflow-sandbox-2026-11-17.json)。

| 环境 | 试验 | 实测 |
| --- | --- | --- |
| ARM64 Phone 模拟器，API 26 | 普通 HAP 的单线程子进程查询 Landlock ABI | `ENOSYS` |
| 同一模拟器 | 用 `PR_SET_NO_NEW_PRIVS` 安装 seccomp 过滤器 | 安装成功。过滤前可打开文件和创建套接字，过滤后 `openat`、`socket`、`execve` 均返回 `EPERM`，父进程收到预先建立的管道中的结果 |
| macOS，DevEco Node 24.14.1 `--jitless` | RC.3 的原始 JavaScript 包装器与上游生成的 guest 模块 | `stripTypeScriptTypes` 返回 `ERR_WEBASSEMBLY_NOT_SUPPORTED`。直接执行同一 JavaScript 时，Workflow 并行取得两个模拟子任务结果，发出进度并清理子任务 |

上游 Node PTC 会在调度前擦除 TypeScript，即使 Workflow 自带的包装器已经是 JavaScript。Workflow guest 使用 `node:vm` 提供脚本 API，隔离依赖调用侧的进程和系统权限。另一项试验只证明过滤器可用于这个进程，尚未验证完整 Node 进程或跨线程同步。Mate 60 本轮 HDC 离线。[Node VM 文档](https://nodejs.org/api/vm.html) · [内核 seccomp 文档](https://docs.kernel.org/userspace-api/seccomp_filter.html)

下一步在独立鸿蒙 Node 子进程内预加载受信任的运行时，关闭多余文件描述符，安装限制后通过管道接受脚本和交换结构化结果。实际执行需要验证超时、取消、文件与网络访问拒绝及插件卸载后的清理，安装限制失败时拒绝执行。通用 PTC 的工作区文件授权需要另行验证，因为按系统调用和文件描述符过滤无法表达工作区路径规则。

## 复现

```sh
tests/probes/harmonyos-workflow-sandbox/build.sh
hdc -t <loopback-target> install -r .build/stage/harmonyos-workflow-sandbox/entry/build/default/outputs/default/entry-default-unsigned.hap
hdc -t <loopback-target> shell aa start -a EntryAbility -b org.mobileharness.workflowsandbox
hdc -t <loopback-target> shell hilog -x | rg WorkflowSandboxProbe
/Applications/DevEco-Studio.app/Contents/tools/node/bin/node --jitless tests/probes/harmonyos-workflow-sandbox/workflow-jitless.mjs
```
