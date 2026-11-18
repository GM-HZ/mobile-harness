# 鸿蒙文件原子创建与可选编辑入口

0.4.36 修复了官方 fs-local 的 createIfAbsent 发布步骤：上游先写完并同步私有暂存文件，再用硬链接避免覆盖已有目标；HarmonyOS 返回 EACCES。此前覆盖式 write 能用，不代表独占创建也能用。

实现放在 `packages/dsh-host/dsh-harmony-fs.mjs`，继承官方 SandboxedFileSystem，只替换公开的 `internals.linkFile` 发布边界。保留版本观察、目录和文件策略、锁、完整暂存与 sync、提交错误分类及清理。正常 profile 使用替换 provider；恢复 profile 保留原 provider，避免新适配器加载故障夺走恢复入口。启动器资源复制清单同步包含该模块。

发布复用已经随包的 libdshpublish.so，反汇编确认调用 AArch64 renameat2／RENAME_NOREPLACE。没有使用“先检查再覆盖”、stat 后 rename 或非原子复制。原输入的未剥离 SHA-256 为 `4df1a50e227048a21a1c6f68f2a12b98ba3f0c9626519e34096def7a0a340077`；HAP 中已剥离的5280字节 SHA-256 为 `c57895c315e4cef12b3bccd290db81a1b3aef273b1a4c5a3939a3e02571d3a2a`，与0.4.35完全相同。这两个摘要对应不同制品形态，不应直接比较。

模拟器在真正挂载的 ctx.fs 上验证：创建成功；已有目标拒绝；在真实暂存完成后插入竞争创建者，发布必须拒绝并保留竞争者字节；真实暂存后取消，不产生目标；成功、竞争和取消均无私有暂存残留。没有用独立测试 FileSystem 代替产品 provider。

真实模型另验证官方 str_replace_editor 的创建、范围查看、精确替换、歧义拒绝、插入、删除、越界和只读拒绝。临时开启的 apply_patch 验证多文件创建、移动与删除、预检失败零修改，以及提交阶段权限失败时准确报告先前已提交文件，停止后续文件；不宣称多文件事务回滚。中文、emoji 和换行按精确字节核对。

这些工具继续遵循上游默认开关：standard 的默认 fs 工具不变，替代编辑器和 apply_patch 由正式配置选择，测试结束移除临时配置。工具文件策略不等于操作系统内核隔离。

[准确制品、命令与失败](../evidence/emulator-inspection-editing-0.4.36.json) · [能力矩阵](../dsh-capabilities.md)
