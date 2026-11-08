# Phone Shell 与 DevEco 执行路径详细调研规格

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

- 用户目标：解释 DevEco 为何能执行终端/调试命令，查找 Mate 60 上 DSHM Shell 失败的可落地突破路径。用户原话“那 devecho 是怎么做的”本轮按 DevEco Studio 理解，同时核对 macOS 与鸿蒙 PC 两类。
- 代码基线：独立的鸿蒙 PoC 工程。
- 已有实测基线：Mate 60 API 26；DSHM 1.1.0 重签 HAP SHA c3ce7ce834ac5708c3346dd4d403b3d4f223839bdeaddd1d7a90d259b69a9755，Node 24.2.0；busybox EACCES、ash/bash/rg denied、sandbox-dlopen false、forkpty failed。当前新版 Node 24.14.1 的 Phone 模拟器进程内测试通过部分 API，真机尚未测试该运行时。
- 非目标：本轮不改系统安全策略、不 root、不启用 Docker/完整 Linux/QEMU/PRoot，不将开发机/HDC 代执行冒充离线手机原生能力；不把上游注释或第三方示例当命令授权。
- 调研验收：一级证据为当前系统/SDK文档与精确源码；二级为真机应用身份实测；明确区分 app/HDC/PC 身份。分别判断路径配置、syscall/PTY、ELF签名/加载、受限ACL与设备档位。对每个候选路径给可解决能力、剩余限制、实测状态及下一条实验。
- 验证计划：读取当前 SDK API 26 与官方文档、DevEco 本机终端/hdc 组件；必要时在独立 PoC 增加不会修改用户数据的 stat/access/进程最小矩阵，HDC 仅为对照，不将模拟器结论外推 Phone。若需要切换手机前台，先完成静态调研后统一一次启动并恢复 DSHM。
- 状态：本轮详细调研完成；普通应用进程边界矩阵已在 Mate 60 实测。无 Shell 工具插件、本机 HDC 自连等后续实现未完成，不计为本轮已交付。
