# 鸿蒙 Host 的通用子进程

0.4.34 的平台适配。DSH 固定 RC.4，主 Host 仍在鸿蒙原生 Node 中，命令仍由 Alpine／PRoot 执行。没有增加第二套 rootfs，也没有修改 DSH 或 PRoot 子模块。

## 服务与路径

加载自己的 `HarmonySubprocessRuntime`，通过正常 patch 禁用旧 `subprocess` provider、插入新 provider。继承上游公开的 `LocalSubprocessRuntime`，用它公开的 `internals.spawn` 扩展点连接原生桥，保留输出收集、尾部限额、完整落盘、环境脱敏、取消和销毁。该 hook 属于固定版本的公开测试接口，不承诺未来任意版本兼容。

| 调用 | 路径与边界 |
| --- | --- |
| 工作树及后续语言服务器 | Host 的原生绝对目录和文件 URL；cwd 限于默认工作区；字面 argv 进入独立管道，额外控制 fd 明确拒绝 |
| 原有 Bash／搜索／MCP | 保留 `/workspace-native` 的原有视图与有界搜索检查；额外提供原生目录别名，能读取新工作树的 Git 控制路径 |
| 权限 | 上游工作树继续先执行 session policy 的 sandbox confinement；无内核后端的默认模式继续拒绝。独立测试通过真实 `/permission danger-full-access` 显式改变自己的会话，未修改部署默认值 |

新执行视图以 App 内 `dsh-subprocess-root` 空目录为 PRoot 根，通过绑定复用现有 Alpine 文件。工作区只有原生绝对路径别名，避免 Git 反向翻译回 `/workspace-native`；Bash 和 MCP 保持旧启动模式。不复制系统、不迁移工作区。安全模式跳过该目录的准备，也不启用新 provider。

可执行文件在 Guest 中查询。鸿蒙签名库对当前 UID 的 `X_OK` 可能返回拒绝，但固定加载器仍能运行包内签名映射；因此构建从同一份 C 加载表生成精确程序路径清单，只对该清单采用签名执行规则，其他文件仍要求执行权限。原生启动变量从子进程的 ambient 环境移除，显式保留字段继续拒绝；凭据形状和 DSH 身份的脱敏复用上游逻辑。

## 已复现的问题

1. 0.4.33 官方 `create_worktree` 报 `command "git" was not found on PATH`。
2. patch 的 `name` 是身份校验，直接改 name 不会替换 provider；改为 disable＋insert。
3. 首次适配误读 collected stdout 接口；改读 `handle.collected.stdout`。
4. 签名 Git 的 POSIX 执行权限检查不通过；采用由加载表生成的精确清单。
5. 仅在原 rootfs 内增加 self-binding 不能修复 Git 的控制路径：PRoot 源码明确跳过位于 rootfs 内的反向绑定，`.git` 仍写 `/workspace-native/...`。最终使用独立空目录作为根。
6. 原生 `symlink` 被应用沙箱拒绝。空根改为 PRoot 目录绑定，保留已有数据位置。
7. 新工作树记录原生 Git 路径后，旧 Bash 看不到它；旧视图也添加原生别名，同时保留原 cwd 约定。

## 验收与限制

测试通过标准临时 bundle 调用真正 provider、真实 Node/Git；使用真实模型调用官方工作树工具。测试记录 stdout 管道、字面特殊字符、stdin EOF、真实嵌套 Node、环境删除与显式覆盖、非零退出、输出尾部与完整 spill、运行中取消和 Context 销毁。正式结果与准确制品将在验收后写入证据。

PRoot 收到进程组 TERM 后可能回收 tracee 并返回退出码1，不能伪称直接命令收到某个 POSIX signal。验收要求真实运行标记、非成功退出事实、`waitForExit`、所有新 helper 回收与耗时，同时保留实际 outcome。最初要求固定 signal 的测试失败保留，修正原因与差异记录在证据。

进程范围沿用 Local provider 的 fallback 语义，不宣称能追踪主动逃离进程组的任意后代。没有新增内核沙箱、系统 PTY、后台保活保证或完整 `/proc`。本次是 LSP 的执行基础，尚不等于已安装或验收 LSP。
