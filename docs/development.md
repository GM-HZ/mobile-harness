# 鸿蒙构建与验证

使用 DevEco Studio SDK 26 和 ARM64 Phone。构建使用 DevEco 自带的 JDK、Node、ohpm 和 hvigor。普通构建的调试包保持 `org.sayact.nodepoc`，用于兼容已有签名和测试数据。

## 获取源码

```sh
git submodule update --init --depth=1
./scripts/vendor/verify.sh
```

父仓库 Git 链接固定每个组件的完整提交。当前直接子模块为 DSH、Node、Termux PRoot、DSHM 和 Termony。构建只读取锁定的子模块，DSHM 的 fetch shim 与许可证直接取自相应子模块。Termony 的嵌套终端组件在当前路径未使用。升级子模块时先提交并推送上游改动，再更新父仓库的 Git 链接。

## 准备输入并打包

1. 备齐 [输入清单](build-inputs.sha256) 指定的 0.4.24 原始打包输入，保留清单中的相对路径。已有开发机的输入存放在 `.build/inputs/harmonyos/`，也可通过 `HARMONY_INPUTS_DIR` 指向一份外部输入目录。当前配方使用已校验的 Node 和 PRoot 输入。DSH 源码固定到发布标签，构建用 [npm 锁文件](../runtime/harmonyos/dsh/package-lock.json) 装配上游发布包，并核对随包原生绑定对应的上游字节。首次准备需要访问 npm 和 Alpine 稳定仓库。新增 Alpine 包可预填至 `.build/runtime-package-inputs/` 或通过 `HARMONY_GUEST_APKS_DIR` 提供已经校验的归档。
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

## Host 进程探针

```sh
HARMONY_EXPERIMENTAL_HOST_PROCESS=1 ./build.sh
```

此模式在 `.build/stage/harmonyos-process-probe/` 生成独立包 `org.mobileharness.processprobe`。它使用实验性的进程启动方式，适用于 Phone 模拟器实验。原生恢复页在实验包中终止并重新启动 Host，同时 UI 可继续运行。普通构建仍由应用内 Node 启动，恢复页以重新打开应用为恢复边界。使用同一模拟器验证两种包时，应先停止另一包，两个 DSH 实例使用同一个回环端口。
