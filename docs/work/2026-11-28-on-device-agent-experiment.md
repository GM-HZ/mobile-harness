# HarmonyOS 端侧 Agent 验证

实验范围为 `codex/harmonyos-on-device-agent` 分支上的只读工具调用验证。第一可用版本的能力矩阵与发布范围继续以现行路线图为准。若决定把端侧模型交付给用户，再按路线图记录功能解锁、签名装配和真机门禁。

## 验证目标

1. 使用同一 llama.cpp 版本和同一组中文任务，对照两个 4-bit 模型。通过 OpenAI Chat Completions SSE 验证「搜索 → 读取 → 根据工具回填回答」和无需工具的对照任务。探针在内存中模拟工具，验证调用 ID、名称、JSON 参数和最终标记。
2. 在 DevEco HarmonyOS ARM64 虚拟机上验证原生 CPU 推理。模型服务仅绑定虚拟机回环，HDC 转发用于观测。记录系统版本、二进制和权重哈希、首个响应时间及退出状态。真机性能需要另测。
3. 完整 DSH 验收复用 `llm-pi-ai` 的 `openai-completions` 接入点。在虚拟机通过真实工作区工具验证读操作和结果回填。发布变体评估沿用仓库已有签名、门禁和证据流程。

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

使用本机版 `llama-server`，或由 HDC 转发虚拟机上已启动的模型服务。探针须等 `/health` 返回成功后再运行。两款模型使用相同配置，便于比较。

```sh
llama-server --host 127.0.0.1 --port 19867 --model "$GGUF" --alias "$MODEL" \
  --ctx-size 4096 --parallel 1 --n-gpu-layers 0 --threads 4 --predict 512 \
  --jinja --reasoning off --temp 0

MH_LOCAL_LLM_MODEL="$MODEL" MH_LOCAL_LLM_BASE_URL=http://127.0.0.1:19867/v1 \
  MH_LOCAL_LLM_BACKEND='llama.cpp b12774 macOS ARM64 CPU' \
  python3 gates/run.py --tier G1 --only local-llm-agent-probe --fail-on-skip --record
```

### DevEco 虚拟机

打包后的独立 PIE 在虚拟机里由 `posix_spawn` 启动时返回 `EACCES`。本实验的独立 HAP 静态链接 llama.cpp，在 N-API 的后台线程启动模型服务。HAP 面向测试虚拟机，模型文件通过 HDC 单独传入。

使用专用的 ARM64 测试虚拟机，先把 `MH_EMULATOR` 指向它的 HDC 回环地址，将 `GGUF` 指向已核验的权重。在仓库根目录执行以下命令，`LLAMA_OHOS_BUILD` 指向上面的 CMake 构建目录。第一次启动后可用 `hdc -t "$MH_EMULATOR" shell -b "$probe_bundle" pwd` 等待 App 沙箱可访问。

```sh
tests/probes/harmonyos-local-agent/build.sh "$LLAMA_OHOS_BUILD"
probe_bundle=org.mobileharness.localagentprobe
probe_hap=.build/stage/harmonyos-local-agent-probe/entry/build/default/outputs/default/entry-default-unsigned.hap
probe_assets=data/storage/el2/base/haps/entry/files

hdc -t "$MH_EMULATOR" install "$probe_hap"
hdc -t "$MH_EMULATOR" shell aa start -b "$probe_bundle" -a EntryAbility
hdc -t "$MH_EMULATOR" file send -b "$probe_bundle" "$GGUF" "$probe_assets/llama-lab.gguf"
hdc -t "$MH_EMULATOR" shell aa start -b "$probe_bundle" -a EntryAbility --ps operation start
hdc -t "$MH_EMULATOR" fport tcp:23965 tcp:39765
curl -f http://127.0.0.1:23965/health
```

在 `/health` 就绪后，从宿主机通过 USB 转发运行 `local-llm-agent-probe.py --base-url http://127.0.0.1:23965/v1 --model mh-on-device --backend 'llama.cpp HarmonyOS ARM64 VM' --timeout 240`。DSH 在同一虚拟机上的推理 URL 为 `http://127.0.0.1:39765/v1`，走原生 `openai-completions` provider。设 `contextWindow: 4096`、`maxTokens: 512`，以仅读取工具的测试预设运行工作区夹具。HDC 转发只用于宿主机探针和观测。

试验结束后执行 `hdc -t "$MH_EMULATOR" fport rm tcp:23965 tcp:39765` 和 `hdc -t "$MH_EMULATOR" shell aa force-stop "$probe_bundle"`。同一虚拟机更换模型时，先结束实验 App，再无参数启动以重新取得文件传输权限。
