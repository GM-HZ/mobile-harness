# HarmonyOS 端侧 Agent 验证

实验范围为 `codex/harmonyos-on-device-agent` 分支上的只读工具调用验证。第一可用版本的能力矩阵与发布范围继续以现行路线图为准。若决定把端侧模型交付给用户，再按路线图记录功能解锁、签名装配和真机门禁。

## 验证目标

1. 使用同一 llama.cpp 版本和同一组中文任务，对照两个 4-bit 模型。通过 OpenAI Chat Completions SSE 验证「搜索 → 读取 → 根据工具回填回答」和无需工具的对照任务。探针在内存中模拟工具，验证调用 ID、名称、JSON 参数和最终标记。
2. 在 Mate 60 上验证原生 ARM64 CPU 推理。仅在手机回环监听模型服务，USB 转发用于观测，不参与推理。记录系统版本、二进制和权重哈希、首个响应时间、峰值内存及退出状态。
3. 完整 DSH 验收复用 `llm-pi-ai` 的 `openai-completions` 接入点。在隔离应用中通过真实工作区工具验证读操作、结果回填和取消。发布变体评估沿用仓库已有签名、门禁和证据流程。

## 固定输入

| 输入 | 版本或文件 | SHA-256 或提交 |
| --- | --- | --- |
| [llama.cpp](https://github.com/ggml-org/llama.cpp/releases/tag/v1.1.0) | `v1.1.0` | `171527522610996f5f0acf12334e185156ca8f44` |
| [Liquid AI LFM3-1.7B GGUF](https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF/blob/cd0c74c/LFM3-1.7B-Q4_K_M.gguf) | `LFM3-1.7B-Q4_K_M.gguf` | `3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4` |
| [Unsloth Qwen3.5-2B GGUF](https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/blob/f6d5376/Qwen3.5-2B-Q4_K_M.gguf) | `Qwen3.5-2B-Q4_K_M.gguf` | `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223` |

LFM3 的后训练包括工具调用监督学习、工具与 Agent 专家蒸馏，以及在真实 Harness 中的浏览与办公强化学习。另有针对 108 个手机工具的公开 GRPO 教程和数据集。Qwen3.5-2B 的模型卡提供 Agent 评测、Qwen-Agent 接入示例和工具模板。两者分数需要结合各自评测设置解读。 [LFM3 训练说明](https://huggingface.co/LiquidAI/LFM3-1.7B#training) · [手机工具数据集](https://huggingface.co/datasets/LiquidAI/phone-assistant-tools) · [Qwen3.5-2B 模型卡](https://huggingface.co/Qwen/Qwen3.5-2B)

## 复现

在固定版本的 llama.cpp 临时 checkout 中，修改 `ggml/src/ggml-cpu/ggml-cpu.c` 的 `ggml_thread_apply_affinity()`，把 `sched_setaffinity` 前的 `#ifdef __ANDROID__` 改为 `#if defined(__ANDROID__) || defined(__OHOS__)`。DevEco Native SDK 26.0.0 在 `_GNU_SOURCE` 下提供该接口。

```sh
cmake -S . -B ohos-build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}/sdk/default/openharmony/native/build/cmake/ohos.toolchain.cmake" \
  -DOHOS_ARCH=arm64-v8a -DOHOS_STL=c++_static -DBUILD_SHARED_LIBS=OFF \
  -DCMAKE_C_FLAGS=-D_GNU_SOURCE -DCMAKE_CXX_FLAGS=-D_GNU_SOURCE \
  -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DGGML_LLAMAFILE=OFF -DGGML_CPU_KLEIDIAI=OFF \
  -DLLAMA_OPENSSL=OFF -DLLAMA_SUBPROCESS=OFF -DLLAMA_BUILD_APP=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_MTMD=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_UI=OFF
cmake --build ohos-build --target llama-server --parallel 8
```

使用本机版 `llama-server`，或由 HDC 转发真机上已启动的模型服务。探针须等 `/health` 返回成功后再运行。两款模型使用相同配置，便于比较。

```sh
llama-server --host 127.0.0.1 --port 19867 --model "$GGUF" --alias "$MODEL" \
  --ctx-size 4096 --parallel 1 --n-gpu-layers 0 --threads 4 --predict 512 \
  --jinja --reasoning off --temp 0

MH_LOCAL_LLM_MODEL="$MODEL" MH_LOCAL_LLM_BASE_URL=http://127.0.0.1:19867/v1 \
  MH_LOCAL_LLM_BACKEND='llama.cpp b12774 macOS ARM64 CPU' \
  python3 gates/run.py --tier G1 --only local-llm-agent-probe --fail-on-skip --record
```
