# 本地推理设置实验

按 2026-11-28 的功能请求，在 `codex/harmonyos-on-device-agent` 实验分支解锁本地推理设置。范围为主动启用的 HarmonyOS self 实验构建。当前发布范围沿用第一可用版本的功能冻结安排。此前的验证见 [鸿蒙虚拟机实测](2026-11-28-on-device-agent-experiment.md)。

## 使用流程

用户在设置中选择固定目录中的 LFM3-1.7B 或 Qwen3.5-2B，自行发起线上下载。权重存入 App 私有目录，通过文件大小和 SHA-256 校验后才可启用。取消或失败时保留现有可用模型，推理引擎在同一时间只加载一个模型。

默认推理路径由 DSH 的现有模型设置决定。用户启用「优先使用本地推理」后，为后续会话设置已启动的本地模型。关闭开关或本地模型启动失败时，相同条件下恢复此前的默认模型。已发送的请求继续使用其原有路由，失败由 DSH 正常报告。模型切换由用户发起，可能结束当前的本地生成。

原生引擎通过 N-API 启动，只监听受凭据保护的 `127.0.0.1` 端口。DSH 复用 `llm-pi-ai` 的 Chat Completions 协议和现有设置 RPC。App 只把短期回环凭据交给 DSH 已有的凭据服务，不记录到账本或日志。

普通包覆盖实验包后，首次正常连接会恢复实验前的 DSH 默认项并移除本地提供方。下载的模型数据保留在 App 私有目录。已由用户更改的默认项按 DSH 当前值处理。

## 构建与验证

将 llama.cpp checkout 放在固定提交 `171527522610996f5f0acf12334e185156ca8f44`。构建采用其 Git 归档，并在装配期应用 HarmonyOS CPU 兼容与服务停止补丁。权重由用户在 App 内按需下载。

```sh
HARMONY_UNSIGNED=1 HARMONY_SELF_BUILD=1 HARMONY_LOCAL_INFERENCE=1 \
  HARMONY_LLAMA_CPP_SOURCE=/path/to/llama.cpp ./build.sh --package
python3 scripts/adaptation/variant_check.py --variant self --require-local-inference --hap /path/to/experiment.hap
python3 gates/run.py --tier G1 --only local-inference-settings --fail-on-skip
```

测试此实验包时，入口在「设置 → 通用 → 本地推理」。LFM3 下载约 1.10 GB，Qwen 下载约 1.28 GB。初始推理配置为 8,192 token 上下文、1,024 token 输出、4 个 CPU 线程。下载、服务运行状态、默认路由和实际 Agent 工具任务分别验收。
