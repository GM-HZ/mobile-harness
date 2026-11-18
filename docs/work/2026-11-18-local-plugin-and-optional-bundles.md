# 鸿蒙本地插件与可选 bundle 回归

基线为 0.4.46、DSH RC.5。把本地 Creator 安装修复、Auto review、LiveShare 和已随包的 Forge 纳入同一轮构建与验收。

Creator 按绝对目录安装，pnpm 尝试创建符号链接并被系统拒绝。0.4.46 复现同一类目录用 file: 成功复制。适配仅针对 pnpm add 的裸绝对目录。验收包括真实 Creator 生成、安装、页面控件、撤销与从保留副本恢复，以及原有安装兼容性。

Auto review 和 LiveShare 使用锁定的上游 bundle，默认关闭。Auto review 验收当前会话选择、允许、拒绝、故障、取消、重启和关闭行为，默认工作区权限和普通审批沿用当前配置。LiveShare 使用独立合成会话，验收启停、连接及访问撤销，避免共享用户现有会话。Forge 验收现有工作树接口与 ArkWeb 呈现，真实外部的写入和合并使用明确授权。

语音并行验证两项依赖。ArkWeb 需要本机录音授权与请求来源校验。SenseVoice 上游识别器拒绝 OpenHarmony 平台，需要验证官方 Linux ARM64 推理二进制与 Alpine 运行时后才随包登记。保留底层失败记录。真机、系统 PTY 和 Phone Use 按现有计划。

0.4.47 已验证最小本地包和真实 Creator 安装、Auto review 只读调用和恢复、LiveShare 本机 Owner、Forge 工作树和真实 ArkWeb、Inspector 与故障恢复。Creator 的第二次生成失败使用了已移除技能，保留该子会话证据。补测的确定性审查证明畸形结果、拒绝和取消均阻止真实写入，回归后恢复既有权限。远端共享、Forge 托管平台以及真机继续。 [证据](../evidence/emulator-optional-batch-0.4.47.json)

后续 Creator 兼容变更只更新 RC.5 自带实现中的提示引用。子会话使用 `dsh-doc` 及随包的插件、Web UI 参考。保持原用户确认、工作区权限、生成目录校验和安装流程。对源包中的两条旧引用与三份新资料执行了构建前检查。新的 HAP 仍需验证模型实际使用技能及创建、撤销和恢复。
