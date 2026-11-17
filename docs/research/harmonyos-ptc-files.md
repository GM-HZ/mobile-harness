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

探针只测试普通文件的打开、内容读写和已有线程的过滤传播。正式通用 PTC 仍需映射 RC.3 的工作区及附加可写根，验证 Node 主线程和 libuv 工作线程发出的请求，并覆盖目录操作、取消、超时和资源回收。两次通过记录来自同一探针制品，Mate 60 离线。 [Node 解析探针](harmonyos-ptc-typescript.md)

## 复现

```sh
HARMONY_INPUTS_DIR=/absolute/path/to/harmonyos-inputs tests/probes/harmonyos-workflow-sandbox/build.sh
hdc -t <loopback-target> install -r .build/stage/harmonyos-workflow-sandbox/entry/build/default/outputs/default/entry-default-unsigned.hap
hdc -t <loopback-target> shell aa start -a EntryAbility -b org.mobileharness.workflowsandbox
hdc -t <loopback-target> shell hilog -x | rg PtcFilesProbe
```
