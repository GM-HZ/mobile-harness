# 鸿蒙构建与验证

使用 DevEco Studio SDK 26 和 ARM64 Phone。构建使用 DevEco 自带的 JDK、Node、ohpm 和 hvigor。普通构建的调试包保持 `org.sayact.nodepoc`，用于兼容已有签名和测试数据。

## 获取源码

```sh
git submodule update --init --depth=1
./scripts/vendor/verify.sh
```

父仓库 Git 链接固定每个组件的完整提交。当前直接子模块为 DSH、Node、Termux PRoot、DSHM、Termony、TypeScript language server 和 TypeScript。构建只读取锁定的子模块，DSHM 的 fetch shim 与许可证直接取自相应子模块。Termony 的嵌套终端组件在当前路径未使用。升级子模块时先提交并推送上游改动，再更新父仓库的 Git 链接。

## 准备输入并打包

1. 备齐 [输入清单](build-inputs.sha256) 指定的 0.4.24 原始打包输入，保留清单中的相对路径。已有开发机的输入存放在 `.build/inputs/harmonyos/`，也可通过 `HARMONY_INPUTS_DIR` 指向一份外部输入目录。当前配方使用已校验的 Node 和 PRoot 输入。DSH 源码子模块固定到官方 RC.4 发布标签，运行时用 [npm 锁文件](../runtime/harmonyos/dsh/package-lock.json) 装配上游发布包，并核对随包原生绑定对应的上游字节。首次准备需要访问 npm 和 Alpine 稳定仓库。新增 Alpine 包可预填至 `.build/runtime-package-inputs/` 或通过 `HARMONY_GUEST_APKS_DIR` 提供已经校验的归档。
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

标准工具测试创建自己的目标与团队任务，验证强停重开后状态，最后清除目标、关闭团队模式并删去自己的文件。交互测试通过鉴权 Remote Events 模拟回答和计划决定，不需要真人点击；插件发现只批准本次列表读取。网页夹具临时反向映射电脑上的受控 HTTP/1 服务，实际客户端和 DSH 工具运行于模拟器，退出时清除端口与测试凭据。`--search` 额外调用真实 DeepSeek 搜索 API。

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
```

后者用标准临时 bundle 验证真正的 provider，包括 stdin/stdout、特殊字符 argv、真实嵌套 Node、环境脱敏／覆盖／删除、非零退出、尾部限额与完整 spill、实际运行中的取消和 Context 销毁。PRoot 取消可能报告退出码1；脚本保留此事实并要求进程范围退出和 helper 回收。两者恢复原 manifest／锁文件并回读摘要，移除本次测试目录和凭据。设计和失败原因见 [Host 子进程](research/harmonyos-host-subprocess.md)。不要在同一模拟器并行运行修改 profile 的回归。

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

以下三个脚本要求已经安装普通0.4.35包。手动脚本验证真实摘要、事实回忆和同会话重启；故障脚本临时安装一个标准 bundle，在收到真实模型文本后才取消或注入流错误；自动脚本复制完整standard到独立临时预设，仅降低压缩阈值／保留预算，保留全部工具，不修改正式默认配置。结束后恢复原预设、profile、锁文件、凭据和普通模式。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-compaction.py <loopback-target> .build/compaction.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-compaction-faults.py <loopback-target> .build/compaction-faults.json
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-compaction-auto.py <loopback-target> .build/compaction-auto.json
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
