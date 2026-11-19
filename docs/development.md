# 鸿蒙构建与验证

使用 DevEco Studio SDK 26 和 ARM64 Phone。构建使用 DevEco 自带的 JDK、Node、ohpm 和 hvigor。普通构建的调试包保持 `org.sayact.nodepoc`，用于兼容已有签名和测试数据。

## 获取源码

```sh
git submodule update --init --depth=1
./scripts/vendor/verify.sh
```

父仓库 Git 链接固定每个组件的完整提交。当前直接子模块为 DSH、Node、Termux PRoot、DSHM、Termony、TypeScript language server、TypeScript 和 Pyright。构建只读取锁定的子模块，DSHM 的 fetch shim 与许可证直接取自相应子模块。Termony 的嵌套终端组件在当前路径未使用。升级子模块时先提交并推送上游改动，再更新父仓库的 Git 链接。

## 准备输入并打包

1. 备齐 [输入清单](build-inputs.sha256) 指定的 0.4.24 原始打包输入，保留清单中的相对路径。已有开发机的输入存放在 `.build/inputs/harmonyos/`，也可通过 `HARMONY_INPUTS_DIR` 指向一份外部输入目录。当前配方使用已校验的 Node 和 PRoot 输入。DSH 源码子模块固定到官方 RC.5 发布标签，运行时用 [npm 锁文件](../runtime/harmonyos/dsh/package-lock.json) 装配上游发布包，并核对随包原生绑定对应的上游字节。首次准备需要访问 npm 和 Alpine 稳定仓库。新增 Alpine 包可预填至 `.build/runtime-package-inputs/` 或通过 `HARMONY_GUEST_APKS_DIR` 提供已经校验的归档。
2. 参考 [DevEco 配置示例](../apps/harmonyos/build-profile.example.json5) 设置本机签名。签名配置从仓库根目录的 `build-profile.json5` 或 `HARMONY_SIGNING_PROFILE` 读取。模拟器用 `HARMONY_UNSIGNED=1`。
3. 在仓库根目录运行：

```sh
HARMONY_UNSIGNED=1 ./build.sh
```

`./build.sh --prepare-only` 生成 DevEco 暂存工程。编辑源文件用 `apps/harmonyos/`，在 DevEco 打开 `.build/stage/harmonyos/` 进行构建或调试。仓库保留源码、补丁与摘要。运行时输入和签名配置保存在本机。

## 打包与发布

```sh
HARMONY_UNSIGNED=1 ./build.sh --package
HARMONY_SIGNING_PROFILE=/absolute/path/to/build-profile.json5 ./build.sh --package
```

`--package` 在 `.build/artifacts/harmonyos/` 生成带版本的 ARM64 HAP 及各自的 `.sha256` 文件。未签名包供 Phone 模拟器使用。普通调试签名包适用于签名配置覆盖的真机，可以在同包名、同签名且版本号更高时覆盖安装。

GitHub Actions 的 **Build HarmonyOS HAP** 可在 `main` 上手动触发。注册带 `deveco` 标签的 ARM64 macOS runner，并预装 DevEco Studio SDK 26。将校验清单中的运行时输入存放在 runner 检出目录之外。通过仓库 Actions 变量 `DEVECO_HOME` 和 `HARMONY_INPUTS_DIR` 指定绝对路径。工作流调用同一个打包命令并上传未签名 HAP 和校验文件。

在模拟器通过回归后，从对应的 Git 提交创建 Release。发布包名中的版本号来自 `apps/harmonyos/AppScope/app.json5`，例如以下命令上传 0.4.26 的模拟器包。需要分发真机调试包时，将 `signed.hap` 及其校验文件一同附到该私有仓库的 Release。

```sh
version=0.4.26
git push origin main
gh release create "v$version" --target "$(git rev-parse HEAD)" \
  --title "DSH-MH $version · HarmonyOS" --notes-file /absolute/path/to/release-notes.md \
  .build/artifacts/harmonyos/dsh-mh-harmonyos-arm64-v"$version"-unsigned.hap{,.sha256}
```

## Phone 模拟器回归

显式选定回环 HDC 目标，安装并启动待测 HAP。故障夹具会在独立 Phone 模拟器上安装一个测试 DSH bundle，主动让 Host 进程崩溃并恢复正常 profile。测试使用模拟器测试数据。

```sh
tests/bench/measure-emulator-start.sh <loopback-target> restart
python3 tests/smoke/emulator-recovery.py <loopback-target> .build/emulator-recovery.json
```

启动计时的 `fresh` 模式会清空目标 App 数据，仅用于独立模拟器。恢复测试要求正常模式已启动，并会记录匿名鉴权、插件崩溃、安全模式和旧会话续接。

启动计时可通过第三个参数指定观测次数，默认 60。需要观察并行负载下的慢启动时可指定 120，并从设备日志分别核对解包、Host 就绪和 ArkWeb 就绪。应用的 60 秒 Host 看门狗从启动 Host 时起算。

## MCP 模拟器回归

普通 HAP 启动后可在隔离的 Phone 模拟器运行 MCP 冒烟测试。测试脚本在退出时清理临时配置。提供 `MH_TEST_DEEPSEEK_API_KEY` 后，脚本会暂存测试凭据，验证模型调用工具并清理凭据。没有配置该变量时，仅验证协议连接、工具列表和探针关闭。

```sh
python3 tests/smoke/emulator-mcp-stdio.py <loopback-target> .build/emulator-mcp-stdio.json
```

## Workflow 模拟器回归

0.4.29 或更新的正式 HAP 启动后，在独立模拟器用真实模型验证 Workflow。命令读取本机环境中的测试凭据，脚本在完成后移除临时设备配置。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-workflow.py <loopback-target> .build/emulator-workflow.json
```

加 `--fanout-only` 验证两个独立会话中的 Workflow。每条提交四个子任务，记录实际峰值并发、双 Workflow 重叠时间、结果归属和 helper 回收。

加 `--soak` 在第 0、10、30、60 和 120 分钟重复上述双 Workflow。每轮产生不同的校验标记并归档测试会话，JSON 逐轮写入。只有 `coverageComplete` 和 `temporaryModelCredentialRemoved` 均为真才算结束。运行期间独占模拟器和它的测试凭据槽。

## pi-ai 真实模型路由回归

在独立模拟器上按标准设置暂存两条 pi-ai 路由，使用同一个 DeepSeek 公网端点验证模型发现、文件读取工具往返和重启续接。测试结束移除临时凭据并恢复原 profile。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-pi-ai-protocols.py <loopback-target> .build/emulator-pi-ai.json
```

## 通用 PTC 回归

0.4.31 起普通构建默认包含通用 PTC。构建机将锁定 Node 子模块中的 Amaro 用固定 Binaryen 132.0.0 转为纯 JavaScript，校验下载包与两个生成文件的摘要并缓存到 `.build/portable-amaro/`；手机无需 WASM 或编译器。恢复模式跳过 PTC。`HARMONY_PTC_AMARO_DIR` 仍可提供相同摘要的预生成文件。安装普通包并通过 HDC 启动后，冒烟测试经真实 DSH 会话触发 `run_code`，检查工作区文件授权、嵌套工具和取消，退出时清除临时文件与凭据。

```sh
HARMONY_UNSIGNED=1 ./build.sh
hdc -t <loopback-target> install -r .build/stage/harmonyos/entry/build/default/outputs/default/entry-default-unsigned.hap
hdc -t <loopback-target> shell aa start -a EntryAbility -b org.sayact.nodepoc
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-ptc-host.py <loopback-target> .build/emulator-ptc-host.json
```

可选参数 `--read-only` 验证只读会话。用 `--mode persistent-in-memory` 验证 REPL，用 `--mode vm-script` 验证 Script，给后者加 `--script-persistence` 验证 Script 跨轮保留变量。这些回归会临时写入官方 Host profile patch 并重启应用，要求独立模拟器的用户 patch 槽为空。测试结束会移除临时 patch，恢复正常模式。

使用 `--additional-roots` 验证三个显式附加目录，包括重叠授权、跨目录重命名及工作目录切换。再加 `--read-only` 验证附加配置无法允许只读会话写入。夹具创建的目录在退出时清理。实验后端每个进程最多接受 16 个附加目录，根目录路径必须为已存在的规范化物理目录。

同一普通 HAP 可运行 Agent 生命周期回归。脚本通过标准 bundle 机制安装临时测试插件，由插件持有真正的 `AgentHandle`，让模型在其会话运行 PTC，再调用 `dispose()`。测试覆盖空闲及同步死循环中的销毁、进程回收，以及从持久化记录恢复会话。脚本要求用户 profile patch 槽为空，退出时恢复原 manifest、锁文件和启动模式，移除临时配置。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-ptc-lifecycle.py <loopback-target> .build/ptc-lifecycle-repl.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-ptc-lifecycle.py <loopback-target> .build/ptc-lifecycle-script.json --mode vm-script
```

审批回归使用实际鉴权的 Remote Event 流接收请求，通过 DSH 的事件结果 RPC 批准或拒绝。脚本复用构建缓存中按锁文件安装的 ws 模块。默认验证工作区写到单次完整文件授权，加 `--read-only` 验证只读到单次工作区写，加 `--retained` 验证保留状态的 REPL。测试只修改自建夹具。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-ptc-approval.py <loopback-target> .build/ptc-approval.json
```

应用数据视图的链接能力是 PTC 链接压力场景的前置条件。下列脚本只读记录应用上下文与 shell 域的符号链接、硬链接创建结果，并扫描工作区现有链接和链接数，用于判断端到端夹具能否运行。

```sh
python3 tests/smoke/emulator-ptc-link-fixture.py <loopback-target> .build/ptc-link-fixture.json
```

## 本地模型路由回归

本机 Ollama 经标准 provider 设置接入，测试用回环夹具把设备请求转发到宿主模型服务。两条 OpenAI 兼容协议分别验证模型发现、流式请求、工具目录、图片附件、重启保持与配置恢复。测试使用本机模型，无外部 API 凭据；小模型的工具调用与视觉问答质量只记录不断言。

```sh
python3 tests/smoke/emulator-ollama.py <loopback-target> .build/ollama-provider.json \
  --model <ollama-model> --context-window <tokens> --max-tokens <tokens>
```

边界压力回归在真实 PTC 会话里检查程序无法自建链接、读链接目标、改元数据或改写打开，并临时安装一个宿主插件按门控把程序父目录移出授权根再移回。每轮读写都应在根外拒绝，且被移出目录不被写入。测试结束移除插件并把 profile manifest 恢复为原字节。需要已登录的模型路由，或 `MH_TEST_DEEPSEEK_API_KEY`。

```sh
python3 tests/smoke/emulator-ptc-boundary.py <loopback-target> .build/ptc-boundary.json
```

## Host 进程探针

```sh
HARMONY_EXPERIMENTAL_HOST_PROCESS=1 ./build.sh
```

此模式在 `.build/stage/harmonyos-process-probe/` 生成独立包 `org.mobileharness.processprobe`。它使用实验性的进程启动方式，适用于 Phone 模拟器实验。原生恢复页在实验包中终止并重新启动 Host，同时 UI 可继续运行。普通构建仍由应用内 Node 启动，恢复页以重新打开应用为恢复边界。使用同一模拟器验证两种包时，应先停止另一包，两个 DSH 实例使用同一个回环端口。

## 工具链与文件工具回归

普通包可运行真实模型驱动的完整工具链测试。默认 Bash 必须拒绝；随后仅批准精确夹具命令一次，验证 pip target、两套 venv、Git、Node fetch、curl、SQLite、时区和五个文件工具。完整 Python 夹具采用 180 秒命令预算；PRoot 下的安装执行时间与原生 Host 启动时间分别记录。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-toolkit.py <loopback-target> .build/emulator-toolkit.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-python-wheel.py <loopback-target> .build/emulator-python-wheel.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-python-wheel.py <loopback-target> .build/emulator-python-native.json --native-suite
```

原生 Python 回归通过正式 Bash 单次审批，在隔离 venv 从公网 PyPI 下载固定 CPython 3.12 ARM64 musllinux wheel，验证 SHA-256 并实际导入扩展。两个场景都用 `venv --copies`。 `--native-suite` 在一次明确批准的后台 Bash 作业中组合 NumPy、随 wheel 提供的 OpenBLAS 与 orjson。验收等待同一作业退出，再核对线性方程解和 UTF-8 JSON 往返。网络与符号链接诊断保留在工具输出。

## 账号登录回归

脚本点击 ArkWeb 的登录入口，确认正式 DeepSeek 页面打开并可返回聊天。随后使用独立回环服务和临时凭据文件验证 DSH 账号回调、PKCE 交换、重启恢复与登出撤销。运行在已退出账号的独立模拟器，结束后恢复原 profile。

```sh
python3 tests/smoke/emulator-account.py <loopback-target> .build/emulator-account.json
```

## Office 模拟器回归

0.4.32 通过上游 Office skill 与三个文档工具执行转换、页面渲染和公式重算。测试要求独立模拟器及测试凭据，输出的 PDF、工作簿与实际附件图像保存在 `--artifacts` 指定目录。`--require-native` 用于要求当前模拟器确实选择原生 worker。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-office.py <loopback-target> .build/office.json \
  --artifacts .build/office-artifacts --require-native
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-office-cancel.py <loopback-target> .build/office-cancel.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-office-provider.py <loopback-target> .build/office-provider.json
```

Provider 测试通过标准 bundle 临时注册夹具，为每种场景创建真正的独立 OfficeKit。验证在途动作、超时、销毁、所有新建进程回收和失败后继续执行；退出时恢复原 profile、锁文件与启动模式。应用内输出按上游保留策略管理。完整说明见 [原生 Office](research/harmonyos-native-office.md)。

## 标准工具、交互与 HTTP/1 回归

0.4.33 的构建将固定 Undici llhttp 转为 JS，按源与输出摘要验证；复用固定的 Binaryen 132.0.0。主 Host 保持 jitless。构建后的电脑网络契约在同一份 Node modules 上分别用原生 WASM 和 jitless 运行，验证代理、流式正文、取消、错误和连接复用。测试参数必须使用锁文件对应的构建目录与准确生成物。

```sh
node --jitless tests/contract/portable-http.cjs /absolute/path/to/locked/node_modules /absolute/path/to/dsh-harmony-llhttp.cjs
node tests/contract/portable-http.cjs /absolute/path/to/locked/node_modules /absolute/path/to/dsh-harmony-llhttp.cjs
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-standard-tools.py <loopback-target> .build/standard-tools.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-web-tools.py <loopback-target> .build/web-tools.json --search
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-interactions.py <loopback-target> .build/interactions.json
```

标准工具测试创建自己的目标与团队任务，验证强停重开后状态，最后清除目标、关闭团队模式并删去自己的文件。交互测试通过鉴权 Remote Events 模拟回答和计划决定，不需要真人点击；插件发现只批准本次列表读取。网页夹具临时反向映射电脑上的受控 HTTP/1 服务，实际客户端和 DSH 工具运行于模拟器，退出时清除端口与测试凭据。`--search` 额外调用实际搜索提供者。RC.5 默认 DeepSeek 模型可再传 `--require-messages-search`，要求会话记录实际的官方 Messages 搜索请求。

## Agent 与目标续跑补验

以下测试使用普通包，不改 profile。fork 子会话用正式 subagent 地址读取，结果只取其新事件；文件通过 base64 精确回读，以免 HDC 文本接口去掉空白。目标夹具初始轮只创建，随后必须由自动 continuation 实际执行并完成。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-agent-continuation.py <loopback-target> .build/agent-continuation.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-goal-continuation.py <loopback-target> .build/goal-continuation.json
```

## 官方可选 Ralph 与会话搜索补验

测试临时把两个随包官方 bundle 加到独立模拟器的标准 profile，保持默认开关不变。all 场景覆盖两轮真正 fresh 子会话及字节结果、实际子模型请求中取消与 helper 回收、归档会话重启后的五个查询工具，以及跨工作区的空搜索／精确拒绝。manifest、锁文件与 boot 备份恢复，正常重启后再次对照摘要。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-optional-iteration.py <loopback-target> .build/optional-iteration.json
```

可用 `--case ralph`、`search`、`cancel` 或 `scope` 单独复现。scope 的工具错误是明确要求的拒绝结果，仍精确检查错误内容和无数据泄露，其他调用继续要求成功。该测试不认证任意长循环，也不把工具级工作区授权说成操作系统沙箱。

## Host 子进程与可选工作树回归

0.4.34 替换公共 subprocess provider，复用上游的输出管理和生命周期。工作树测试临时启用随包官方 bundle，使用真实 Git 创建、进入、重启续接并归档。默认策略必须拒绝；只有夹具自身的会话通过正式 `/permission` 命令明确选择完整权限。Bash 仍显示原 `/workspace-native` 视图，工作树控制文件保留 Host 的原生路径，测试分别精确验证。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-worktree.py <loopback-target> .build/worktree.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-subprocess.py <loopback-target> .build/subprocess.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-subprocess.py <loopback-target> .build/subprocess-extensions.json --extension-probes
```

后者用标准临时 bundle 验证真正的 provider，包括 stdin/stdout、特殊字符 argv、真实嵌套 Node、环境脱敏／覆盖／删除、非零退出、尾部限额与完整 spill、实际运行中的取消和 Context 销毁。PRoot 取消可能报告退出码1；脚本保留此事实并要求进程范围退出和 helper 回收。两者恢复原 manifest／锁文件并回读摘要，移除本次测试目录和凭据。设计和失败原因见 [Host 子进程](research/harmonyos-host-subprocess.md)。不要在同一模拟器并行运行修改 profile 的回归。

扩展探针用 DevEco SDK 和锁定 Node 头文件分别编译鸿蒙和 Linux ARM64 addon。主 Host 能加载 HAP 内的语音 addon，本轮传入的外部鸿蒙 addon 返回 `ERR_DLOPEN_FAILED`。Linux addon 通过官方 subprocess 服务在 Alpine 子进程中执行。

在已验证可运行 JIT 的模拟器上，插件可让受管理的 Alpine Node 显式传入 `--no-jitless` 执行 WASM。直接运行 TypeScript 并使用 Node 自带的 fetch 时，可同时传入空的 `NODE_OPTIONS`。已有 Mate 60 记录存在 Linux Node 默认 JIT 启动失败，主 Host 和普通子进程的默认选项保持原样。

## LSP 模拟器回归

0.4.35 默认通过自带 bundle 装配官方 LSP，按需启动 TypeScript language server。正常语义检查使用真实模型与真实服务器；生命周期检查的透明 relay 只暂扣真实 hover 响应，专门验证取消升级和销毁，不生成语义结果。测试完成恢复原配置、锁文件和普通启动模式。

```sh
python3 tests/smoke/emulator-lsp-bundle.py <loopback-target> .build/lsp-bundle.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-lsp.py <loopback-target> .build/lsp.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-lsp-lifecycle.py <loopback-target> .build/lsp-lifecycle.json
```

源码 pins 与 npm 锁一致；构建在 DSH release 内提供独立编译器工具链，并以整个实际层的 SHA-256 判断是否重新解包。不能仅凭包目录存在判断插件启用或测试通过。见 [LSP 设计](research/harmonyos-lsp.md)。

## 会话压缩模拟器回归

受控 Messages 夹具覆盖 HTTP 400 溢出、两次自动压缩、重试及重启检查点。它使用一次性凭据和回环服务，测试结束恢复原 profile。

```sh
python3 tests/smoke/emulator-compaction-overflow.py <loopback-target> .build/compaction-overflow.json
```

公网探针用一次合成的流式 Messages 请求读取服务端报出的实际上限。可把返回报告交给模拟器夹具回放同一错误的类型和消息，验证正式 DSH 的压缩、重试及重启恢复。实时请求只发送合成文本。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/bench/deepseek-public-context.py .build/context-limit.json
python3 tests/smoke/emulator-compaction-overflow.py <loopback-target> .build/overflow-replay.json \
  --provider-error-report .build/context-limit.json
```

0.4.58 另有完整公网回归。使用正式导入接口创建合成历史和独立会话，DSH 自己向公网发请求。脚本校验持久化的 HTTP 400、摘要排除当前回合、原回合精确回复、重启恢复、旧历史和配置清理。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-compaction-live-overflow.py <loopback-target> .build/live-overflow.json
```

以下三个脚本要求已经安装普通0.4.35包。手动脚本验证真实摘要、事实回忆和同会话重启；故障脚本临时安装一个标准 bundle，在收到真实模型文本后才取消或注入流错误；自动脚本复制完整standard到独立临时预设，仅降低压缩阈值／保留预算，保留全部工具，不修改正式默认配置。结束后恢复原预设、profile、锁文件、凭据和普通模式。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-compaction.py <loopback-target> .build/compaction.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-compaction-faults.py <loopback-target> .build/compaction-faults.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-compaction-auto.py <loopback-target> .build/compaction-auto.json
```

## 原生 addon 加载位置实测

通过随包 Inspector 在 Host 主进程内评估加载结果：同一份 `libdshshell.so` 字节按安装目录 soname 加载成功，复制到应用数据目录后按绝对路径加载失败。测试会临时启用 Inspector、结束后停用并恢复 profile 与启动文件，不需要模型凭据。

```sh
python3 tests/smoke/emulator-native-addon-location.py <loopback-target> .build/native-addon-location.json
```

## 后台定时任务回归

模拟器从应用进入系统桌面，持续通过 AbilityManager 核对应用处于 `BACKGROUND`，在同一会话等待计划任务投递和真实模型回复。回到前台核对 Host 启动身份、历史完整性和最初消息的准确回忆。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-background-schedule.py <loopback-target> .build/background-schedule.json
```

`--soak` 将七次投递分布在两小时内，并在第 105 秒后安排一次应用强停重启。检查旧事件前缀、重启前尚未投递的任务以及回到桌面后的真实模型回复。每次投递更新 JSON 检查点，`finished` 为真时表示最终回忆和清理已通过。长测占用该模拟器和临时模型密钥槽。

## Minimal 持久 Bash 回归

仅在独立 Phone 模拟器运行。使用实际模型和官方 Bash 工具核对默认拒绝、两条会话状态隔离、退出码、后台任务、空 stdin，以及用户取消后的进程回收和重建。测试仅给测试会话选择完整文件权限，结束时恢复 profile 与临时模型凭据。0.4.61 可加 `--expect-absent` 验证旧包未暴露 Minimal 预设。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-persistent-bash.py <loopback-target> .build/persistent-bash.json
```

## 工作区依赖工具

构建使用 [PyPI wheel 锁文件](../runtime/harmonyos/dsh/office-wheels.json)，缓存位于 `.build/runtime-package-inputs/office-wheels/`。模拟器验收用真实模型调用 `load_workspace_dependencies` 和 `office-xlsx` 技能，再通过单次批准执行返回的 Python、Node 和 pnpm 路径。加 `--expect-absent` 可在 0.4.60 核对工具尚未暴露。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-workspace-dependencies.py <loopback-target> .build/workspace-deps.json
```

## Cordis 与替代编辑回归

0.4.36 修复独占创建发布后，以下检查使用真实模型和正式插件。Cordis 要求真实 ArkWeb 客户端已连接；超出 inline 上限时验证正式保留文件和实际 read。编辑测试仅临时启用官方字符串编辑器与 apply_patch；权限、完整字节、多文件预检及部分提交报告均保留检查。文件发布检查通过标准测试 bundle 验证实际 ctx.fs，包含真实暂存后的竞争创建和取消。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-cordis-inspect.py <loopback-target> .build/cordis.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-alternative-editing.py <loopback-target> .build/alternative-editing.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-fs-publication.py <loopback-target> .build/fs-publication.json
```

独立的 `emulator-inspector-availability.py` 只探测诊断 Worker，要求设备测试 Key 槽为空，临时通过官方 profile bundle 启用，结束恢复原字节。它不验证完整 CDP；当前0.4.36实际失败于 Worker 的 require-builtin 鸿蒙绑定，不属于通过的三组检查。

0.4.44 的下列脚本通过官方插件管理启停 Inspector，经同源鉴权代理完成实际 CDP。验证拒绝匿名直连、Host 和 ArkWeb 求值、原生快捷键打开 DevTools、端口释放及配置恢复。省略 `--panel` 时，仍执行 CDP 和访问控制检查。

```sh
python3 tests/smoke/emulator-inspector.py <loopback-target> .build/inspector.json --panel
```

## 工作树恢复和随包目录

在独立 Phone 模拟器安装 0.4.37 后执行下列命令。使用正式 PluginManager 启停并验证跨重启选择，再经 Forge RPC 还原真实 Git 工作树。测试仅暂停夹具的最终检出阶段，用实际受管进程验证 HTTP 取消。原 profile、锁文件和启动配置在结束后按字节恢复。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-worktree-restore.py <loopback-target> .build/worktree-restore.json --catalog
```

## 会话标题与徽标技能

在独立 Phone 模拟器安装 0.4.38 后，用临时模型凭据执行以下验证。脚本通过插件管理启停两个包，核对标题来源、固定与重启，以及技能目录、内容、官方资源和工作区产出。退出时恢复原配置及锁文件。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-titles-badge.py <loopback-target> .build/titles-badge.json
```

## DeepSeek 会话导入

在独立 Phone 模拟器安装 0.4.39，用合成的 v3 档案验证正式上传、错误处理、原图回读和真实模型续接。测试结束归档夹具会话、移除夹具工作区登记并恢复原配置。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-chat-import.py <loopback-target> .build/chat-import.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-chat-import-ui.py <loopback-target> .build/chat-import-ui.json
```

## 插件市场与跨重启回滚

在独立 Phone 模拟器安装 0.4.41。脚本用 HDC 反向映射自建索引与 npm 仓库，验证实际安装、依赖、升级、拒绝不兼容版本、激活失败后回滚与卸载。更新或回滚返回 `module-comparison` 时，按 DSH 要求重启并重新调用工具。第二个脚本点开 ArkWeb 安装确认并取消，验证未下载归档。均恢复原配置、锁文件和启动模式。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-plugin-market.py <loopback-target> .build/plugin-market.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-plugin-market-ui.py <loopback-target> .build/plugin-market-ui.json
```

官方 DSH profile 的 `autoInstallPeers: false` 让插件复用包内依赖。插件可将 DSH Host 提供的 API 声明为 peer。若插件还需要 Host 和 profile 均未提供的 npm 库，可将其列入自己的 `dependencies`；只有具备缺省处理的库才适合列为 `optionalDependencies`。官方插件市场由用户添加索引来源。HarmonyOS profile 使用 pnpm 的普通可执行脚本写入 `node_modules/.bin`，安装期间仍禁用依赖生命周期脚本。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-plugin-public-graph.py <loopback-target> .build/plugin-public-graph.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-plugin-public-graph.py <loopback-target> .build/plugin-npm-native.json --native
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-plugin-public-graph.py <loopback-target> .build/plugin-npm-wrappers.json --native-wrapper
```

标准包入口测试依赖 `@node-rs/crc32` 和 `@parcel/watcher`，由包自身选择 Alpine ARM64 musl 二进制。在 DSH 管理的 Alpine Node 子进程中实际计算 CRC32、订阅文件创建、执行 `detect-libc` 命令和回收订阅。

## 思考内容翻译

在独立 Phone 模拟器执行。脚本通过正式导入接口创建合成会话，并用内嵌 ArkWeb 检查展开、原译文、跨重启复用、重试及取消。正常模式使用回环服务，`--live` 显式使用指定提供者。`--arkweb-live` 从页面触发真实 DeepSeek Flash 请求，并在移除测试密钥后重开已保存的译文。只提交合成文本，结束后恢复测试配置。

`--live public-proxy` 在同一次模拟器回归调用 Bing 和 Google 公网端点。需已有 macOS 回环 HTTP CONNECT 代理，临时服务只转发本夹具的固定合成文本。单独使用 `--live bing` 或 `--live google` 验证模拟器默认网络路径。

0.4.59 的匿名翻译读取 DSH 的代理路由。将 `HTTPS_PROXY` 写在应用私有 DSH home 的 `.env` 中并重新启动 Host，路由可同时配置 `NO_PROXY`。工程验收使用 `--live profile-proxy`，临时代理只接收对两个上游地址的 HTTPS CONNECT，保留原始翻译端点与 TLS 校验。应用退出测试后恢复原 `.env`。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-cot-translation.py <loopback-target> .build/cot-translation.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-cot-translation.py <loopback-target> .build/cot-flash.json --live deepseek-official
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-cot-translation.py <loopback-target> .build/cot-flash-arkweb.json \
  --live deepseek-official --arkweb-live
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-cot-translation.py <loopback-target> .build/cot-public-proxy.json \
  --live public-proxy
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-cot-translation.py <loopback-target> .build/cot-profile-proxy.json \
  --live profile-proxy
```

## 个性化推荐

覆盖安装对应 HAP 后，按顺序在独立 Phone 模拟器运行两条命令。两个测试会临时启用同一 profile 的个性化推荐和 Inspector，退出时恢复原配置。第二条会批准 Creator 生成仅含计数器的本地页面，然后验证操作、撤销、重启和从原副本恢复。它同时核对恢复未触发新的模型回合。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" python3 tests/smoke/emulator-personalized-recommendations.py <loopback-target> .build/recommendation-cards.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" python3 tests/smoke/emulator-personalized-recommendations.py <loopback-target> .build/recommendation-creator.json --create
```

## Forge GitHub

Forge 继续使用官方 GitHub provider，鸿蒙包将脚本调用转发给随包签名的 `/usr/bin/gh`。CLI 从应用私有 `/native-benchmark-home/.config/gh` 读取账号配置。模拟器夹具对 GitHub 兼容的 REST 和 GraphQL 路径执行实际 TLS 请求，用临时 CA 与合成凭据，退出后恢复原始文件。

从 DSH 的「设置 → 通用设置 → Forge GitHub 账号」可用 GitHub CLI 设备授权流程登录。原生页面显示一次性代码并提供系统浏览器入口。取消时终止该 CLI 进程，退出登录使用 CLI 的本地账号管理。凭据由包内 GitHub CLI 管理，界面状态仅保存流程阶段、一次性代码和账号名。 [GitHub CLI 登录文档](https://cli.github.com/manual/gh_auth_login)

```sh
python3 tests/smoke/emulator-forge-github.py <loopback-target> .build/forge-github.json
python3 tests/smoke/emulator-forge-github.py <loopback-target> .build/forge-github-writes.json --writes
python3 tests/smoke/emulator-forge-github.py <loopback-target> .build/forge-github-public.json --public-read
python3 tests/smoke/emulator-forge-account.py <loopback-target> .build/forge-account.json
```

`--writes` 用包内 gh 在隔离服务验证带行范围的评审、邀请评审和绑定当前提交的合并。脚本检查 403 拒绝、旧提交拒绝、503 的未知结果与无重复提交，并在 Host 重启后完成合并。

`--public-read` 使用已登录的桌面 gh 查询 GM-HZ/omnix 的公开 PR #9。测试代理仅转发该 PR 的固定只读 GraphQL 查询和一个固定提交的文件读取。模拟器使用一次性夹具凭据，GitHub 账号凭据由桌面 gh 持有。文件逐字核对，提交和父提交与 GitHub REST 结果比对。

## LiveShare

独立 Phone 模拟器使用仅回环可达的测试 Relay 和一次性会话。独立查看者读取已共享的页面和历史，同工作区未共享会话及 Owner 管理接口会拒绝访问。验收也覆盖 Host 重启重连、撤销查看者授权、删除共享及停用网关。加 `--model` 可验证查看者通过真实 DeepSeek Flash 完成一轮对话，并在历史中核对其身份。脚本在结束时恢复 profile，移除测试凭据和转发。

加 `--owner-login` 可以通过实际 ArkWeb 的分享对话框打开授权，点击测试 Relay 的同意按钮并检查 PKCE 交换与身份显示。测试 Relay 使用本机回环和临时身份，生产 Relay 的部署与真实身份提供方单独验证。

加 `--guest-uploads` 会运行共享页面随包提供的上传脚本及官方 viewer carrier。测试经实际 Host 和回环 Relay 上传一个文本文件和两张图片，把返回的票据提交给 DeepSeek Flash，并核对会话范围、真实访客身份及取消。可在同一次添加多个文件，访客页面依次发送每个文件。单个文件上限 16 MiB，Host 和 Relay 仍可配置更小的限制。加 `--attachments` 另外验证主人提交的图片在 Host 重启后仍能由访客读取。

加 `--program-policy` 使用 PTC 预设，在同一会话同时开设只读和可写链接。真实模型调用 `run_code`，检查原生 worker 获准的模式、作用域、单次生命周期和派生会话的撤销。测试另核对主人直接执行、访客申请扩大权限时的拒绝及程序调用内置写工具的权限。需要测试模型凭据。与 `--owner-login` 分开运行。

```sh
python3 tests/smoke/emulator-liveshare-relay.py <loopback-target> .build/liveshare-relay.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-liveshare-relay.py <loopback-target> .build/liveshare-model.json --model
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-liveshare-relay.py <loopback-target> .build/liveshare-owner.json \
  --owner-login --model
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-liveshare-relay.py <loopback-target> .build/liveshare-program.json \
  --program-policy
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-liveshare-relay.py <loopback-target> .build/liveshare-visitors.json \
  --guest-uploads --attachments
```

加 `--cross-device <second-loopback-target>` 时，测试 Relay 会把 owner 的 index 资源取回并注入官方 `viewerCarrierScript`，再在第二台模拟器的系统浏览器打开 viewer 页面。测试检查浏览器 UA、`/__liveshare/context`、页面资源与会话 cookie 的 `session/list` 调用，并核对界面出现观看者只读提示。owner 侧的已有 reader 回归会先撤销访问再经夹具 admin 恢复，第二台设备因此是真实读者。该链路使用自建 Relay 与本机 `hdc rport`，不是官方公网 Relay。

```sh
python3 tests/smoke/emulator-liveshare-relay.py <loopback-target> .build/liveshare-cross-device.json \
  --cross-device <second-loopback-target>
```

加 `--owner-login` 时先用实际 ArkWeb 完成分享授权（测试 Relay 的 PKCE 交换），再让第二台设备读取带历史消息的共享会话；viewer 页面会显示共享会话标题、消息和时间戳。该组合不需要 `MH_TEST_DEEPSEEK_API_KEY`，模型路由取本机 `session/modelCatalog` 的默认项。

```sh
python3 tests/smoke/emulator-liveshare-relay.py <loopback-target> .build/liveshare-owner-cross-device.json \
  --owner-login --cross-device <second-loopback-target>
```

桌面装有 Chrome 和 Playwright CLI 时，可以打开实际分享页面，从对话框选择文件并发送。下列测试通过回环 Relay 转发真实页面资源，按 Viewer 身份核对模型回合。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-liveshare-browser.py <loopback-target> .build/liveshare-browser.json \
  --playwright-cli <cli-or-wrapper-path>
```

## Goal 跨重启续跑

使用 DeepSeek Flash 驱动同一个 Goal 的三轮文件操作。前两轮达到轮次上限后重启 Host，检查历史、轮次和文件保持一致。修改目标和上限后先验证旧修订无法恢复，再通过当前修订恢复。第三轮实际写入检查点并完成 Goal。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-goal-restart.py <loopback-target> .build/goal-restart.json
```

## 鸿蒙语音

在独立 Phone 模拟器安装对应 HAP。先准备上游 RC.5 锁定的 SenseVoice int8 模型、词表及 Silero VAD，放在同一测试输入目录。官方模型清单位于锁定 DSH 的 `packages/experimental/speech-to-text-sensevoice/runtime/assets.json`。测试临时填充 App 私有模型缓存，校验后加载，再验证普通话转写、无效音频与关闭回收。退出后移除测试缓存并恢复原配置。可选 `--arkweb` 使用真实模拟器触屏启动 ArkWeb 录音，采集合成音频并验证草稿和取消。使用 `--download` 可从空缓存经独立限速镜像准备原始模型。真机麦克风单独验收。使用 `--public-download auto` 会从空缓存走应用默认公网来源，并核对下载文件的原始 SHA-256。

可选 `--native-mic` 使用独立的调试模拟器和未授权的初始麦克风状态。测试触屏点击 DSH 录音按钮，通过系统弹窗授予权限，核对真实 ArkWeb 音轨进入 live、取消后进入 ended，结束时恢复系统权限。该步骤仅保留状态证据。可与 `--arkweb` 一起运行。

```sh
python3 tests/smoke/emulator-voice-input.py <loopback-target> .build/voice-api.json \
  --model-root <fixture-model-dir> --audio <16k-mono-pcm16-wav>
```

多模态回归用两个随机生成的 PNG，在真实 DeepSeek Flash 会话读取四个色块，随后核对重启前后的附件数据。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-deepseek-vision.py <loopback-target> .build/deepseek-vision.json
```

从独立的本机 Git 服务测试固定提交包的安装、拒绝未固定的升级、同来源升级及重启保留。

```sh
python3 tests/smoke/emulator-plugin-git-update.py <loopback-target> .build/git-plugin-upgrade.json
```
