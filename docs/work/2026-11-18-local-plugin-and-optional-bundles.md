# 鸿蒙本地插件与可选 bundle 回归

基线为 0.4.46、DSH RC.5。把本地 Creator 安装修复、Auto review、LiveShare 和已随包的 Forge 纳入同一轮构建与验收。

Creator 按绝对目录安装，pnpm 尝试创建符号链接并被系统拒绝。0.4.46 复现同一类目录用 file: 成功复制。适配仅针对 pnpm add 的裸绝对目录。验收包括真实 Creator 生成、安装、页面控件、撤销与从保留副本恢复，以及原有安装兼容性。

Auto review 和 LiveShare 使用锁定的上游 bundle，默认关闭。Auto review 验收当前会话选择、允许、拒绝、故障、取消、重启和关闭行为，默认工作区权限和普通审批沿用当前配置。LiveShare 使用独立合成会话，验收启停、连接及访问撤销，避免共享用户现有会话。Forge 验收现有工作树接口与 ArkWeb 呈现，真实外部的写入和合并使用明确授权。

语音并行验证两项依赖。ArkWeb 需要本机录音授权与请求来源校验。SenseVoice 上游识别器拒绝 OpenHarmony 平台，需要验证官方 Linux ARM64 推理二进制与 Alpine 运行时后才随包登记。保留底层失败记录。真机、系统 PTY 和 Phone Use 按现有计划。

0.4.47 已验证最小本地包和真实 Creator 安装、Auto review 只读调用和恢复、LiveShare 本机 Owner、Forge 工作树和真实 ArkWeb、Inspector 与故障恢复。Creator 的第二次生成失败使用了已移除技能，保留该子会话证据。补测的确定性审查证明畸形结果、拒绝和取消均阻止真实写入，回归后恢复既有权限。远端共享、Forge 托管平台以及真机继续。 [证据](../evidence/emulator-optional-batch-0.4.47.json)

后续 Creator 兼容变更只更新 RC.5 自带实现中的提示引用。子会话使用 `dsh-doc` 及随包的插件、Web UI 参考。保持原用户确认、工作区权限、生成目录校验和安装流程。对源包中的两条旧引用与三份新资料执行了构建前检查。新的 HAP 仍需验证模型实际使用技能及创建、撤销和恢复。

## 语音原生推理探针

同版本 Sherpa ONNX 1.13.8 提供官方鸿蒙 ARM64 C API 和 ONNX Runtime。下载包 SHA-256 为 `7473e1f6138c2d33a26adda01dd94f4d618089370957ed374f8cc0d50b8cdfa7`。模型使用 DSH RC.5 已锁定的 239,233,841 字节 int8 权重，SHA-256 为 `c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51`。模型仅传入测试机私有目录。[官方 Sherpa 1.13.8 制品](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v1.13.8)

- 桌面合成 16 kHz 单声道 PCM，通过真实鸿蒙 HAP 内嵌的 Node 执行。第一版探针加载时调用到 ArkTS 的同名 `napi_create_string_utf8` 并触发 SIGBUS。第二版从已加载的 `libnode.so` 解析对应符号，避免混用两个运行时。
- 第二版同一 HAP 的 SHA-256 为 `2b53a651cb372bc422a37ef0f1bd10575778eea34188b4ed0b614bf42bfa9822`。英文样本输出“Testing a F voice transcription.”，将 “offline” 误识。普通话样本精确识别“今天我们测试语音输入。”，载入 C API 后初始化及识别耗时 1,371 ms，脚本退出 0。
- 同版 ArkWeb 在回环页面报告安全上下文及 `getUserMedia` 支持。麦克风权限桥接已在隔离工程中编译，尚未验证实际录音授权、上传 PCM、VAD、停止与草稿回填。完整语音输入仍待验。
- 本次为临时探针。每次测试均覆盖恢复到准确的 0.4.47 HAP 和原配置。中间制品及输出位于本地 `.build/voice-native/`。

## 0.4.51 语音接入

同一个官方语音 bundle 使用鸿蒙 ARM64 Sherpa C API，模型与 Silero VAD 在专属 Node worker 初始化。原 HTTP 语音请求出现合法 WAV 进入识别前被拒绝，改为以私有线程消息传递 PCM。应用仅向回环主页面授予通过鸿蒙系统确认的麦克风请求，登录内嵌页无此入口。默认关闭语音及其他既有可选插件。

0.4.51 已完成标准 API 的双次转写、畸形数据拒绝和停用回收。合成输入的 ArkWeb 录音测试仍未获取流，真机麦克风与草稿回填待验。Creator 实际加载了 `dsh-doc`，仍未完成生成验证。 [本轮证据](../evidence/emulator-voice-input-0.4.51.json)
