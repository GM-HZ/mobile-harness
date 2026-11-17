# Inspector 与替代编辑入口

基线：Mobile Harness `be8d1f41f65e1fc8bec7c21be0f0fde8b7cdf060`，`codex/harmonyos-package-management`，开始时工作树干净。前轮三组真实压缩检查和推送已完成，属于实际进展。当前模拟器安装准确0.4.35HAP，沿用SHA-256 `555be71d17877797b50e42c1f6150a1a83898a7668ddc52670226320550ba64e`；不修改 SayAct。

目标：验证官方 Cordis 预设中的只读 Service／Event／Config／Tool 查询、精确 schema、未知方法拒绝与重启；分别验证可选诊断 Inspector，不把它与 Cordis API发现混淆。补齐 str_replace_editor 和配置开启的 apply_patch 的真实创建、替换、插入、移动、删除、预检失败、越界和只读拒绝。客户端能力依赖真实页面时明确区分已连页面、缺失页面与失败，不用伪造客户端当完整验收。

实现：优先普通包真实模型调用，适用可选 bundle／公开配置；只有复现平台错误才改产品并新构建。临时配置保存在外部原字节，回写核对；原默认值／会话保留，凭据和自建文件清理。源码依赖继续按已锁定submodule，不关闭测试来声称兼容。

验收：实际模型调用对应工具并核对结果、字节与边界；分页目录后按返回的准确entry id查询schema，静态 API目录与实时工具／Config分开证明。替代编辑和补丁先保持上游开关，只在测试预设按配置启用，保留完整standard组成；不能用改写默认Host或放宽权限使测试通过。必要时验证失败后恢复和正常恢复入口。保留实际制品、测试源码、退出码、失败和未验项，提交推送。

状态：已阅读官方组成与接口，开始普通包 Cordis 发现测试。尚未声明 Inspector 客户端或编辑功能通过。整体目标仍为全部适用DSH能力。

## 已复现的原子创建错误与适配

0.4.35 中实际 str_replace_editor create 返回 FS_PERMISSION_DENIED：fs-local 的 createIfAbsent 使用 hard-link 原子发布，鸿蒙拒绝 link。没有放宽已存在目标拒绝或改为覆盖写。检查现有已锁定 libdshpublish.so（SHA-256 `4df1a50e227048a21a1c6f68f2a12b98ba3f0c9626519e34096def7a0a340077`），反汇编 RenameNoReplace 明确为AArch64 syscall276、flags1（renameat2/RENAME_NOREPLACE），既有附件／持久化已经使用该能力。

0.4.36 通过可替换 HarmonyFileSystem 继承官方 SandboxedFileSystem，仅注入公开 FsIoInternals.linkFile 发布边界；复用已有原子no-replace原生桥，保留原暂存、sync、版本检查、锁和每次调用权限。恢复模式继续原provider，不因适配器故障丢失恢复入口。不改上游核心或新增底层编译。需验证已存在文件／确定性并发创建拒绝、完整编辑测试和受影响回归后才声明通过。

另：第一轮 Cordis 检查把超过inline上限的工具目录当完整JSON解析而失败。实际完整结果已按正式retention机制保存。测试修正为核对完整保存结果及摘要，并让真实Agent用read读取首分页；保留所有语义断言，不提高输出上限或删去完整工具目录检查。Host及真实ArkWeb五类查询和重启的修正批次已退出0，尚未等同于可选诊断Inspector Worker验收。
