# 内置能力的剩余验收与补齐

目标：继续完成“补全 DSH 能力”，核对标准 preset 中尚未执行验收的 Skills、Office、目标／待办等工具。对实际不可用的能力建立复现，再优先通过现有提供者接口及插件机制适配，保持完整功能语义。

基线：`f6380fd9ecd6681593c4abb08a36d92f9dadaf39`，`codex/harmonyos-package-management`，普通 HAP 0.4.31／官方 npm RC.4；工作区干净。此前 17 组模拟器回归及原生恢复 UI 已通过并推送，不能替代本轮未验能力。

非目标：不改变 Phone Use／系统 PTY 的既有暂缓要求，不使用电脑执行替代手机本机，不跳过审批或降低默认 Bash 限制，不改 SayAct。

验证计划：按官方 RC.4 bundle／preset 清点入口；在 API 26 Phone 模拟器通过真实模型触发实际工具；Office 使用可校验的最小 DOCX／XLSX 等夹具，回读输出并检查内容、页面或公式结果。先验证手机可用的 WASM／原生引擎执行路径，不能把资源文件存在或工具列表出现算作执行成功。任何适配需验证取消、故障、生命周期和已有主链路回归，绑定准确源码及 HAP。完成后提交远端。

来源初查：官方 LibreOffice Kit 0.2.3 随当前 npm 锁文件提供 145 MB WASM 运行资源；Host 是 JITless，尚无成功转换证据。上游 Office provider 负责队列、缓存、文件授权与取消，应保留这些职责。不能用纯文件改写冒充渲染／格式转换／重算。

实现：通过模块解析钩子，仅将上游 Office provider 的公开 `createConverter` 消费入口接到鸿蒙适配器。保留上游 OfficeKit 的源授权、队列、缓存、输出验证和取消；转换使用同一锁定的官方 LibreOffice Kit WASM，在手机随包 Linux Node 的独立进程中执行。Host 保持原生 JITless。系统字体目录按需映射，Host 临时目录固定在应用私有运行时内。恢复模式拒绝创建 Office worker。

实测进展：原始 0.4.31 在真实 `office_convert` 返回没有可用字体；手机的随包 Node 在清除该次命令的 NODE_OPTIONS 后可执行最小 WASM，返回 42。同一官方 Kit 的独立 DOCX→PDF 试验成功。0.4.32 普通包适配后，实际模型调用的 DOCX→PDF、Host 缓存命中、页面附件图像和 XLSX 公式重算已通过；重算保留 C1 的公式并将缓存值由 0 更新为 42。页面图像已目视确认含原测试文本。PowerPoint 转换仍出现超时，正在用相同引擎做本机对照并检查进程生命周期，不计为通过。

测试记录要求：第一次新的 Office 冒烟在加载 Skill 时，模型重复了两次相同调用；该次失败保留。原断言未修改，同一脚本第二次通过 Skill 与 Word／Excel 子项，随后在 PPT 转换处失败。不可只汇报成功子项。

状态：实施中；PPT、取消、销毁及进程故障恢复待完成。
