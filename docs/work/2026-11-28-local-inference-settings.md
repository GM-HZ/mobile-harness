# 本地推理设置实验

按 2026-11-28 的功能请求，在 `codex/harmonyos-on-device-agent` 实验分支解锁本地推理设置。范围为主动启用的 HarmonyOS self 实验构建。当前发布范围沿用第一可用版本的功能冻结安排。此前的验证见 [鸿蒙虚拟机实测](2026-11-28-on-device-agent-experiment.md)。

## 使用流程

用户在设置中选择固定目录中的 LFM3-1.7B 或 Qwen3.5-2B，从各自发布者的 ModelScope 仓库下载固定版本。权重存入 App 私有目录，通过文件大小和 SHA-256 校验后才可启用。取消或失败时保留现有可用模型，推理引擎在同一时间只加载一个模型。 [LiquidAI 模型](https://www.modelscope.cn/models/LiquidAI/LFM3-1.7B-GGUF) · [Unsloth 模型](https://www.modelscope.cn/models/unsloth/Qwen3.5-2B-GGUF)

默认推理路径由 DSH 的现有模型设置决定。用户启用「优先使用本地推理」后，为后续会话设置已启动的本地模型。关闭开关或本地模型启动失败时，相同条件下恢复此前的默认模型。已发送的请求继续使用其原有路由，失败由 DSH 正常报告。模型切换由用户发起，可能结束当前的本地生成。

固定 DSH 版本的默认压缩预留为 65,536 token。现有会话手动切换到 16,384 token 的本地模型时，会触发上游模型切换压缩限制。当前实验的默认选择通过新会话使用，长会话还需验证。

原生引擎通过 N-API 启动，只监听受凭据保护的 `127.0.0.1` 端口。DSH 复用 `llm-pi-ai` 的 Chat Completions 协议和现有设置 RPC。App 只把短期回环凭据交给 DSH 已有的凭据服务，不记录到账本或日志。

普通包覆盖实验包后，首次正常连接会恢复实验前的 DSH 默认项并移除本地提供方。下载的模型数据保留在 App 私有目录。已由用户更改的默认项按 DSH 当前值处理。

## 构建与验证

将 llama.cpp checkout 放在固定提交 `171527522610996f5f0acf12334e185156ca8f44`。构建采用其 Git 归档，并在装配期应用 HarmonyOS CPU 兼容与服务停止补丁。权重由用户在 App 内按需下载。

```sh
HARMONY_UNSIGNED=1 HARMONY_SELF_BUILD=1 HARMONY_LOCAL_INFERENCE=1 \
  HARMONY_LLAMA_CPP_SOURCE=/path/to/llama.cpp ./build.sh --package
python3 scripts/adaptation/variant_check.py --variant self --require-local-inference --hap /path/to/experiment.hap
python3 gates/run.py --tier G1 --only local-inference-settings --fail-on-skip
MH_LOCAL_INFERENCE_EMULATOR=127.0.0.1:15555 MH_LOCAL_INFERENCE_HAP=/path/to/experiment.hap \
  python3 gates/run.py --tier G2 --only emulator-local-inference-e2e --fail-on-skip --record
```

测试此实验包时，入口在「设置 → 通用设置 → 本地推理」。LFM3 下载约 1.10 GB，Qwen 下载约 1.28 GB。推理配置为 16,384 token 上下文、1,024 token 输出、4 个 CPU 线程。下载、服务运行状态、默认路由和实际 Agent 工具任务分别验收。

G2 验收要求用专用虚拟机和没有该模型缓存的实际 App。测试点击下载并在设备内复核权重 SHA-256，通过界面启动模型并设为默认，再在同一个标准 DSH 会话中完成普通回复和只读文件工具回填。脚本分别记录耗时、路由来源、工具调用和回填结果。

## 实测

在 HarmonyOS ARM64 API 26 虚拟机中，通过设置界面启动了预置的 LFM3，DSH 发现了受凭据保护的本地模型。开启开关后模型目录将 LFM3 报告为默认项。关闭后恢复原默认项，停止推理后移除了实验提供方和凭据。首次 DSH 文本请求到达了原生引擎，9,548 token 的输入超过 8,192 token 的上限，返回 HTTP 400。应用和引擎随后同步增大了上限。

虚拟机使用内置回滚恢复空的测试配置后，安装 16,384 token 实验包重测。DSH 事件确认新会话使用 LFM3 和新的上下文上限，110 秒内未收到助手消息或回合结束事件，随后取消。此次没有继续跑工具回合。停止推理并正常重启后，原默认项仍被保留，实验提供方和凭据已清理。

另一台同 API 的虚拟机使用受控 HTTP 源，下载并发布了完整的 1,099,627,808 字节 LFM3 权重，设备内 SHA-256 与固定值一致。中途取消和失败后均清理了临时文件。该虚拟机直连 Hugging Face 的两次试验均在约一分钟后失败，收到 0 字节，第二次确认系统报告 `TIMEOUT`。实验包和普通 store 包分别通过对应的形态门禁。 [实测证据](../evidence/emulator/20261128-local-inference-settings.json)

## ModelScope 复测

同一个实验 HAP 分别在两台虚拟机从空缓存点击下载。LFM3 从 LiquidAI 仓库完成 1,099,627,808 字节的下载和校验，用时约 64 秒。Qwen 从 Unsloth 仓库完成 1,280,835,840 字节的下载和校验，用时约 73 秒。独立在设备内重算的 SHA-256 均与原有权重 pin 一致。

对旧构建的长回合诊断捕获到 pi-ai 的 300 秒流空闲超时。新版只为回环提供方使用 480 秒的上限。G2 以实际下载的 LFM3 启动标准 DSH 会话，在约 296 秒后收到了来自本地的助手消息，回合以 `max-tokens` 结束。普通回复断言失败，工具回合尚未执行。该次 G2 记录为失败。

同一 HAP 的独立诊断使用临时轻量预设和预置的同哈希 LFM3。普通回复与读取文件并回填标记的回合分别在约 44 秒和 22 秒完成。临时预设已移除。这项结果仅作为定位标准会话问题的诊断证据。 [ModelScope 与 DSH 复测](../evidence/emulator/20261128-local-inference-modelscope.json)
